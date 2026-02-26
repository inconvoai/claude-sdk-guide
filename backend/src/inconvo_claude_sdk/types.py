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


@dataclass
class InconvoToolsState:
    conversation_ids: list[str] = field(default_factory=list)
    on_tool_call: ToolCallLogger | None = None
    on_streaming_chunk: StreamingChunkCallback | None = None

    @property
    def conversation_id(self) -> str | None:
        """Most recently created conversation ID, for backwards compat."""
        return self.conversation_ids[-1] if self.conversation_ids else None
