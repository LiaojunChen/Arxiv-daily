import { useState, useEffect, useMemo } from "react";
import type { PapersData, Paper } from "../types";

export function usePapers() {
  const [data, setData] = useState<PapersData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    fetch("/Arxiv-daily/papers.json")
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

  const filterPapers = (papers: Paper[]) => {
    if (!search.trim()) return papers;
    const q = search.toLowerCase();
    return papers.filter(
      (p) =>
        p.title.toLowerCase().includes(q) ||
        p.authors.some((a) => a.toLowerCase().includes(q)) ||
        p.abstract.toLowerCase().includes(q) ||
        p.categories.some((c) => c.toLowerCase().includes(q))
    );
  };

  const filteredSimilar = useMemo(
    () => filterPapers(data?.similar_papers ?? []),
    [data, search]
  );
  const filteredFollowed = useMemo(
    () => filterPapers(data?.followed_papers ?? []),
    [data, search]
  );
  const filteredHF = useMemo(
    () => filterPapers(data?.hf_papers ?? []),
    [data, search]
  );

  return {
    data,
    loading,
    error,
    search,
    setSearch,
    filteredSimilar,
    filteredFollowed,
    filteredHF,
  };
}
