export type InconvoResponse = {
  type: "text" | "table" | "chart" | "error";
  message: string;
  table?: {
    head: string[];
    body: string[][];
  };
  chart?: {
    type: "bar" | "line";
    xLabel?: string;
    yLabel?: string;
    data:
      | Array<{ label: string; value: number }>
      | {
          labels: string[];
          datasets: Array<{ name: string; values: number[] }>;
        };
  };
  spec?: Record<string, unknown>;
};

export type ToolCall = {
  name: string;
  input: Record<string, unknown>;
  output: unknown;
  is_error: boolean;
};

export type ChatRequestMessage = {
  role: "user" | "assistant";
  text: string;
};

export type ChatResponse = {
  assistant_text: string;
  tool_calls: ToolCall[];
};
