"use client";

import { useEffect, useState } from "react";
import { InconvoToolResult } from "./components/inconvo";
import type { ChatRequest, ChatResponse, ToolCall } from "./types/inconvo";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  toolResults?: unknown[];
};
const SESSION_STORAGE_KEY = "inconvo_chat_session_id";

const shouldRenderToolCall = (call: ToolCall): boolean => {
  if (call.name === "start_data_agent_conversation") {
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
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);

  useEffect(() => {
    try {
      const storedSession = window.localStorage.getItem(SESSION_STORAGE_KEY);
      if (storedSession) {
        setSessionId(storedSession);
      } else {
        const generated = crypto.randomUUID();
        window.localStorage.setItem(SESSION_STORAGE_KEY, generated);
        setSessionId(generated);
      }
    } catch {
      // Ignore storage access issues in restricted browser modes.
    }
  }, []);

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
      const nextSessionId = sessionId ?? crypto.randomUUID();
      if (!sessionId) {
        setSessionId(nextSessionId);
        try {
          window.localStorage.setItem(SESSION_STORAGE_KEY, nextSessionId);
        } catch {
          // Ignore storage access issues.
        }
      }

      const payload: ChatRequest = {
        text: trimmed,
        session_id: nextSessionId,
      };

      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify(payload),
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
      if (success.session_id && success.session_id !== sessionId) {
        setSessionId(success.session_id);
        try {
          window.localStorage.setItem(SESSION_STORAGE_KEY, success.session_id);
        } catch {
          // Ignore storage access issues.
        }
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
