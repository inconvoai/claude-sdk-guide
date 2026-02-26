export async function POST(req: Request) {
  const backendBaseUrl =
    process.env.PYTHON_BACKEND_URL ?? "http://127.0.0.1:8000";

  let rawBody: string;
  try {
    rawBody = await req.text();
  } catch {
    return Response.json(
      { error: "Invalid request payload." },
      { status: 400 },
    );
  }

  try {
    const upstream = await fetch(`${backendBaseUrl}/chat/stream`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: rawBody,
      cache: "no-store",
    });

    if (!upstream.ok || !upstream.body) {
      const text = await upstream.text();
      return new Response(text, { status: upstream.status });
    }

    return new Response(upstream.body, {
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        "x-accel-buffering": "no",
      },
    });
  } catch (error) {
    return Response.json(
      {
        error: "Failed to reach Python backend.",
        details: error instanceof Error ? error.message : String(error),
      },
      { status: 502 },
    );
  }
}
