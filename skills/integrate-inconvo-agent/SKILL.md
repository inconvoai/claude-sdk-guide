---
name: integrate-inconvo-agent
description: Add Inconvo data-agent tools to an already-running Python Claude Agent SDK agent. Use when you already have `ClaudeSDKClient` + `ClaudeAgentOptions` and need copy-ready `inconvo_claude_sdk` code plus exact wiring steps for `mcp_servers`, `allowed_tools`, subagents, and optional streaming/tool-call callbacks.
---

# Integrate Inconvo Agent

## Overview
Use this skill when the target project already has a working Claude Agent SDK agent loop and you only need to integrate Inconvo tools.

This skill is self-contained: it includes the full tool package code so users do not need this repository checked out.

## Assumption
Start from an existing Claude agent setup that already does all of the following:
- Builds `ClaudeAgentOptions`
- Creates and connects `ClaudeSDKClient`
- Runs `client.query(...)` + `client.receive_response()`

## Integration Steps (Existing Agent)
1. Copy the four Python files below into `src/inconvo_claude_sdk/` in the target project.
2. Install the Inconvo SDK (`claude-agent-sdk` is assumed to already exist in the project).

```bash
pip install inconvo
```

3. Patch your existing agent-options builder to register Inconvo server/tools/subagent.

```python
import os

from claude_agent_sdk import ClaudeAgentOptions
from inconvo_claude_sdk import (
    DATA_AGENT_SUBAGENT_NAME,
    INCONVO_SERVER,
    inconvo_data_agent,
    inconvo_data_agent_definition,
)

SUBAGENT_MAX_MESSAGES = 5
SUBAGENT_TOOLS = [
    f"mcp__{INCONVO_SERVER}__start_data_agent_conversation",
    f"mcp__{INCONVO_SERVER}__message_data_agent",
]

data_agent = inconvo_data_agent(
    agent_id=os.environ["INCONVO_AGENT_ID"],
    user_identifier=user_identifier,  # from your auth/session
    user_context=user_context,        # from your auth/session
    max_messages_per_conversation=SUBAGENT_MAX_MESSAGES,
)

agent_options = ClaudeAgentOptions(
    # keep your existing options
    mcp_servers={
        **existing_mcp_servers,
        INCONVO_SERVER: data_agent,
    },
    allowed_tools=[
        *existing_allowed_tools,
        "Task",
        f"mcp__{INCONVO_SERVER}__get_data_agent_connected_data_summary",
    ],
    agents={
        **existing_agents,
        **inconvo_data_agent_definition(
            tools=SUBAGENT_TOOLS,
            max_messages_per_conversation=SUBAGENT_MAX_MESSAGES,
        ),
    },
    can_use_tool=_permission_handler,
)
```

4. Add an allow-list permission handler so top-level agent cannot call unknown tools.

```python
async def _permission_handler(tool_name: str, tool_input: dict, _context):
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

    prefix = f"mcp__{INCONVO_SERVER}__"
    if tool_name.startswith(prefix):
        return PermissionResultAllow(updated_input=tool_input)

    return PermissionResultDeny(
        reason=f"Tool '{tool_name}' is not available. Use the Task tool to delegate to the {DATA_AGENT_SUBAGENT_NAME} subagent."
    )
```

5. Update your main agent `system_prompt` with these routing rules (append to your existing prompt):

```python
SYSTEM_PROMPT = "\n".join(
    [
        "Before your first data question, call get_data_agent_connected_data_summary to understand what data is available.",
        "Use this summary as internal context — don't include it in your response unless the user asks about available data.",
        "Use this context to write better, more specific tasks for the subagents.",
        f"You MUST use the Task tool to delegate data questions to the '{DATA_AGENT_SUBAGENT_NAME}' subagent.",
        "Do NOT call start_data_agent_conversation or message_data_agent directly — those are only available to the subagent.",
        "For multiple independent questions, spawn one subagent per question so they run in parallel.",
    ]
)
```

6. If your app streams status to UI, attach callbacks around each turn:
- `data_agent.set_tool_call_logger(...)`
- `data_agent.set_streaming_chunk_handler(...)`

7. Clear both handlers in `finally` after each turn.

## Copy-Ready Package: `src/inconvo_claude_sdk`

