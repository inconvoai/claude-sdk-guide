# Backend (FastAPI + Claude Agent SDK)

This backend exposes `POST /chat` and wires a local `inconvo_claude_sdk` package into Claude Agent SDK custom tools.
It keeps a persistent `ClaudeSDKClient` per `session_id` so tool/session context is maintained across turns.

## Environment

Copy `.env.example` to `.env` and set:

- `ANTHROPIC_API_KEY`
- `INCONVO_API_KEY`
- `INCONVO_AGENT_ID`
- `CHAT_TIMEOUT_SECONDS` (optional, default `120`)

The backend uses inline defaults for user values:

- `user_identifier = "user-123"`
- `user_context = {"organisationId": 1}`

## Install

```bash
python3.10 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Run

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info
```

## Local package API

`src/inconvo_claude_sdk` exports:

- `get_data_agent_connected_data_summary(...)`
- `start_data_agent_conversation(...)`
- `message_data_agent(...)`
- `inconvo_data_agent(...)`

`inconvo_data_agent(...)` auto-creates `Inconvo` from `INCONVO_API_KEY` unless you pass a client explicitly.

```python
from inconvo_claude_sdk import inconvo_data_agent

data_agent = inconvo_data_agent(
    agent_id=os.environ["INCONVO_AGENT_ID"],
    user_identifier="user-123",
    user_context={"organisationId": 1},
)

agent_options = ClaudeAgentOptions(
    tools=[],
    model="claude-sonnet-4-6",
    mcp_servers={"data-analyst": data_agent},
    allowed_tools=[
        "mcp__data-analyst__get_data_agent_connected_data_summary",
        "mcp__data-analyst__start_data_agent_conversation",
        "mcp__data-analyst__message_data_agent",
    ],
)
```
