/**
 * Type guard to check if a tool output is an Inconvo response
 * based on its structure (type field with text/table/chart values)
 */
export function isInconvoOutput(output: unknown): boolean {
  return (
    typeof output === "object" &&
    output !== null &&
    "type" in output &&
    typeof (output as any).type === "string" &&
    ["text", "table", "chart"].includes((output as any).type)
  );
}
