import { useState, useEffect, useMemo } from "react";
import type { AppSettings, PapersData, Paper } from "../types";
import { getUniqueAffiliations } from "../utils/affiliations";
import { loadSettings, SETTINGS_UPDATED_EVENT } from "../utils/storage";
import { mergeFollowedPapers } from "../utils/subscriptions";

export function usePapers() {
  const [data, setData] = useState<PapersData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [settings, setSettings] = useState<AppSettings>(loadSettings);

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}papers.json?ts=${Date.now()}`, {
      cache: "no-store",
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((json: PapersData) => {
        setData(json);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load papers:", err);
        setError("无法加载论文数据。请确保 papers.json 已部署。");
        setLoading(false);
      });
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
        [...(data?.similar_papers ?? []), ...(data?.hf_papers ?? [])],
        settings,
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
