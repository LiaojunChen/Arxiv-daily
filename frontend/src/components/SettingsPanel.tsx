import { useState } from "react";
import type { AppSettings } from "../types";
import { loadSettings, saveSettings } from "../utils/storage";

export default function SettingsPanel() {
  const [settings, setSettings] = useState<AppSettings>(loadSettings());
  const [saved, setSaved] = useState(false);

  const update = (patch: Partial<AppSettings>) => {
    setSettings((prev) => ({ ...prev, ...patch }));
    setSaved(false);
  };

  const handleSave = () => {
    saveSettings(settings);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const addAuthor = () => {
    const name = prompt("输入要关注的作者名:");
    if (name?.trim()) {
      update({ followed_authors: [...settings.followed_authors, name.trim()] });
    }
  };

  const removeAuthor = (idx: number) => {
    const next = settings.followed_authors.filter((_, i) => i !== idx);
    update({ followed_authors: next });
  };

  const addInstitution = () => {
    const name = prompt("输入要关注的机构名:");
    if (name?.trim()) {
      update({ followed_institutions: [...settings.followed_institutions, name.trim()] });
    }
  };

  const removeInstitution = (idx: number) => {
    const next = settings.followed_institutions.filter((_, i) => i !== idx);
    update({ followed_institutions: next });
  };

  return (
    <div className="max-w-2xl mx-auto space-y-8">
      {/* Feedback settings */}
      <section className="bg-white border border-gray-200 rounded-lg p-6">
        <h3 className="text-base font-semibold text-gray-900 mb-2">论文反馈</h3>
        <p className="text-xs text-gray-400 mb-4">
          反馈访问码仅保存在当前浏览器，用于向 Cloudflare 反馈服务验证提交身份；它不会被写入 GitHub Pages 页面或仓库。
        </p>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">反馈访问码</label>
          <input
            type="password"
            value={settings.feedback_access_code}
            onChange={(e) => update({ feedback_access_code: e.target.value })}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            placeholder="在 Cloudflare Worker 中设置的 FEEDBACK_ACCESS_CODE"
            autoComplete="off"
          />
        </div>
      </section>

      {/* Followed Authors */}
      <section className="bg-white border border-gray-200 rounded-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-900">关注作者</h3>
          <button
            onClick={addAuthor}
            className="text-sm px-3 py-1.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 cursor-pointer transition-colors"
          >
            + 添加
          </button>
        </div>
        {settings.followed_authors.length === 0 ? (
          <p className="text-sm text-gray-400">尚未添加关注作者</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {settings.followed_authors.map((a, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 rounded-lg text-sm text-gray-700"
              >
                {a}
                <button
                  onClick={() => removeAuthor(i)}
                  className="text-gray-400 hover:text-red-500 cursor-pointer"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </span>
            ))}
          </div>
        )}
      </section>

      {/* Followed Institutions */}
      <section className="bg-white border border-gray-200 rounded-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-900">关注机构</h3>
          <button
            onClick={addInstitution}
            className="text-sm px-3 py-1.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 cursor-pointer transition-colors"
          >
            + 添加
          </button>
        </div>
        {settings.followed_institutions.length === 0 ? (
          <p className="text-sm text-gray-400">尚未添加关注机构</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {settings.followed_institutions.map((inst, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 rounded-lg text-sm text-gray-700"
              >
                {inst}
                <button
                  onClick={() => removeInstitution(i)}
                  className="text-gray-400 hover:text-red-500 cursor-pointer"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </span>
            ))}
          </div>
        )}
      </section>

      {/* AI API Settings */}
      <section className="bg-white border border-gray-200 rounded-lg p-6">
        <h3 className="text-base font-semibold text-gray-900 mb-4">AI API 配置</h3>
        <p className="text-xs text-gray-400 mb-4">
          API Key 仅存储在你浏览器的本地存储中，不会被上传到服务器。
        </p>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">API Base URL</label>
            <input
              type="text"
              value={settings.ai_api_base}
              onChange={(e) => update({ ai_api_base: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="https://api.openai.com/v1"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">API Key</label>
            <input
              type="password"
              value={settings.ai_api_key}
              onChange={(e) => update({ ai_api_key: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="sk-..."
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Model</label>
            <input
              type="text"
              value={settings.ai_model}
              onChange={(e) => update({ ai_model: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="gpt-4o"
            />
          </div>
        </div>
      </section>

      {/* Save Button */}
      <div className="flex items-center gap-4">
        <button
          onClick={handleSave}
          className="px-6 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 cursor-pointer transition-colors font-medium"
        >
          保存设置
        </button>
        {saved && <span className="text-sm text-green-600">已保存</span>}
      </div>

      <p className="text-xs text-gray-400 pb-8">
        提示：关注的作者和机构列表需要同步到仓库的 data/config.json 文件中，才能在每日自动拉取时生效。
      </p>
    </div>
  );
}
