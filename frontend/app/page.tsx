"use client";

import { useState } from "react";
import { InconvoToolResult } from "./components/inconvo";
import type { ChatRequest, ChatResponse, ToolCall } from "./types/inconvo";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  toolResults?: unknown[];
};

const shouldRenderToolCall = (call: ToolCall): boolean => {
  if (
    call.name === "start_data_agent_conversation" ||
    call.name === "get_data_agent_connected_data_summary"
  ) {
    return false;
  }

  if (
    call.output &&
    typeof call.output === "object" &&
    !Array.isArray(call.output)
  ) {
    const keys = Object.keys(call.output as Record<string, unknown>);
    if (keys.length === 1 && keys[0] === "conversationId") {
      return false;
    }
  }

  return true;
};

export default function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [loadingItems, setLoadingItems] = useState<
    Array<{ description: string; conversationId?: string; progress?: string; completed?: boolean }>
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);

  const sendMessage = async () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text: trimmed,
    };

    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setInput("");
    setError(null);
    setIsLoading(true);
    setLoadingItems([]);

    try {
      const nextSessionId =
        messages.length === 0 || !sessionId ? crypto.randomUUID() : sessionId;
      if (nextSessionId !== sessionId) {
        setSessionId(nextSessionId);
      }

      const payload: ChatRequest = {
        text: trimmed,
        session_id: nextSessionId,
      };

      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok || !response.body) {
        const text = await response.text();
        throw new Error(text || "Request failed.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const processChunk = (chunk: string) => {
        buffer += chunk;
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";

        for (const raw of events) {
          const dataLine = raw.split("\n").find((l) => l.startsWith("data: "));
          if (!dataLine) continue;
          try {
            const event = JSON.parse(dataLine.slice(6)) as Record<string, unknown>;

            if (event.type === "task_start") {
              setLoadingItems((prev) => [
                ...prev,
                { description: event.description as string },
              ]);
            } else if (event.type === "conversation_start") {
              const convId = event.conversation_id as string;
              setLoadingItems((prev) => {
                const idx = prev.findIndex((item) => !item.conversationId);
                if (idx === -1) return prev;
                const next = [...prev];
                next[idx] = { ...next[idx], conversationId: convId };
                return next;
              });
            } else if (event.type === "inconvo_progress") {
              const convId = event.conversation_id as string;
              const msg = event.message as string;
              setLoadingItems((prev) =>
                prev.map((item) =>
                  item.conversationId === convId
                    ? { ...item, progress: msg, completed: false }
                    : item,
                ),
              );
            } else if (event.type === "conversation_complete") {
              const convId = event.conversation_id as string;
              setLoadingItems((prev) =>
                prev.map((item) =>
                  item.conversationId === convId
                    ? { ...item, completed: true }
                    : item,
                ),
              );
            } else if (event.type === "complete") {
              const success = event as unknown as ChatResponse;
              if (success.session_id && success.session_id !== sessionId) {
                setSessionId(success.session_id);
              }
              const assistantMessage: ChatMessage = {
                id: crypto.randomUUID(),
                role: "assistant",
                text: success.assistant_text ?? "",
                toolResults:
                  success.tool_calls
                    ?.filter(shouldRenderToolCall)
                    .map((call) => call.output) ?? [],
              };
              setMessages((prev) => [...prev, assistantMessage]);
            } else if (event.type === "error") {
              throw new Error((event.detail as string) || "Request failed.");
            }
          } catch (parseError) {
            if (parseError instanceof Error && parseError.message !== "Unexpected end of JSON input") {
              throw parseError;
            }
          }
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        processChunk(decoder.decode(value, { stream: true }));
      }
      if (buffer.trim()) processChunk("\n\n");

    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : String(requestError),
      );
    } finally {
      setIsLoading(false);
      setLoadingItems([]);
    }
  };

  return (
    <div className="flex flex-col w-full max-w-4xl py-24 mx-auto px-4">
      {messages.map((message) => (
        <div key={message.id} className="mb-4">
          <div className="font-semibold mb-1">
            {message.role === "user" ? "User" : "AI"}:
          </div>
          <div>
            {message.text && (
              <div className="whitespace-pre-wrap">{message.text}</div>
            )}
            {message.text && message.toolResults && message.toolResults.length > 0 && (
              <hr className="my-4 border-zinc-200 dark:border-zinc-700" />
            )}
            {message.toolResults?.map((result, i) => (
              <InconvoToolResult key={`${message.id}-tool-${i}`} result={result} />
            ))}
          </div>
        </div>
      ))}

      {isLoading && (
        <div className="mb-4">
          <div className="font-semibold mb-1">AI:</div>
          <div className="p-4 text-sm text-zinc-500">
            <div className="flex items-center gap-2">
              <div className="animate-spin h-4 w-4 shrink-0 border-2 border-zinc-300 border-t-zinc-600 rounded-full" />
              <span>
                {loadingItems.length > 0 && loadingItems.every((i) => i.completed)
                  ? "Writing response..."
                  : "Querying your data..."}
              </span>
            </div>
            {loadingItems.length > 0 && (
              <ul className="mt-2 ml-6 space-y-1 text-xs text-zinc-400">
                {loadingItems.map((item, i) => (
                  <li key={i} className={item.completed ? "text-zinc-600 dark:text-zinc-500" : ""}>
                    {item.completed ? "✓" : <span className="inline-block animate-spin" style={{ animationDuration: "3s", animationDelay: `-${(Date.now() % 3000) / 1000}s` }}>*</span>}{" "}{item.description}
                    {item.completed ? null : item.progress ? (
                      <span className="ml-2 italic text-zinc-500">— {item.progress}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <form
        onSubmit={async (e) => {
          e.preventDefault();
          await sendMessage();
        }}
      >
        <input
          className="fixed dark:bg-zinc-900 bottom-0 w-full max-w-4xl p-2 mb-8 border border-zinc-300 dark:border-zinc-800 rounded shadow-xl"
          value={input}
          disabled={isLoading}
          placeholder="Say something..."
          onChange={(e) => setInput(e.currentTarget.value)}
        />
      </form>
    </div>
  );
}
