import { useState, useRef, useEffect, useCallback } from "react";
import type { Paper, ChatMessage } from "../types";
import { loadSettings } from "../utils/storage";

interface PaperViewerProps {
  paper: Paper;
  onClose: () => void;
}

export default function PaperViewer({ paper, onClose }: PaperViewerProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [fullTextLoading, setFullTextLoading] = useState(false);
  const [fullTextLoaded, setFullTextLoaded] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<"paper" | "chat">("paper");
  const messagesEnd = useRef<HTMLDivElement>(null);

  const settings = loadSettings();

  const systemPrompt = `你正在讨论以下论文:

标题: ${paper.title}
作者: ${paper.authors.join(", ")}
分类: ${paper.categories.join(", ")}
arXiv ID: ${paper.arxiv_id}

摘要: ${paper.abstract}

请基于以上信息回答用户关于这篇论文的问题。你可以解释论文的核心贡献、方法论、实验结果、与其他工作的关系等。如果用户询问论文中未提及的细节，请诚实地说明。`;

  useEffect(() => {
    setMessages([{ role: "system", content: systemPrompt }]);
  }, [paper.arxiv_id]);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const fetchFullText = useCallback(async () => {
    setFullTextLoading(true);
    try {
      const resp = await fetch(
        `https://ar5iv.labs.arxiv.org/html/${paper.arxiv_id}`
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const html = await resp.text();
      const div = document.createElement("div");
      div.innerHTML = html;

      // Remove math, scripts, styles, nav
      div.querySelectorAll("script, style, nav, .ltx_navbar, math").forEach((el) => el.remove());

      const text = (div.textContent || "").replace(/\s{3,}/g, "\n").trim();
      const truncated = text.slice(0, 15000);

      const fullPrompt = `${systemPrompt}

以下是论文的完整内容（供参考，优先基于此内容回答用户问题）:
${truncated}`;

      setMessages((prev) => {
        const filtered = prev.filter((m) => m.role !== "system");
        return [{ role: "system", content: fullPrompt }, ...filtered];
      });
      setFullTextLoaded(true);
    } catch (err: any) {
      console.warn("Failed to fetch full text:", err.message);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "未能获取论文全文，将基于摘要进行讨论。部分较新的论文可能尚未在 ar5iv 上渲染。",
        },
      ]);
    } finally {
      setFullTextLoading(false);
    }
  }, [paper.arxiv_id]);

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

  return (
    <div className="fixed inset-0 bg-white z-20 flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={onClose}
            className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg cursor-pointer transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <h2 className="text-sm font-semibold text-gray-900 truncate">{paper.title}</h2>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {/* Full text button */}
          {!fullTextLoaded && (
            <button
              onClick={fetchFullText}
              disabled={fullTextLoading}
              className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50 cursor-pointer transition-colors"
            >
              {fullTextLoading ? "加载全文中..." : "加载论文全文"}
            </button>
          )}
          {fullTextLoaded && (
            <span className="text-xs text-green-600 px-2">全文已加载</span>
          )}
          {/* PDF link */}
          <a
            href={paper.pdf_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs px-3 py-1.5 bg-gray-900 text-white rounded-lg hover:bg-gray-800 cursor-pointer transition-colors"
          >
            打开 PDF
          </a>
        </div>
      </header>

      {/* Mobile tab switcher */}
      <div className="flex lg:hidden border-b border-gray-200 shrink-0">
        <button
          onClick={() => setSidebarTab("paper")}
          className={`flex-1 py-2.5 text-sm font-medium text-center transition-colors cursor-pointer ${
            sidebarTab === "paper"
              ? "text-indigo-600 border-b-2 border-indigo-600"
              : "text-gray-500"
          }`}
        >
          论文
        </button>
        <button
          onClick={() => setSidebarTab("chat")}
          className={`flex-1 py-2.5 text-sm font-medium text-center transition-colors cursor-pointer ${
            sidebarTab === "chat"
              ? "text-indigo-600 border-b-2 border-indigo-600"
              : "text-gray-500"
          }`}
        >
          讨论
        </button>
      </div>

      {/* Content: split layout */}
      <div className="flex-1 flex min-h-0">
        {/* Left: Paper viewer (desktop always visible, mobile conditional) */}
        <div
          className={`${
            sidebarTab === "paper" ? "flex" : "hidden"
          } lg:flex flex-col w-full lg:w-1/2 border-r border-gray-200`}
        >
          {/* Paper metadata */}
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 shrink-0">
            <p className="text-xs text-gray-500 mb-1">
              {paper.authors.slice(0, 5).join(", ")}
              {paper.authors.length > 5 && ` et al.`}
            </p>
            <p className="text-xs text-gray-400">{paper.categories.join(" · ")}</p>
          </div>
          {/* arXiv abstract page iframe */}
          <iframe
            src={`https://arxiv.org/abs/${paper.arxiv_id}`}
            className="flex-1 w-full border-0"
            title={`arXiv: ${paper.arxiv_id}`}
          />
        </div>

        {/* Right: Chat panel (desktop always visible, mobile conditional) */}
        <div
          className={`${
            sidebarTab === "chat" ? "flex" : "hidden"
          } lg:flex flex-col w-full lg:w-1/2`}
        >
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
                    className={`max-w-[85%] px-4 py-2.5 rounded-lg text-sm leading-relaxed ${
                      msg.role === "user"
                        ? "bg-indigo-600 text-white"
                        : "bg-gray-100 text-gray-800"
                    }`}
                  >
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  </div>
                </div>
              ))}
            {messages.filter((m) => m.role !== "system").length === 0 && (
              <div className="text-center text-gray-400 mt-20">
                <svg className="w-12 h-12 mx-auto mb-3 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
                <p className="text-sm">点击"加载论文全文"后开始讨论</p>
                <p className="text-xs mt-1">或直接输入问题，基于摘要进行讨论</p>
              </div>
            )}
            {sending && (
              <div className="flex justify-start">
                <div className="bg-gray-100 px-4 py-2 rounded-lg text-sm text-gray-500 flex items-center gap-2">
                  <div className="w-4 h-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
                  思考中...
                </div>
              </div>
            )}
            <div ref={messagesEnd} />
          </div>

          {/* Input */}
          <div className="p-4 border-t border-gray-200 bg-white">
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                placeholder="输入问题讨论这篇论文..."
                className="flex-1 px-4 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                disabled={sending}
              />
              <button
                onClick={sendMessage}
                disabled={sending || !input.trim()}
                className="px-5 py-2.5 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-colors"
              >
                发送
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
