import { useState, useRef, useEffect } from "react";
import type { Paper, ChatMessage } from "../types";
import { loadSettings } from "../utils/storage";

interface ChatPanelProps {
  paper: Paper | null;
  onClose: () => void;
}

export default function ChatPanel({ paper, onClose }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const messagesEnd = useRef<HTMLDivElement>(null);

  const settings = loadSettings();

  useEffect(() => {
    if (paper) {
      setMessages([
        {
          role: "system",
          content: `你正在讨论的论文: "${paper.title}"。摘要: ${paper.abstract}`,
        },
      ]);
    }
  }, [paper]);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || sending) return;

    const userMsg: ChatMessage = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSending(true);

    if (!settings.ai_api_key) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "请先在设置页面配置 AI API Key。" },
      ]);
      setSending(false);
      return;
    }

    try {
      const apiMessages = [
        ...messages.filter((m) => m.role === "system"),
        ...messages.filter((m) => m.role !== "system").slice(-10),
        userMsg,
      ];

      const resp = await fetch(`${settings.ai_api_base}/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${settings.ai_api_key}`,
        },
        body: JSON.stringify({
          model: settings.ai_model,
          messages: apiMessages.map((m) => ({ role: m.role, content: m.content })),
          temperature: 0.7,
          max_tokens: 2048,
        }),
      });

      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.error?.message || `HTTP ${resp.status}`);
      }

      const reply = data.choices?.[0]?.message?.content || "(无回复)";
      setMessages((prev) => [...prev, { role: "assistant", content: reply }]);
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `错误: ${err.message}` },
      ]);
    } finally {
      setSending(false);
    }
  };

  if (!paper) return null;

  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-white shadow-xl border-l border-gray-200 flex flex-col z-20">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
        <h2 className="text-sm font-semibold text-gray-900 truncate flex-1 mr-2">
          讨论: {paper.title}
        </h2>
        <button
          onClick={onClose}
          className="p-1 text-gray-400 hover:text-gray-600 cursor-pointer"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages
          .filter((m) => m.role !== "system")
          .map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[85%] px-4 py-2 rounded-lg text-sm ${
                  msg.role === "user"
                    ? "bg-indigo-600 text-white"
                    : "bg-gray-100 text-gray-800"
                }`}
              >
                <p className="whitespace-pre-wrap">{msg.content}</p>
              </div>
            </div>
          ))}
        {sending && (
          <div className="flex justify-start">
            <div className="bg-gray-100 px-4 py-2 rounded-lg text-sm text-gray-500">
              思考中...
            </div>
          </div>
        )}
        <div ref={messagesEnd} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-gray-200">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder="输入问题讨论这篇论文..."
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            disabled={sending}
          />
          <button
            onClick={sendMessage}
            disabled={sending || !input.trim()}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-colors"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
