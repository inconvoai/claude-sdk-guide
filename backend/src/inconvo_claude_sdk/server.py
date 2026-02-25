from __future__ import annotations

from .tools import (
    get_data_agent_connected_data_summary,
    message_data_agent,
    start_data_agent_conversation,
)
from .types import InconvoToolsOptions, InconvoToolsState

DEFAULT_SERVER_NAME = "data-analyst-tools"


def sdk_tool_names() -> list[str]:
    return [
        "get_data_agent_connected_data_summary",
        "start_data_agent_conversation",
        "message_data_agent",
    ]


def allowed_tool_names(server_name: str = DEFAULT_SERVER_NAME) -> list[str]:
    return [f"mcp__{server_name}__{tool_name}" for tool_name in sdk_tool_names()]


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


def inconvo_data_agent_server(
    options: InconvoToolsOptions,
    state: InconvoToolsState | None = None,
    server_name: str = DEFAULT_SERVER_NAME,
):
    return _create_inconvo_data_agent_server(
        options,
        state or InconvoToolsState(),
        server_name=server_name,
    )