### `__init__.py`
```python
from .server import (
    DATA_AGENT_SUBAGENT_NAME,
    INCONVO_SERVER,
    allow_all_tools,
    inconvo_allowed_tools,
    inconvo_data_agent,
    inconvo_data_agent_definition,
)
from .tools import (
    DEFAULT_MESSAGE_DATA_AGENT_DESCRIPTION,
    get_data_agent_connected_data_summary,
    message_data_agent,
    start_data_agent_conversation,
)

__all__ = [
    "DATA_AGENT_SUBAGENT_NAME",
    "DEFAULT_MESSAGE_DATA_AGENT_DESCRIPTION",
    "INCONVO_SERVER",
    "allow_all_tools",
    "inconvo_allowed_tools",
    "inconvo_data_agent",
    "inconvo_data_agent_definition",
    "get_data_agent_connected_data_summary",
    "start_data_agent_conversation",
    "message_data_agent",
]
```

### `types.py`
```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TypedDict

from inconvo import AsyncInconvo

JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


class ToolCallRecord(TypedDict):
    name: str
    input: dict[str, Any]
    output: Any
    is_error: bool


ToolCallLogger = Callable[[ToolCallRecord], None]
StreamingChunkCallback = Callable[[str, str], None]  # (conversation_id, progress_message)


@dataclass
class InconvoToolsOptions:
    agent_id: str
    user_identifier: str
    user_context: dict[str, str | int | float | bool]
    inconvo: AsyncInconvo | None = None
    message_description: str | None = None
    max_messages_per_conversation: int = 5


@dataclass
class InconvoToolsState:
    conversation_ids: list[str] = field(default_factory=list)
    on_tool_call: ToolCallLogger | None = None
    on_streaming_chunk: StreamingChunkCallback | None = None
    message_counts: dict[str, int] = field(default_factory=dict)

    @property
    def conversation_id(self) -> str | None:
        """Most recently created conversation ID, for backwards compat."""
        return self.conversation_ids[-1] if self.conversation_ids else None
```

