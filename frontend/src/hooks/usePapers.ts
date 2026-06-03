import { useState, useEffect, useMemo } from "react";
import type { PapersData } from "../types";

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

  const filteredSimilar = useMemo(() => {
    if (!data) return [];
    if (!search.trim()) return data.similar_papers;
    const q = search.toLowerCase();
    return data.similar_papers.filter(
      (p) =>
        p.title.toLowerCase().includes(q) ||
        p.authors.some((a) => a.toLowerCase().includes(q)) ||
        p.abstract.toLowerCase().includes(q) ||
        p.categories.some((c) => c.toLowerCase().includes(q))
    );
  }, [data, search]);

  const filteredFollowed = useMemo(() => {
    if (!data) return [];
    if (!search.trim()) return data.followed_papers;
    const q = search.toLowerCase();
    return data.followed_papers.filter(
      (p) =>
        p.title.toLowerCase().includes(q) ||
        p.authors.some((a) => a.toLowerCase().includes(q)) ||
        p.abstract.toLowerCase().includes(q)
    );
  }, [data, search]);

  return {
    data,
    loading,
    error,
    search,
    setSearch,
    filteredSimilar,
    filteredFollowed,
  };
}
