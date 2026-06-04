import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import type { Paper, ChatMessage } from "../types";
import { loadSettings } from "../utils/storage";

interface PaperViewerProps {
  paper: Paper;
  onClose: () => void;
}

// Simple markdown renderer — handles bold, italic, code, lists, links, headings
function renderMarkdown(text: string): string {
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Code blocks (```...```)
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g,
    '<pre class="bg-gray-800 text-green-100 rounded p-3 my-2 overflow-x-auto text-xs"><code>$2</code></pre>');
  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code class="bg-gray-200 text-red-600 px-1 py-0.5 rounded text-xs">$1</code>');
  // Bold
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // Italic
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  // Headings
  html = html.replace(/^### (.+)$/gm, '<h4 class="font-semibold text-sm mt-3 mb-1">$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3 class="font-semibold text-sm mt-3 mb-1">$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2 class="font-semibold text-base mt-3 mb-1">$1</h2>');
  // Unordered lists
  html = html.replace(/^- (.+)$/gm, '<li class="ml-4 list-disc">$1</li>');
  // Numbered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li class="ml-4 list-decimal">$1</li>');
  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" class="text-indigo-600 underline">$1</a>');
  // Line breaks
  html = html.replace(/\n\n/g, '</p><p class="mb-2">');
  html = html.replace(/\n/g, '<br/>');
  html = `<p class="mb-2">${html}</p>`;

  return html;
}


