import { useState, useEffect, useMemo } from "react";
import type { PapersData, Paper } from "../types";
import { getUniqueAffiliations } from "../utils/affiliations";

export function usePapers() {
  const [data, setData] = useState<PapersData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

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
      filteredFollowed: filterPapers(data?.followed_papers ?? []),
      filteredHF: filterPapers(data?.hf_papers ?? []),
    };
  }, [data, search]);

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
