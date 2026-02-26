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
