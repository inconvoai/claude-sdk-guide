export async function POST(req: Request) {
  const backendBaseUrl =
    process.env.PYTHON_BACKEND_URL ?? "http://127.0.0.1:8000";
  const controller = new AbortController();
  const timeoutMs = 120_000;
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

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
    const upstream = await fetch(`${backendBaseUrl}/chat`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: rawBody,
      cache: "no-store",
      signal: controller.signal,
    });

    const responseText = await upstream.text();
    return new Response(responseText, {
      status: upstream.status,
      headers: {
        "content-type":
          upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return Response.json(
        {
          error: "Python backend timed out.",
          details: `No response after ${timeoutMs / 1000} seconds.`,
        },
        { status: 504 },
      );
    }

    return Response.json(
      {
        error: "Failed to reach Python backend.",
        details: error instanceof Error ? error.message : String(error),
      },
      { status: 502 },
    );
  } finally {
    clearTimeout(timeout);
  }
}
