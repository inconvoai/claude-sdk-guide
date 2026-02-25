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
    InconvoToolsOptions,
    InconvoToolsState,
    inconvo_data_agent_server,
)

CLAUDE_MODEL = "claude-sonnet-4-6"
CHAT_TIMEOUT_SECONDS = float(os.getenv("CHAT_TIMEOUT_SECONDS", "120"))
SYSTEM_PROMPT = "\n".join(
    [
        "When you receive structured data (tables, charts) from tools, do NOT recreate or reformat them as markdown tables in your response.",
        "The tool output is rendered directly as UI.",
        "You may provide brief context and insights, but never duplicate data from tool output.",
        "Conversation policy: reuse the same data-analyst conversation for follow-up requests.",
        "Only replace the conversation when there is a clear topic reset.",
        "When replacing, call start_data_agent_conversation with force_new=true.",
    ]
)


@dataclass
class ClaudeChatSession:
    client: Any
    tools_state: InconvoToolsState
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


async def _create_session(
    anthropic_api_key: str,
    inconvo_agent_id: str,
) -> ClaudeChatSession:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

    _require_env("INCONVO_API_KEY")
    tools_state = InconvoToolsState()

    client = ClaudeSDKClient(
        ClaudeAgentOptions(
            tools=[],
            mcp_servers={
                "data-analyst": inconvo_data_agent_server(
                    InconvoToolsOptions(
                        agent_id=inconvo_agent_id,
                        user_identifier="user-123",
                        user_context={"organisationId": 1},
                    ),
                    state=tools_state,
                )
            },
            model=CLAUDE_MODEL,
            system_prompt=SYSTEM_PROMPT,
            env={
                "ANTHROPIC_API_KEY": anthropic_api_key,
                "HOME": _ensure_claude_home(),
            },
        )
    )
    await client.connect()

    return ClaudeChatSession(client=client, tools_state=tools_state)


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
            session.tools_state.on_tool_call = on_tool_call
            try:
                assistant_text = await asyncio.wait_for(
                    _run_claude_turn(session, text),
                    timeout=CHAT_TIMEOUT_SECONDS,
                )
            finally:
                session.tools_state.on_tool_call = None

        return ChatResponse(
            assistant_text=assistant_text,
            tool_calls=tool_calls,
            session_id=session_id,
            conversation_id=session.tools_state.conversation_id,
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
