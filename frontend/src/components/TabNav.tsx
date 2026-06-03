interface TabNavProps {
  activeTab: "similar" | "followed" | "hf" | "settings";
  onTabChange: (tab: "similar" | "followed" | "hf" | "settings") => void;
  similarCount: number;
  followedCount: number;
  hfCount: number;
}

export default function TabNav({ activeTab, onTabChange, similarCount, followedCount, hfCount }: TabNavProps) {
  const tabs = [
    { key: "similar" as const, label: "Zotero 推荐", count: similarCount },
    { key: "hf" as const, label: "HF 热门", count: hfCount },
    { key: "followed" as const, label: "关注追踪", count: followedCount },
    { key: "settings" as const, label: "设置", count: null },
  ];

  return (
    <div className="flex border-b border-gray-200 bg-white sticky top-0 z-10">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onTabChange(tab.key)}
          className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors cursor-pointer ${
            activeTab === tab.key
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
          }`}
        >
          {tab.label}
          {tab.count !== null && (
            <span className="ml-2 text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
              {tab.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