### `tools.py`
```python
from __future__ import annotations

import json
import os
from typing import Any, Callable

from inconvo import AsyncInconvo

from .types import InconvoToolsOptions, InconvoToolsState, ToolCallRecord

DEFAULT_MESSAGE_DATA_AGENT_DESCRIPTION = "\n".join(
    [
        "You are the orchestrator, not the analyst.",
        "Translate the user's request into a short, precise data question for the analyst.",
        "Keep one goal; include key constraints like time range, top/bottom N, and sort.",
        "Do not guess schema, fields, grain, or filters.",
        "Do not prescribe formulas or how to calculate metrics; let the analyst decide.",
        "If the user explicitly defines a metric, you may keep the metric name but drop the formula.",
        "Do not bundle multiple sub-questions or add formatting requirements.",
        "If the request is unclear, ask one clarifying question instead of making assumptions.",
        "You can use the 'get_data_agent_connected_data_summary' tool before the first question to learn what data is available.",
        "Do not repeat information already provided by the analyst in your user message.",
        "Do not define any metrics or calculations yourself; the data agent is the source of truth.",
        "If there is a question about how something from the data analyst was calculated, ask the analyst directly.",
        "You may run multiple independent data-agent conversations in parallel.",
        "Each call to start_data_agent_conversation creates a new conversation; pass its conversation_id to message_data_agent.",
    ]
)


def _get_tool_decorator() -> Callable[..., Any]:
    from claude_agent_sdk import tool

    return tool


def _validate_options(options: InconvoToolsOptions) -> None:
    if not options.agent_id:
        raise ValueError("agent_id is required.")


def _emit(state: InconvoToolsState, record: ToolCallRecord) -> None:
    if state.on_tool_call:
        state.on_tool_call(record)


def _serialize_response(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict(mode="json", use_api_names=True, exclude_unset=False)
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump(mode="json", by_alias=True)
    return value


def _as_tool_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)
    except TypeError:
        return str(value)


def _resolve_inconvo(options: InconvoToolsOptions) -> AsyncInconvo:
    if options.inconvo:
        return options.inconvo

    api_key = os.getenv("INCONVO_API_KEY")
    if not api_key:
        raise RuntimeError("Missing INCONVO_API_KEY for default Inconvo client.")
    return AsyncInconvo(api_key=api_key)


async def _create_conversation(
    inconvo: AsyncInconvo,
    options: InconvoToolsOptions,
    state: InconvoToolsState,
) -> str:
    if not options.user_identifier:
        raise ValueError("user_identifier is required.")
    if not options.user_context:
        raise ValueError("user_context is required.")

    conversation = await inconvo.agents.conversations.create(
        options.agent_id,
        user_identifier=options.user_identifier,
        user_context=options.user_context,
    )
    if not conversation or not conversation.id:
        raise RuntimeError("Failed to start conversation with data analyst.")

    state.conversation_ids.append(conversation.id)
    return conversation.id


def get_data_agent_connected_data_summary(
    options: InconvoToolsOptions,
    state: InconvoToolsState | None = None,
):
    _validate_options(options)
    resolved_state = state or InconvoToolsState()
    inconvo = _resolve_inconvo(options)
    tool_decorator = _get_tool_decorator()

    @tool_decorator(
        "get_data_agent_connected_data_summary",
        "Use this before your first question to get a high-level summary of connected data.",
        {},
    )
    async def _tool(args: dict[str, Any]) -> dict[str, Any]:
        tool_name = "get_data_agent_connected_data_summary"
        tool_input: dict[str, Any] = args or {}

        try:
            summary = await inconvo.agents.data_summary.retrieve(options.agent_id)
            result = summary.data_summary
            _emit(
                resolved_state,
                {
                    "name": tool_name,
                    "input": tool_input,
                    "output": result,
                    "is_error": False,
                },
            )
            return {"content": [{"type": "text", "text": _as_tool_text(result)}]}
        except Exception as exc:  # pragma: no cover - defensive path
            _emit(
                resolved_state,
                {
                    "name": tool_name,
                    "input": tool_input,
                    "output": {"error": str(exc)},
                    "is_error": True,
                },
            )
            return {"content": [{"type": "text", "text": f"Error: {exc}"}], "is_error": True}

    return _tool


def start_data_agent_conversation(
    options: InconvoToolsOptions,
    state: InconvoToolsState | None = None,
):
    _validate_options(options)
    resolved_state = state or InconvoToolsState()
    if not options.user_identifier:
        raise ValueError("user_identifier is required.")
    if not options.user_context:
        raise ValueError("user_context is required.")

    inconvo = _resolve_inconvo(options)
    tool_decorator = _get_tool_decorator()

    @tool_decorator(
        "start_data_agent_conversation",
        "Start a new data-agent conversation. Each call creates an independent conversation and returns its ID.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    async def _tool(args: dict[str, Any]) -> dict[str, Any]:
        tool_name = "start_data_agent_conversation"
        tool_input: dict[str, Any] = args or {}

        try:
            conversation_id = await _create_conversation(inconvo, options, resolved_state)
            result: dict[str, Any] = {"conversationId": conversation_id}

            _emit(
                resolved_state,
                {
                    "name": tool_name,
                    "input": tool_input,
                    "output": result,
                    "is_error": False,
                },
            )
            return {"content": [{"type": "text", "text": _as_tool_text(result)}]}
        except Exception as exc:  # pragma: no cover - defensive path
            _emit(
                resolved_state,
                {
                    "name": tool_name,
                    "input": tool_input,
                    "output": {"error": str(exc)},
                    "is_error": True,
                },
            )
            return {"content": [{"type": "text", "text": f"Error: {exc}"}], "is_error": True}

    return _tool


def message_data_agent(
    options: InconvoToolsOptions,
    state: InconvoToolsState | None = None,
):
    _validate_options(options)
    resolved_state = state or InconvoToolsState()

    inconvo = _resolve_inconvo(options)
    tool_decorator = _get_tool_decorator()
    analyst_description = options.message_description or DEFAULT_MESSAGE_DATA_AGENT_DESCRIPTION

    @tool_decorator(
        "message_data_agent",
        analyst_description,
        {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "Conversation ID. If omitted, the active conversation is reused.",
                },
                "message": {
                    "type": "string",
                    "description": "The user's analytics question, short and singular.",
                },
            },
            "required": ["message"],
        },
    )
    async def _tool(args: dict[str, Any]) -> dict[str, Any]:
        conversation_id = str(args.get("conversation_id", "")).strip()
        message = str(args.get("message", "")).strip()
        if not message:
            raise ValueError("message is required.")

        resolved_conversation_id = conversation_id or resolved_state.conversation_id
        if not resolved_conversation_id:
            resolved_conversation_id = await _create_conversation(inconvo, options, resolved_state)

        tool_name = "message_data_agent"
        tool_input: dict[str, Any] = {
            "conversation_id": resolved_conversation_id,
            "message": message,
        }

        count = resolved_state.message_counts.get(resolved_conversation_id, 0) + 1
        resolved_state.message_counts[resolved_conversation_id] = count
        if count > options.max_messages_per_conversation:
            limit_msg = (
                f"You have reached the {options.max_messages_per_conversation}-message "
                "limit for this conversation. Stop now and return the best answer you have."
            )
            _emit(resolved_state, {"name": tool_name, "input": tool_input, "output": limit_msg, "is_error": False})
            return {"content": [{"type": "text", "text": limit_msg}]}

        try:
            stream = await inconvo.agents.conversations.response.create(
                resolved_conversation_id,
                agent_id=options.agent_id,
                message=message,
                stream=True,
            )
            result = None
            async for event in stream:
                event_type = event.get("type") if isinstance(event, dict) else None
                if event_type == "response.progress":
                    progress_msg = event.get("message", "")
                    if resolved_state.on_streaming_chunk and progress_msg:
                        resolved_state.on_streaming_chunk(resolved_conversation_id, progress_msg)
                elif event_type == "response.completed":
                    completed = event.get("response")
                    if completed is not None:
                        result = _serialize_response(completed)
            if result is None:
                raise RuntimeError("No completed response received from Inconvo stream.")
            _emit(
                resolved_state,
                {
                    "name": tool_name,
                    "input": tool_input,
                    "output": result,
                    "is_error": False,
                },
            )
            return {"content": [{"type": "text", "text": _as_tool_text(result)}]}
        except Exception as exc:  # pragma: no cover - defensive path
            _emit(
                resolved_state,
                {
                    "name": tool_name,
                    "input": tool_input,
                    "output": {"error": str(exc)},
                    "is_error": True,
                },
            )
            return {"content": [{"type": "text", "text": f"Error: {exc}"}], "is_error": True}

    return _tool
```

