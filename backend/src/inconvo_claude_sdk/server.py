from __future__ import annotations

from typing import Any

from inconvo import AsyncInconvo

from .tools import (
    get_data_agent_connected_data_summary,
    message_data_agent,
    start_data_agent_conversation,
)
from .types import InconvoToolsOptions, InconvoToolsState, ToolCallLogger

INCONVO_SERVER = "data-analyst"

DATA_AGENT_SUBAGENT_NAME = "data-analyst-agent"

DATA_AGENT_SUBAGENT_PROMPT = "\n".join(
    [
        "You answer data questions by talking to the Inconvo data agent.",
        "1) Call start_data_agent_conversation to create a conversation.",
        "2) Call message_data_agent with the returned conversation_id and a clear, focused message.",
        "3) Review the response. If you need more data to fully answer the question, send additional messages to the same conversation.",
        "   Each message should be tight and specific — ask for exactly what you still need.",
        "4) Once you have everything, return the analyst's data verbatim — do not reformat tables or charts.",
        "Keep messages short and precise. Do not bundle multiple questions into one message.",
    ]
)


def inconvo_allowed_tools(server_name: str = INCONVO_SERVER) -> list[str]:
    prefix = f"mcp__{server_name}__"
    return [
        f"{prefix}get_data_agent_connected_data_summary",
        f"{prefix}start_data_agent_conversation",
        f"{prefix}message_data_agent",
    ]


def inconvo_data_agent_definition(
    server_name: str = INCONVO_SERVER,
) -> dict[str, Any]:
    """Return an AgentDefinition dict for the data-analyst subagent."""
    from claude_agent_sdk import AgentDefinition

    return {
        DATA_AGENT_SUBAGENT_NAME: AgentDefinition(
            description="Answers a single data question by talking to the Inconvo data agent. Use for parallel independent questions.",
            prompt=DATA_AGENT_SUBAGENT_PROMPT,
            tools=inconvo_allowed_tools(server_name),
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


def inconvo_data_agent(
    *,
    agent_id: str,
    user_identifier: str,
    user_context: dict[str, str | int | float | bool],
    inconvo: AsyncInconvo | None = None,
    message_description: str | None = None,
    server_name: str = INCONVO_SERVER,
) -> InconvoDataAgentServer:
    state = InconvoToolsState()
    options = InconvoToolsOptions(
        agent_id=agent_id,
        user_identifier=user_identifier,
        user_context=user_context,
        inconvo=inconvo,
        message_description=message_description,
    )

    server = _create_inconvo_data_agent_server(
        options,
        state,
        server_name=server_name,
    )
    return InconvoDataAgentServer(server=server, state=state)
