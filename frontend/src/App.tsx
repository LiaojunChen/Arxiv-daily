import { useState } from "react";
import type { Paper } from "./types";
import { usePapers } from "./hooks/usePapers";
import TabNav from "./components/TabNav";
import PaperList from "./components/PaperList";
import ChatPanel from "./components/ChatPanel";
import SettingsPanel from "./components/SettingsPanel";

export default function App() {
  const [activeTab, setActiveTab] = useState<"similar" | "followed" | "hf" | "settings">("similar");
  const [chatPaper, setChatPaper] = useState<Paper | null>(null);
  const { data, loading, error, search, setSearch, filteredSimilar, filteredFollowed, filteredHF } = usePapers();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="w-10 h-10 border-4 border-indigo-600 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-500">加载论文数据中...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center max-w-md">
          <h1 className="text-xl font-bold text-gray-900 mb-2">ArXiv Daily</h1>
          <p className="text-gray-500 mb-4">{error}</p>
          <p className="text-sm text-gray-400">
            请确认已配置 GitHub Secrets 并运行了 GitHub Actions workflow。
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">ArXiv Daily</h1>
            {data && (
              <p className="text-xs text-gray-400 mt-0.5">
                更新于 {data.updated_at}
              </p>
            )}
          </div>
          {/* Search */}
          <div className="relative">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索论文..."
              className="pl-9 pr-4 py-2 border border-gray-300 rounded-lg text-sm w-64 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
            <svg
              className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
          </div>
        </div>
      </header>

      {/* Tab Navigation */}
      <div className="max-w-6xl mx-auto">
        <TabNav
          activeTab={activeTab}
          onTabChange={setActiveTab}
          similarCount={data?.similar_papers.length ?? 0}
          followedCount={data?.followed_papers.length ?? 0}
          hfCount={data?.hf_papers.length ?? 0}
        />
      </div>

      {/* Content */}
      <main className="max-w-6xl mx-auto px-4 py-6">
        {activeTab === "similar" && (
          <PaperList
            papers={filteredSimilar}
            onChat={setChatPaper}
            emptyMessage="暂无相似论文推荐。请确保已配置 Zotero API 密钥。"
          />
        )}
        {activeTab === "hf" && (
          <PaperList
            papers={filteredHF}
            onChat={setChatPaper}
            emptyMessage="暂无 HuggingFace 热门论文数据。"
          />
        )}
        {activeTab === "followed" && (
          <PaperList
            papers={filteredFollowed}
            onChat={setChatPaper}
            emptyMessage="暂无关注的作者/机构论文。请在设置中添加关注列表。"
          />
        )}
        {activeTab === "settings" && <SettingsPanel />}
      </main>

      {/* AI Chat Panel */}
      {chatPaper && (
        <ChatPanel paper={chatPaper} onClose={() => setChatPaper(null)} />
      )}
    </div>
  );
}