### `server.py`
```python
from __future__ import annotations

from typing import Any

from inconvo import AsyncInconvo

from .tools import (
    get_data_agent_connected_data_summary,
    message_data_agent,
    start_data_agent_conversation,
)
from .types import InconvoToolsOptions, InconvoToolsState, StreamingChunkCallback, ToolCallLogger

INCONVO_SERVER = "data-analyst"

DATA_AGENT_SUBAGENT_NAME = "data-analyst-agent"

DATA_AGENT_SUBAGENT_PROMPT = "\n".join(
    [
        "You answer data questions by talking to the Inconvo data agent.",
        "1) If you don't already know what data is available, call get_data_agent_connected_data_summary first.",
        "2) Call start_data_agent_conversation to create a conversation.",
        "3) Call message_data_agent with the returned conversation_id and a direct, specific question.",
        "4) Review the response. If the answer is incomplete or you need a follow-up, send another message to the same conversation.",
        "   You may send multiple messages in one conversation — each should be a single, concrete question.",
        "5) Once you have a complete answer, return the analyst's data verbatim — do not reformat tables or charts.",
        "",
        "Rules:",
        "- Be direct: ask exactly what you need. No preamble, no filler, no open-ended exploration.",
        "- One question per message. Never bundle multiple questions together.",
        "- Use precise constraints: time ranges, filters, top/bottom N, sort order.",
        "- Do not guess column names, metrics, or schema — let the analyst resolve those.",
        "- Do not ask the analyst to explain methodology unless the user specifically asked for it.",
    ]
)


def inconvo_allowed_tools(server_name: str = INCONVO_SERVER) -> list[str]:
    """All MCP tool names for this server."""
    prefix = f"mcp__{server_name}__"
    return [
        f"{prefix}get_data_agent_connected_data_summary",
        f"{prefix}start_data_agent_conversation",
        f"{prefix}message_data_agent",
    ]


def inconvo_data_agent_definition(
    server_name: str = INCONVO_SERVER,
    tools: list[str] | None = None,
    max_messages_per_conversation: int | None = None,
) -> dict[str, Any]:
    """Return an AgentDefinition dict for the data-analyst subagent.

    Pass ``tools`` to explicitly control which MCP tools the subagent can use.
    Pass ``max_messages_per_conversation`` to append a hard-limit instruction to the prompt.
    """
    from claude_agent_sdk import AgentDefinition

    prompt = DATA_AGENT_SUBAGENT_PROMPT
    if max_messages_per_conversation is not None:
        prompt += (
            f"\nYou have a hard limit of {max_messages_per_conversation} message(s) per conversation. "
            "Plan your question carefully and get the answer within that limit. "
            "If you are close to the limit, return the best answer you have rather than asking a follow-up."
        )

    return {
        DATA_AGENT_SUBAGENT_NAME: AgentDefinition(
            description="Answers a single data question by talking to the Inconvo data agent. Use for parallel independent questions.",
            prompt=prompt,
            tools=tools if tools is not None else inconvo_allowed_tools(server_name),
        ),
    }


async def allow_all_tools(
    _tool_name: str,
    tool_input: dict[str, Any],
    _context: Any,
) -> Any:
    from claude_agent_sdk import PermissionResultAllow

    return PermissionResultAllow(updated_input=tool_input)


def _create_inconvo_data_agent_server(
    options: InconvoToolsOptions,
    state: InconvoToolsState,
    server_name: str,
):
    from claude_agent_sdk import create_sdk_mcp_server

    tools = [
        get_data_agent_connected_data_summary(options, state),
        start_data_agent_conversation(options, state),
        message_data_agent(options, state),
    ]

    return create_sdk_mcp_server(
        name=server_name,
        version="1.0.0",
        tools=tools,
    )


class InconvoDataAgentServer(dict[str, Any]):
    def __init__(self, server: dict[str, Any], state: InconvoToolsState):
        super().__init__(server)
        self._state = state

    @property
    def conversation_id(self) -> str | None:
        return self._state.conversation_id

    @property
    def conversation_ids(self) -> list[str]:
        return list(self._state.conversation_ids)

    def set_tool_call_logger(self, logger: ToolCallLogger | None) -> None:
        self._state.on_tool_call = logger

    def clear_tool_call_logger(self) -> None:
        self._state.on_tool_call = None

    def set_streaming_chunk_handler(self, handler: StreamingChunkCallback | None) -> None:
        self._state.on_streaming_chunk = handler

    def clear_streaming_chunk_handler(self) -> None:
        self._state.on_streaming_chunk = None


def inconvo_data_agent(
    *,
    agent_id: str,
    user_identifier: str,
    user_context: dict[str, str | int | float | bool],
    inconvo: AsyncInconvo | None = None,
    message_description: str | None = None,
    server_name: str = INCONVO_SERVER,
    max_messages_per_conversation: int = 5,
) -> InconvoDataAgentServer:
    state = InconvoToolsState()
    options = InconvoToolsOptions(
        agent_id=agent_id,
        user_identifier=user_identifier,
        user_context=user_context,
        inconvo=inconvo,
        message_description=message_description,
        max_messages_per_conversation=max_messages_per_conversation,
    )

    server = _create_inconvo_data_agent_server(
        options,
        state,
        server_name=server_name,
    )
    return InconvoDataAgentServer(server=server, state=state)
```

## Runtime Wiring Checklist
- Provide backend env vars: `ANTHROPIC_API_KEY`, `INCONVO_API_KEY`, `INCONVO_AGENT_ID`.
- Resolve `user_identifier` and `user_context` server-side.
- Keep tool names unchanged:
  - `get_data_agent_connected_data_summary`
  - `start_data_agent_conversation`
  - `message_data_agent`
- Keep structured outputs intact; do not reformat tables/charts into markdown.
- Enforce `max_messages_per_conversation` to avoid unbounded loops.

## Optional: Bundle References
The same files are also bundled as plain Python files under:
- `references/inconvo_claude_sdk/__init__.py`
- `references/inconvo_claude_sdk/types.py`
- `references/inconvo_claude_sdk/tools.py`
- `references/inconvo_claude_sdk/server.py`
