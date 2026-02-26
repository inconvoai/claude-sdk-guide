from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from inconvo_claude_sdk import (
    DATA_AGENT_SUBAGENT_NAME,
    INCONVO_SERVER,
    inconvo_data_agent,
    inconvo_data_agent_definition,
)

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CHAT_TIMEOUT_SECONDS = float(os.getenv("CHAT_TIMEOUT_SECONDS", "120"))

SUBAGENT_MAX_MESSAGES = 5  # hard limit on message_data_agent calls per conversation

# Tools available to the main orchestrator agent
MAIN_AGENT_TOOLS = [
    "Task",
    f"mcp__{INCONVO_SERVER}__get_data_agent_connected_data_summary",
]

# Tools available to the data-analyst subagent
SUBAGENT_TOOLS = [
    f"mcp__{INCONVO_SERVER}__start_data_agent_conversation",
    f"mcp__{INCONVO_SERVER}__message_data_agent",
]
SYSTEM_PROMPT = "\n".join(
    [
        "When you receive structured data (tables, charts) from tools, do NOT recreate or reformat them as markdown tables in your response.",
        "The tool output is rendered directly as UI.",
        "You may provide brief context and insights, but never duplicate data from tool output.",
        "Before your first data question, call get_data_agent_connected_data_summary to understand what data is available.",
        "Use this summary as internal context — don't include it in your response unless the user asks about available data.",
        "Use this context to write better, more specific tasks for the subagents.",
        f"You MUST use the Task tool to delegate data questions to the '{DATA_AGENT_SUBAGENT_NAME}' subagent.",
        "Do NOT call start_data_agent_conversation or message_data_agent directly — those are only available to the subagent.",
        "For multiple independent questions, spawn one subagent per question so they run in parallel.",
    ]
)


@dataclass
class ClaudeChatSession:
    client: Any
    data_agent: Any
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_SESSIONS: dict[str, ClaudeChatSession] = {}
_SESSIONS_LOCK = asyncio.Lock()


class ChatRequest(BaseModel):
    text: str
    session_id: str | None = None


