# Frontend (Next.js)

This frontend keeps the existing chat UI and renders Inconvo tool outputs (text/table/chart), but no longer uses Vercel AI SDK.

## Environment

Copy `.env.example` to `.env.local` and set:

- `PYTHON_BACKEND_URL` (default: `http://127.0.0.1:8000`)

## Install and Run

```bash
pnpm install
pnpm dev
```

## Chat Flow

1. `app/page.tsx` manages local chat state
2. User message is posted to `app/api/chat/route.ts`
3. Route proxies to Python backend `/chat`
4. Assistant text + tool outputs are rendered in the UI
