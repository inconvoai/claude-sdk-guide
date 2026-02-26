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
