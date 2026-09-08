import { useState, useEffect, useMemo } from "react";
import type { AppSettings, PapersData, Paper } from "../types";
import { getUniqueAffiliations } from "../utils/affiliations";
import { hasSavedSettings, loadSettings, SETTINGS_UPDATED_EVENT } from "../utils/storage";
import { mergeFollowedPapers } from "../utils/subscriptions";

export function usePapers() {
  const [data, setData] = useState<PapersData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [settings, setSettings] = useState<AppSettings>(loadSettings);

  useEffect(() => {
    let disposed = false;
    let hasSnapshot = false;
    let request: AbortController | null = null;
    const refresh = async () => {
      if (request || disposed) return;
      request = new AbortController();
      const timeout = window.setTimeout(() => request?.abort(), 20_000);
      try {
        const res = await fetch(`${import.meta.env.BASE_URL}papers.json`, {
          // Revalidate with ETag instead of downloading the whole candidate pool
          // under a different timestamp URL on every poll.
          cache: "no-cache",
          signal: request.signal,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json: PapersData = await res.json();
        if (disposed) return;
        hasSnapshot = true;
        setData((current) => current?.run_id === json.run_id && current?.updated_at === json.updated_at ? current : json);
        setError(null);
      } catch (err) {
        if (disposed) return;
        console.error("Failed to load papers:", err);
        // A temporary refresh failure must not hide already loaded papers.
        if (!hasSnapshot) setError("无法加载论文数据。请确保 papers.json 已部署。");
      } finally {
        window.clearTimeout(timeout);
        request = null;
        if (!disposed) setLoading(false);
      }
    };
    const refreshVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    void refresh();
    const interval = window.setInterval(refreshVisible, 60_000);
    document.addEventListener("visibilitychange", refreshVisible);
    window.addEventListener("focus", refreshVisible);
    return () => {
      disposed = true;
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refreshVisible);
      window.removeEventListener("focus", refreshVisible);
      request?.abort();
    };
  }, []);

  useEffect(() => {
    const refreshSettings = () => setSettings(loadSettings());
    window.addEventListener(SETTINGS_UPDATED_EVENT, refreshSettings);
    window.addEventListener("storage", refreshSettings);
    return () => {
      window.removeEventListener(SETTINGS_UPDATED_EVENT, refreshSettings);
      window.removeEventListener("storage", refreshSettings);
    };
  }, []);

  const followedPapers = useMemo(
    () =>
      mergeFollowedPapers(
        data?.followed_papers ?? [],
        data?.candidate_papers ?? [...(data?.similar_papers ?? []), ...(data?.hf_papers ?? [])],
        !hasSavedSettings() && data?.subscriptions ? data.subscriptions : settings,
      ),
    [data, settings],
  );

  const { filteredSimilar, filteredFollowed, filteredHF } = useMemo(() => {
    const filterPapers = (papers: Paper[]) => {
      if (!search.trim()) return papers;
      const q = search.toLowerCase();
      return papers.filter(
        (p) =>
          p.title.toLowerCase().includes(q) ||
          p.authors.some((a) => a.toLowerCase().includes(q)) ||
          getUniqueAffiliations(p.affiliations).some((affiliation) =>
            affiliation.toLowerCase().includes(q)
          ) ||
          p.abstract.toLowerCase().includes(q) ||
          p.categories.some((c) => c.toLowerCase().includes(q))
      );
    };

    return {
      filteredSimilar: filterPapers(data?.similar_papers ?? []),
      filteredFollowed: filterPapers(followedPapers),
      filteredHF: filterPapers(data?.hf_papers ?? []),
    };
  }, [data, followedPapers, search]);

  return {
    data,
    loading,
    error,
    search,
    setSearch,
    filteredSimilar,
    filteredFollowed,
    filteredHF,
    followedPapers,
  };
}