class ToolCall(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    is_error: bool = False


class ChatResponse(BaseModel):
    assistant_text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    session_id: str
    conversation_id: str | None = None


app = FastAPI(title="Inconvo + Claude SDK Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _ensure_claude_home() -> str:
    configured = os.getenv("CLAUDE_HOME_DIR")
    home_dir = Path(configured) if configured else Path(__file__).resolve().parent.parent / ".claude-home"
    home_dir.mkdir(parents=True, exist_ok=True)
    return str(home_dir)


async def _run_claude_turn(session: ClaudeChatSession, prompt: str) -> str:
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

    await session.client.query(prompt)

    chunks: list[str] = []
    final_result: ResultMessage | None = None

    async for message in session.client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
        elif isinstance(message, ResultMessage):
            final_result = message

    if final_result and final_result.is_error:
        detail = final_result.result or f"Claude returned error subtype: {final_result.subtype}"
        raise RuntimeError(detail)

    return "\n".join(chunk for chunk in chunks if chunk).strip()


async def _permission_handler(
    tool_name: str,
    tool_input: dict[str, Any],
    _context: Any,
) -> Any:
    """Allow MCP tools (needed by subagents), deny everything else."""
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

    prefix = f"mcp__{INCONVO_SERVER}__"
    if tool_name.startswith(prefix):
        return PermissionResultAllow(updated_input=tool_input)

    return PermissionResultDeny(
        reason=f"Tool '{tool_name}' is not available. Use the Task tool to delegate to the {DATA_AGENT_SUBAGENT_NAME} subagent."
    )


async def _create_session(
    anthropic_api_key: str,
    inconvo_agent_id: str,
) -> ClaudeChatSession:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    _require_env("INCONVO_API_KEY")

    # You can get the user context values 
    # from your JWT or whatever mechanism you have 
    # to identify your users server side
    data_agent = inconvo_data_agent(
        agent_id=inconvo_agent_id,
        user_identifier="user-123",
        user_context={"orgId": 1},
        max_messages_per_conversation=SUBAGENT_MAX_MESSAGES,
    )

    agent_options = ClaudeAgentOptions(
        mcp_servers={
            INCONVO_SERVER: data_agent,
        },
        allowed_tools=MAIN_AGENT_TOOLS,
        can_use_tool=_permission_handler,
        agents=inconvo_data_agent_definition(
            tools=SUBAGENT_TOOLS,
            max_messages_per_conversation=SUBAGENT_MAX_MESSAGES,
        ),
        model=CLAUDE_MODEL,
        system_prompt=SYSTEM_PROMPT,
        include_partial_messages=True,
        env={
            "ANTHROPIC_API_KEY": anthropic_api_key,
            "HOME": _ensure_claude_home(),
        },
    )

    client = ClaudeSDKClient(agent_options)
    await client.connect()

    return ClaudeChatSession(
        client=client,
        data_agent=data_agent,
    )


async def _get_or_create_session(
    session_id: str,
    anthropic_api_key: str,
    inconvo_agent_id: str,
) -> ClaudeChatSession:
    existing = _SESSIONS.get(session_id)
    if existing:
        return existing

    async with _SESSIONS_LOCK:
        existing = _SESSIONS.get(session_id)
        if existing:
            return existing

        created = await _create_session(
            anthropic_api_key=anthropic_api_key,
            inconvo_agent_id=inconvo_agent_id,
        )
        _SESSIONS[session_id] = created
        return created


@app.get("/health")
async def health() -> dict[str, str | int]:
    return {"status": "ok", "active_sessions": len(_SESSIONS)}


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "message": "Use POST /chat"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text cannot be empty")

    session_id = request.session_id or uuid4().hex

    try:
        session = await _get_or_create_session(
            session_id=session_id,
            anthropic_api_key=_require_env("ANTHROPIC_API_KEY"),
            inconvo_agent_id=_require_env("INCONVO_AGENT_ID"),
        )

        tool_calls: list[ToolCall] = []

        def on_tool_call(record: dict[str, Any]) -> None:
            tool_calls.append(ToolCall(**record))

        async with session.lock:
            session.data_agent.set_tool_call_logger(on_tool_call)
            try:
                assistant_text = await asyncio.wait_for(
                    _run_claude_turn(session, text),
                    timeout=CHAT_TIMEOUT_SECONDS,
                )
            finally:
                session.data_agent.clear_tool_call_logger()

        return ChatResponse(
            assistant_text=assistant_text,
            tool_calls=tool_calls,
            session_id=session_id,
            conversation_id=session.data_agent.conversation_id,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Chat timed out after {int(CHAT_TIMEOUT_SECONDS)} seconds.",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Chat processing failed: {exc}") from exc


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text cannot be empty")

    session_id = request.session_id or uuid4().hex

    try:
        session = await _get_or_create_session(
            session_id=session_id,
            anthropic_api_key=_require_env("ANTHROPIC_API_KEY"),
            inconvo_agent_id=_require_env("INCONVO_AGENT_ID"),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def generate():
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
        from claude_agent_sdk.types import StreamEvent

        event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        tool_calls: list[ToolCall] = []
        result_holder: dict[str, Any] = {}

        def on_tool_call(record: dict[str, Any]) -> None:
            tool_calls.append(ToolCall(**record))
            if record.get("name") == "start_data_agent_conversation":
                output = record.get("output", {})
                if isinstance(output, dict) and "conversationId" in output:
                    event_queue.put_nowait({
                        "type": "conversation_start",
                        "conversation_id": output["conversationId"],
                    })
            elif record.get("name") == "message_data_agent":
                conv_id = record.get("input", {}).get("conversation_id")
                if conv_id:
                    event_queue.put_nowait({
                        "type": "conversation_complete",
                        "conversation_id": conv_id,
                    })

        def on_chunk(conversation_id: str, progress_msg: str) -> None:
            event_queue.put_nowait({
                "type": "inconvo_progress",
                "conversation_id": conversation_id,
                "message": progress_msg,
            })

        async def run_turn() -> None:
            try:
                await session.client.query(text)

                chunks: list[str] = []
                final_result: ResultMessage | None = None
                pending_task_inputs: dict[int, str] = {}

                async for message in session.client.receive_response():
                    if isinstance(message, StreamEvent):
                        event = message.event
                        event_type = event.get("type")

                        if event_type == "content_block_start":
                            cb = event.get("content_block", {})
                            idx = event.get("index", -1)
                            if cb.get("type") == "tool_use" and cb.get("name") == "Task":
                                pending_task_inputs[idx] = ""

                        elif event_type == "content_block_delta":
                            idx = event.get("index", -1)
                            delta = event.get("delta", {})
                            if delta.get("type") == "input_json_delta" and idx in pending_task_inputs:
                                pending_task_inputs[idx] += delta.get("partial_json", "")

                        elif event_type == "content_block_stop":
                            idx = event.get("index", -1)
                            if idx in pending_task_inputs:
                                raw = pending_task_inputs.pop(idx)
                                try:
                                    task_input = json.loads(raw) if raw else {}
                                except json.JSONDecodeError:
                                    task_input = {}
                                description = task_input.get("description", json.dumps(task_input))
                                event_queue.put_nowait({"type": "task_start", "description": description})

                    elif isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                chunks.append(block.text)

                    elif isinstance(message, ResultMessage):
                        final_result = message

                if final_result and final_result.is_error:
                    detail = final_result.result or f"Claude returned error: {final_result.subtype}"
                    result_holder["error"] = detail
                else:
                    result_holder["assistant_text"] = "\n".join(c for c in chunks if c).strip()

            except Exception as exc:
                result_holder["error"] = f"Chat processing failed: {exc}"
            finally:
                event_queue.put_nowait(None)  # sentinel

        try:
            async with session.lock:
                session.data_agent.set_tool_call_logger(on_tool_call)
                session.data_agent.set_streaming_chunk_handler(on_chunk)
                try:
                    turn_task = asyncio.create_task(run_turn())

                    while True:
                        item = await event_queue.get()
                        if item is None:
                            break
                        yield f"data: {json.dumps(item)}\n\n"

                    await turn_task
                finally:
                    session.data_agent.clear_tool_call_logger()
                    session.data_agent.clear_streaming_chunk_handler()

            if "error" in result_holder:
                yield f"data: {json.dumps({'type': 'error', 'detail': result_holder['error']})}\n\n"
                return

            response = ChatResponse(
                assistant_text=result_holder.get("assistant_text", ""),
                tool_calls=tool_calls,
                session_id=session_id,
                conversation_id=session.data_agent.conversation_id,
            )
            yield f"data: {json.dumps({'type': 'complete', **response.model_dump()})}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    for session in list(_SESSIONS.values()):
        try:
            await session.client.disconnect()
        except Exception:
            pass
    _SESSIONS.clear()
