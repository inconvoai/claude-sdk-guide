from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Iterable
from typing import Any, Literal
from uuid import uuid4
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from inconvo import Inconvo
from pydantic import BaseModel, Field

from inconvo_claude_sdk import (
    InconvoToolsOptions,
    allowed_tool_names,
    create_inconvo_data_agent_server,
)

SERVER_NAME = "my-custom-tools"
DEFAULT_USER_IDENTIFIER = "user-123"
DEFAULT_USER_CONTEXT: dict[str, str | int | float | bool] = {"organisationId": 1}
CHAT_TIMEOUT_SECONDS = float(os.getenv("CHAT_TIMEOUT_SECONDS", "120"))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("inconvo_claude_backend")
logger.setLevel(logging.INFO)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    tool_results: list[dict[str, Any]] | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)


class ToolCall(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    is_error: bool = False


class ChatResponse(BaseModel):
    assistant_text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)


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


def _build_prompt(messages: Iterable[ChatMessage]) -> str:
    lines = [
        "When you receive structured data (tables, charts) from tools, do NOT recreate or reformat them as markdown tables in your response.",
        "The tool output is rendered directly as UI.",
        "You may provide brief context and insights, but never duplicate data from tool output.",
        "",
        "Conversation:",
    ]

    for msg in messages:
        speaker = "User" if msg.role == "user" else "Assistant"
        lines.append(f"{speaker}: {msg.text}")

    lines.append("Assistant:")
    return "\n".join(lines)


def _is_transport_close_error(exc: BaseException) -> bool:
    return "ProcessTransport is not ready for writing" in str(exc)


async def _run_claude_query(prompt: str, agent_options: Any) -> str:
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, query

    async def _prompt_stream() -> AsyncIterator[dict[str, Any]]:
        # Use AsyncIterable input so SDK MCP control protocol can keep stdin open
        # until the first result (avoids premature stream-close with SDK MCP tools).
        yield {
            "type": "user",
            "session_id": "",
            "message": {"role": "user", "content": prompt},
            "parent_tool_use_id": None,
        }

    chunks: list[str] = []
    final_result: ResultMessage | None = None
    saw_transport_close_error = False

    try:
        async for message in query(prompt=_prompt_stream(), options=agent_options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        chunks.append(block.text)
            elif isinstance(message, ResultMessage):
                final_result = message
    except ExceptionGroup as exc:
        if _is_transport_close_error(exc):
            saw_transport_close_error = True
            logger.warning(
                "Claude SDK transport closed while handling control message; continuing with collected output."
            )
        else:
            raise

    if final_result and final_result.is_error:
        detail = final_result.result or f"Claude returned error subtype: {final_result.subtype}"
        raise RuntimeError(detail)

    if not final_result and saw_transport_close_error:
        raise RuntimeError(
            "Claude CLI transport closed before returning a final result."
        )

    return "\n".join(chunk for chunk in chunks if chunk).strip()


def _ensure_claude_home() -> str:
    configured = os.getenv("CLAUDE_HOME_DIR")
    if configured:
        home_dir = Path(configured)
    else:
        home_dir = Path(__file__).resolve().parent.parent / ".claude-home"

    home_dir.mkdir(parents=True, exist_ok=True)
    return str(home_dir)


def _build_agent_options(custom_server: Any, anthropic_api_key: str) -> Any:
    from claude_agent_sdk import ClaudeAgentOptions

    def _stderr_logger(line: str) -> None:
        logger.info("claude-cli: %s", line)

    claude_env = {
        "ANTHROPIC_API_KEY": anthropic_api_key,
        "HOME": _ensure_claude_home(),
    }

    return ClaudeAgentOptions(
        mcp_servers={SERVER_NAME: custom_server},
        allowed_tools=allowed_tool_names(SERVER_NAME),
        env=claude_env,
        stderr=_stderr_logger,
        extra_args={"debug-to-stderr": None},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    logger.info("health check")
    return {"status": "ok"}


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "message": "Backend is running. Use /health or POST /chat."}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")

    request_id = uuid4().hex[:8]
    logger.info(
        "[%s] /chat received with %d message(s)",
        request_id,
        len(request.messages),
    )

    try:
        anthropic_api_key = _require_env("ANTHROPIC_API_KEY")
        inconvo = Inconvo(api_key=_require_env("INCONVO_API_KEY"))
        options = InconvoToolsOptions(
            agent_id=_require_env("INCONVO_AGENT_ID"),
            user_identifier=DEFAULT_USER_IDENTIFIER,
            user_context=DEFAULT_USER_CONTEXT,
            inconvo=inconvo,
        )

        tool_calls: list[ToolCall] = []

        def _logger(record: dict[str, Any]) -> None:
            tool_calls.append(ToolCall(**record))
            logger.info("[%s] tool call: %s", request_id, record.get("name"))

        options.on_tool_call = _logger

        logger.info("[%s] creating MCP server", request_id)
        custom_server = create_inconvo_data_agent_server(options, server_name=SERVER_NAME)
        agent_options = _build_agent_options(custom_server, anthropic_api_key)
        prompt = _build_prompt(request.messages)
        logger.info("[%s] executing Claude query", request_id)
        assistant_text = await asyncio.wait_for(
            _run_claude_query(prompt, agent_options),
            timeout=CHAT_TIMEOUT_SECONDS,
        )
        logger.info("[%s] Claude query complete", request_id)

        return ChatResponse(
            assistant_text=assistant_text,
            tool_calls=tool_calls,
        )
    except asyncio.TimeoutError as exc:
        logger.exception("[%s] timed out after %.0f seconds", request_id, CHAT_TIMEOUT_SECONDS)
        raise HTTPException(
            status_code=504,
            detail=f"Chat timed out after {int(CHAT_TIMEOUT_SECONDS)} seconds.",
        ) from exc
    except RuntimeError as exc:
        logger.exception("[%s] runtime error", request_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - network/sdk error path
        logger.exception("[%s] chat processing failed", request_id)
        error_text = str(exc)
        if "ProcessTransport is not ready for writing" in error_text:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Claude CLI transport closed during SDK MCP handling. "
                    "Verify ANTHROPIC_API_KEY and restart. "
                    "If it persists, remove stale Claude config and retry."
                ),
            ) from exc
        raise HTTPException(status_code=500, detail=f"Chat processing failed: {exc}") from exc
