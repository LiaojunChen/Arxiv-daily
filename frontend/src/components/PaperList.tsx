import type { Paper } from "../types";
import PaperCard from "./PaperCard";

interface PaperListProps {
  papers: Paper[];
  onChat: (paper: Paper) => void;
  emptyMessage: string;
  feedbackRunId: string;
}

export default function PaperList({ papers, onChat, emptyMessage, feedbackRunId }: PaperListProps) {
  if (papers.length === 0) {
    return (
      <div className="text-center py-16 text-gray-400">
        <svg className="w-16 h-16 mx-auto mb-4 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        <p>{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-2">
      {papers.map((paper) => (
        <PaperCard
          key={paper.arxiv_id}
          paper={paper}
          onChat={onChat}
          feedbackRunId={feedbackRunId}
        />
      ))}
    </div>
  );
}