export default function PaperViewer({ paper, onClose }: PaperViewerProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [fullTextLoading, setFullTextLoading] = useState(false);
  const [fullTextLoaded, setFullTextLoaded] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<"paper" | "chat">("paper");
  const [splitRatio, setSplitRatio] = useState(70); // paper % (default 70%)
  const [dragging, setDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const messagesEnd = useRef<HTMLDivElement>(null);

  const settings = loadSettings();

  const uniqueAffiliations = useMemo(() => {
    const seen = new Set<string>();
    return (paper.affiliations || [])
      .filter((a) => {
        if (!a.affiliation || seen.has(a.affiliation)) return false;
        seen.add(a.affiliation);
        return true;
      })
      .map((a) => a.affiliation);
  }, [paper.affiliations]);

  const systemPrompt = `你正在讨论以下论文:

标题: ${paper.title}
作者: ${paper.authors.join(", ")}
${uniqueAffiliations.length > 0 ? `机构: ${uniqueAffiliations.join(", ")}` : ""}
分类: ${paper.categories.join(", ")}
arXiv ID: ${paper.arxiv_id}

摘要: ${paper.abstract}

请基于以上信息回答用户关于这篇论文的问题。你可以解释论文的核心贡献、方法论、实验结果、与其他工作的关系等。如果用户询问论文中未提及的细节，请诚实地说明。`;

  useEffect(() => {
    setMessages([{ role: "system", content: systemPrompt }]);
    setFullTextLoaded(false);
  }, [paper.arxiv_id]);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Drag-to-resize handlers
  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setDragging(true);
  }, []);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
      setSplitRatio(Math.min(85, Math.max(30, pct)));
    };
    const onUp = () => setDragging(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging]);

  const fetchFullText = useCallback(async () => {
    setFullTextLoading(true);
    const sources = [
      `https://arxiv.org/html/${paper.arxiv_id}`,
      `https://ar5iv.labs.arxiv.org/html/${paper.arxiv_id}`,
    ];

    let success = false;
    for (const src of sources) {
      try {
        const resp = await fetch(src);
        if (!resp.ok) continue;

        const html = await resp.text();
        const div = document.createElement("div");
        div.innerHTML = html;
        div.querySelectorAll("script, style, nav, .ltx_navbar, math, .ltx_page_footer, .ltx_marksection").forEach((el) => el.remove());

        const text = (div.textContent || "").replace(/\s{3,}/g, "\n").trim();
        if (text.length < 500) continue; // too short, probably error page

        const truncated = text.slice(0, 15000);
        const fullPrompt = `${systemPrompt}

以下为论文全文（优先基于此内容回答）:
${truncated}`;

        setMessages((prev) => {
          const filtered = prev.filter((m) => m.role !== "system");
          return [{ role: "system", content: fullPrompt }, ...filtered];
        });
        setFullTextLoaded(true);
        success = true;
        break;
      } catch {
        continue;
      }
    }

    if (!success) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "自动获取全文失败，将基于摘要讨论。较新的论文可能在 arXiv 上尚无 HTML 版本，可尝试复制 PDF 文本到对话框中。",
        },
      ]);
    }
    setFullTextLoading(false);
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
        { role: "assistant", content: "请先在**设置**页面配置 AI API Key。" },
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
        { role: "assistant", content: `**错误**: ${err.message}` },
      ]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-white z-20 flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-gray-200 bg-white shrink-0">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <button
            onClick={onClose}
            className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg cursor-pointer transition-colors shrink-0"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <h2 className="text-sm font-semibold text-gray-900 truncate">{paper.title}</h2>
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-2">
          {!fullTextLoaded && (
            <button
              onClick={fetchFullText}
              disabled={fullTextLoading}
              className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50 cursor-pointer transition-colors"
            >
              {fullTextLoading ? "加载中..." : "加载全文到 AI"}
            </button>
          )}
          {fullTextLoaded && (
            <span className="text-xs text-green-600 px-2 font-medium">全文已加载</span>
          )}
          <a
            href={paper.pdf_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs px-3 py-1.5 bg-gray-900 text-white rounded-lg hover:bg-gray-800 cursor-pointer transition-colors"
          >
            PDF
          </a>
        </div>
      </header>

      {/* Paper metadata bar */}
      <div className="px-4 py-2 border-b border-gray-100 bg-gray-50 shrink-0">
        <p className="text-xs text-gray-500 mb-0.5">
          {paper.authors.slice(0, 6).join(", ")}
          {paper.authors.length > 6 && ` et al.`}
        </p>
        {uniqueAffiliations.length > 0 && (
          <p className="text-xs text-gray-400">
            {uniqueAffiliations.join("  ·  ")}
          </p>
        )}
      </div>

      {/* Mobile tab switcher */}
      <div className="flex lg:hidden border-b border-gray-200 shrink-0">
        <button onClick={() => setSidebarTab("paper")} className={`flex-1 py-2 text-sm font-medium text-center cursor-pointer ${sidebarTab === "paper" ? "text-indigo-600 border-b-2 border-indigo-600" : "text-gray-500"}`}>论文</button>
        <button onClick={() => setSidebarTab("chat")} className={`flex-1 py-2 text-sm font-medium text-center cursor-pointer ${sidebarTab === "chat" ? "text-indigo-600 border-b-2 border-indigo-600" : "text-gray-500"}`}>讨论</button>
      </div>

      {/* Split layout with draggable divider */}
      <div ref={containerRef} className={`flex-1 flex min-h-0 ${dragging ? "select-none cursor-col-resize" : ""}`}>
        {/* Left: Paper page */}
        <div
          className={`${sidebarTab === "paper" ? "flex" : "hidden"} lg:flex flex-col w-full`}
          style={{ width: sidebarTab === "paper" || window.innerWidth >= 1024 ? `${splitRatio}%` : "100%" }}
        >
          {/* Top bar with PDF fallback */}
          <div className="px-4 py-1.5 bg-gray-50 border-b border-gray-200 flex items-center justify-between shrink-0">
            <span className="text-xs text-gray-500">
              arXiv HTML 全文（部分论文无此版本）
            </span>
            <a
              href={paper.pdf_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs px-3 py-1 bg-gray-900 text-white rounded hover:bg-gray-800 cursor-pointer transition-colors shrink-0"
            >
              新窗口打开 PDF
            </a>
          </div>
          <iframe
            src={`https://arxiv.org/html/${paper.arxiv_id}`}
            className="flex-1 w-full border-0"
            title={`arXiv HTML: ${paper.arxiv_id}`}
            onError={(e) => {
              // Fallback to abstract page if HTML version not available
              (e.target as HTMLIFrameElement).src = `https://arxiv.org/abs/${paper.arxiv_id}`;
            }}
          />
        </div>

        {/* Drag handle (desktop only) */}
        <div
          className="hidden lg:flex w-2 bg-gray-200 hover:bg-indigo-400 cursor-col-resize shrink-0 items-center justify-center transition-colors"
          onMouseDown={onDragStart}
        >
          <div className="w-0.5 h-8 bg-gray-400 rounded" />
        </div>

        {/* Right: Chat */}
        <div
          className={`${sidebarTab === "chat" ? "flex" : "hidden"} lg:flex flex-col border-l border-gray-200`}
          style={{ width: `${100 - splitRatio}%` }}
        >
          <div className="px-3 py-2 border-b border-gray-100 bg-gray-50 shrink-0">
            <span className="text-xs text-gray-500 font-medium">AI 讨论</span>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {messages.filter((m) => m.role !== "system").map((msg, i) => (
              <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[90%] px-3 py-2 rounded-lg text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-indigo-600 text-white"
                    : "bg-gray-100 text-gray-800"
                }`}>
                  {msg.role === "assistant" ? (
                    <div dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }} />
                  ) : (
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  )}
                </div>
              </div>
            ))}
            {messages.filter((m) => m.role !== "system").length === 0 && (
              <div className="text-center text-gray-400 mt-16">
                <svg className="w-10 h-10 mx-auto mb-2 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
                <p className="text-xs">点击"加载全文到 AI"后讨论</p>
                <p className="text-[10px] mt-0.5">或直接输入问题讨论</p>
              </div>
            )}
            {sending && (
              <div className="flex justify-start">
                <div className="bg-gray-100 px-3 py-2 rounded-lg text-xs text-gray-500 flex items-center gap-2">
                  <div className="w-3 h-3 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
                  思考中...
                </div>
              </div>
            )}
            <div ref={messagesEnd} />
          </div>

          {/* Input */}
          <div className="p-3 border-t border-gray-200 bg-white">
            <div className="flex gap-1.5">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                placeholder="输入问题..."
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                disabled={sending}
              />
              <button
                onClick={sendMessage}
                disabled={sending || !input.trim()}
                className="px-3 py-2 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-colors"
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
