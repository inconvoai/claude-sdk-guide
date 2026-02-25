import type { InconvoResponse } from "../../types/inconvo";
import { InconvoTable } from "./InconvoTable";
import { InconvoChart } from "./InconvoChart";

// Type guard for Inconvo responses
function isInconvoResponse(result: unknown): result is InconvoResponse {
  return (
    typeof result === "object" &&
    result !== null &&
    "type" in result &&
    typeof (result as any).type === "string" &&
    ["text", "table", "chart"].includes((result as any).type)
  );
}

export function InconvoToolResult({ result }: { result: unknown }) {

  // Handle string results (legacy or error cases)
  if (typeof result === "string") {
    try {
      const parsed = JSON.parse(result);
      return <InconvoToolResult result={parsed} />;
    } catch {
      return <div className="whitespace-pre-wrap">{result}</div>;
    }
  }

  // Handle array results (likely table data)
  if (Array.isArray(result)) {
    const table = {
      head: result.length > 0 ? Object.keys(result[0]) : [],
      body: result.map((row) => Object.values(row).map(String)),
    };
    return <InconvoTable message="Data" table={table} />;
  }

  // Handle Inconvo responses
  if (isInconvoResponse(result)) {
    const response = result as any; // Type assertion to handle SDK type limitations

    switch (response.type) {
      case "text":
        return <div className="whitespace-pre-wrap">{response.message}</div>;

      case "table":
        if (!response.table) {
          return <div className="text-zinc-500">{response.message}</div>;
        }
        return <InconvoTable message={response.message} table={response.table} />;

      case "chart":
        return (
          <InconvoChart
            message={response.message}
            spec={response.spec ?? undefined}
            chart={response.chart ?? undefined}
          />
        );

      default:
        // Handle any other types that might not be in the exported type
        if ("message" in response) {
          return (
            <div className="p-4 border border-zinc-300 dark:border-zinc-700 rounded-lg my-2">
              {String(response.message)}
            </div>
          );
        }
    }
  }

  // Fallback: render as formatted JSON
  return (
    <div className="p-4 border border-zinc-300 dark:border-zinc-700 rounded-lg my-2 bg-zinc-50 dark:bg-zinc-900">
      <pre className="text-xs overflow-auto whitespace-pre-wrap">
        {JSON.stringify(result, null, 2)}
      </pre>
    </div>
  );
}
