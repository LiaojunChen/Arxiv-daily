import type { AppSettings } from "../types";

const SETTINGS_KEY = "arxiv-daily-settings";
export const SETTINGS_UPDATED_EVENT = "arxiv-daily-settings-updated";

const defaultSettings: AppSettings = {
  followed_authors: [],
  followed_institutions: [],
  ai_api_base: "https://api.openai.com/v1",
  ai_api_key: "",
  ai_model: "gpt-4o",
  feedback_access_code: "",
};

export function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { ...defaultSettings };
    const parsed = JSON.parse(raw);
    return { ...defaultSettings, ...parsed };
  } catch {
    return { ...defaultSettings };
  }
}

export function saveSettings(settings: AppSettings): void {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  window.dispatchEvent(new Event(SETTINGS_UPDATED_EVENT));
}
