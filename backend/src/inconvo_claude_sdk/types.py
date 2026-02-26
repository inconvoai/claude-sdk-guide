from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class InconvoToolsOptions:
    agent_id: str
    user_identifier: str
    user_context: dict[str, str | int | float | bool]
    inconvo: AsyncInconvo | None = None
    message_description: str | None = None


@dataclass
class InconvoToolsState:
    conversation_id: str | None = None
    on_tool_call: ToolCallLogger | None = None
