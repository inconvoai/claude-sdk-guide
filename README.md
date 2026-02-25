# Claude SDK Guide - Inconvo Python SDK Integration

This guide demonstrates a TypeScript-to-Python mapping of the Inconvo data-agent tool flow:

- Frontend: Next.js chat UI (`frontend/`)
- Backend: FastAPI + Claude Agent SDK + local `inconvo_claude_sdk` package (`backend/`)

The UI keeps the same feel as the original Vercel AI SDK example, but chat orchestration now happens in Python with Claude Agent SDK custom tools.

## Architecture

1. Browser posts chat history to `frontend/app/api/chat/route.ts`
2. Next.js proxy forwards to Python backend `POST /chat`
3. Backend registers 3 Inconvo tools via `create_sdk_mcp_server(...)`
4. Claude Agent SDK uses those tools during query execution
5. Backend returns:
   - `assistant_text`
   - `tool_calls[]` with structured outputs
6. Frontend renders assistant text + `InconvoToolResult` cards

## Project Layout

- `frontend/`: Next.js app and proxy route
- `backend/`: FastAPI server and local Python tool package (`src/inconvo_claude_sdk`)

## Prerequisites

- Node.js 18+
- pnpm
- Python 3.10+
- Anthropic API key
- Inconvo API key + agent id

User values are inline in backend code:

- `user_identifier = "user-123"`
- `user_context = {"organisationId": 1}`

## Run Locally

### Fast path (Makefile)

```bash
cd claude-sdk-guide
make bootstrap
make dev
```

`make dev` starts backend and frontend together.


### 1. Start the Python backend

```bash
cd claude-sdk-guide/backend
python3.10 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info
```

### 2. Start the Next.js frontend

```bash
cd claude-sdk-guide/frontend
cp .env.example .env.local
pnpm install
pnpm dev
```

Then open [http://localhost:3000](http://localhost:3000).

## Notes

- This implementation is intentionally non-streaming between frontend and backend.
- Tool outputs are still structured and rendered as cards/tables/charts.
- `inconvo_claude_sdk` is local for now and can be extracted to a PyPI package later.
