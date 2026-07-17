export function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export function truncateAbstract(text: string, maxLen = 300): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + "...";
}

/** Backend reranker scores use a 0-10 scale. */
export function formatSimilarityPercentage(score: number): string {
  const clamped = Math.min(10, Math.max(0, score));
  return `${Math.round(clamped * 10)}%`;
}

export function categoryColor(cat: string): string {
  const colors: Record<string, string> = {
    "cs.CV": "bg-blue-100 text-blue-800",
    "cs.LG": "bg-green-100 text-green-800",
    "cs.AI": "bg-purple-100 text-purple-800",
    "cs.CL": "bg-orange-100 text-orange-800",
    "cs.RO": "bg-red-100 text-red-800",
    "cs.IR": "bg-teal-100 text-teal-800",
    "stat.ML": "bg-indigo-100 text-indigo-800",
  };
  return colors[cat] || "bg-gray-100 text-gray-800";
}
