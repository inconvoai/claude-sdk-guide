"use client";

import { useState } from "react";
import { InconvoToolResult } from "./components/inconvo";
import type { ChatRequestMessage, ChatResponse } from "./types/inconvo";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  toolResults?: unknown[];
};

const toRequestMessages = (messages: ChatMessage[]): ChatRequestMessage[] =>
  messages.map((message) => ({
    role: message.role,
    text: message.text,
  }));

export default function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({
          messages: toRequestMessages(nextMessages),
        }),
      });

      const data = (await response.json()) as
        | ChatResponse
        | { detail?: string; error?: string; details?: string };
      if (!response.ok) {
        throw new Error(
          ("detail" in data && data.detail) ||
            ("error" in data && data.error) ||
            ("details" in data && data.details) ||
            "Request failed.",
        );
      }

      const success = data as ChatResponse;
      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        text: success.assistant_text ?? "",
        toolResults: success.tool_calls?.map((call) => call.output) ?? [],
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : String(requestError),
      );
    } finally {
      setIsLoading(false);
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
            {message.toolResults?.map((result, i) => (
              <InconvoToolResult key={`${message.id}-tool-${i}`} result={result} />
            ))}
          </div>
        </div>
      ))}

      {isLoading && (
        <div className="mb-4">
          <div className="font-semibold mb-1">AI:</div>
          <div className="flex items-center gap-2 p-4 text-sm text-zinc-500">
            <div className="animate-spin h-4 w-4 border-2 border-zinc-300 border-t-zinc-600 rounded-full" />
            <div>
              <div>Querying your data...</div>
              <div className="text-xs mt-1">
                This may take a few moments for complex queries
              </div>
            </div>
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
