from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from inconvo_claude_sdk import (
    DATA_AGENT_SUBAGENT_NAME,
    INCONVO_SERVER,
    allow_all_tools,
    inconvo_data_agent,
    inconvo_data_agent_definition,
)

CLAUDE_MODEL = "claude-sonnet-4-6"
CHAT_TIMEOUT_SECONDS = float(os.getenv("CHAT_TIMEOUT_SECONDS", "120"))
SYSTEM_PROMPT = "\n".join(
    [
        "When you receive structured data (tables, charts) from tools, do NOT recreate or reformat them as markdown tables in your response.",
        "The tool output is rendered directly as UI.",
        "You may provide brief context and insights, but never duplicate data from tool output.",
        "Before your first data question, call get_data_agent_connected_data_summary to understand what data is available.",
        "Use this summary as internal context — don't include it in your response unless the user asks about available data.",
        "Use this context to write better, more specific tasks for the subagents.",
        f"Delegate all data questions to the '{DATA_AGENT_SUBAGENT_NAME}' subagent.",
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
    import logging
    import time

    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

    logger = logging.getLogger("claude_turn")

    await session.client.query(prompt)

    chunks: list[str] = []
    final_result: ResultMessage | None = None

    async for message in session.client.receive_response():
        msg_type = type(message).__name__
        logger.info("[%.3f] message: %s", time.time(), msg_type)
        if isinstance(message, AssistantMessage):
            for block in message.content:
                block_type = getattr(block, "type", None)
                block_name = getattr(block, "name", None)
                logger.info("  block: type=%s name=%s", block_type, block_name)
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
        elif isinstance(message, ResultMessage):
            final_result = message

    if final_result and final_result.is_error:
        detail = final_result.result or f"Claude returned error subtype: {final_result.subtype}"
        raise RuntimeError(detail)

    return "\n".join(chunk for chunk in chunks if chunk).strip()


async def _create_session(
    anthropic_api_key: str,
    inconvo_agent_id: str,
) -> ClaudeChatSession:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    _require_env("INCONVO_API_KEY")

    agent_options = ClaudeAgentOptions(
        tools=[],
        mcp_servers={
            INCONVO_SERVER: inconvo_data_agent(
                agent_id=inconvo_agent_id,
                user_identifier="user-123",
                user_context={"orgId": 1},
            )
        },
        allowed_tools=["Task", f"mcp__{INCONVO_SERVER}__get_data_agent_connected_data_summary"],
        can_use_tool=allow_all_tools,
        agents=inconvo_data_agent_definition(),
        model=CLAUDE_MODEL,
        system_prompt=SYSTEM_PROMPT,
        env={
            "ANTHROPIC_API_KEY": anthropic_api_key,
            "HOME": _ensure_claude_home(),
        },
    )

    client = ClaudeSDKClient(agent_options)
    await client.connect()

    return ClaudeChatSession(
        client=client,
        data_agent=agent_options.mcp_servers[INCONVO_SERVER],
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


@app.on_event("shutdown")
async def shutdown() -> None:
    for session in list(_SESSIONS.values()):
        try:
            await session.client.disconnect()
        except Exception:
            pass
    _SESSIONS.clear()
