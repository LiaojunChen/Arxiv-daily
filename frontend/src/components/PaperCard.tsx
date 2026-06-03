import type { Paper } from "../types";
import { truncateAbstract, categoryColor } from "../utils/arxiv";

interface PaperCardProps {
  paper: Paper;
  onChat: (paper: Paper) => void;
}

export default function PaperCard({ paper, onChat }: PaperCardProps) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5 hover:shadow-md transition-shadow">
      {/* Categories */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {paper.categories.slice(0, 3).map((cat) => (
          <span key={cat} className={`text-xs px-2 py-0.5 rounded font-medium ${categoryColor(cat)}`}>
            {cat}
          </span>
        ))}
        {paper.similarity_score !== undefined && paper.similarity_score > 0 && (
          <span className="text-xs px-2 py-0.5 rounded font-medium bg-indigo-100 text-indigo-800">
            匹配度: {(paper.similarity_score * 100).toFixed(0)}%
          </span>
        )}
        {paper.matched_by && (
          <span className="text-xs px-2 py-0.5 rounded font-medium bg-amber-100 text-amber-800">
            {paper.matched_by}
          </span>
        )}
      </div>

      {/* Title */}
      <h3 className="text-base font-semibold text-gray-900 mb-2 leading-snug">
        <a
          href={paper.abstract_url}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-indigo-600 transition-colors"
        >
          {paper.title}
        </a>
      </h3>

      {/* Authors */}
      <p className="text-sm text-gray-600 mb-3">
        {paper.authors.slice(0, 5).join(", ")}
        {paper.authors.length > 5 && ` et al. (${paper.authors.length} authors)`}
      </p>

      {/* Abstract */}
      <p className="text-sm text-gray-500 leading-relaxed mb-4">
        {truncateAbstract(paper.abstract)}
      </p>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <a
          href={paper.pdf_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-sm px-4 py-2 bg-gray-900 text-white rounded-lg hover:bg-gray-800 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
          </svg>
          PDF
        </a>
        <button
          onClick={() => onChat(paper)}
          className="inline-flex items-center gap-1.5 text-sm px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
          讨论
        </button>
      </div>
    </div>
  );
}
