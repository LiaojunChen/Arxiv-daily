import { useMemo, useState } from "react";
import type { Paper } from "../types";
import {
  truncateAbstract,
  categoryColor,
  formatSimilarityPercentage,
} from "../utils/arxiv";
import { getUniqueAffiliations } from "../utils/affiliations";
import {
  submitPaperFeedback,
  type FeedbackAction,
} from "../utils/feedback";

interface PaperCardProps {
  paper: Paper;
  onChat: (paper: Paper) => void;
  feedbackRunId: string;
}

const feedbackLabels: Record<FeedbackAction, string> = {
  like: "喜欢",
  interested: "感兴趣",
  not_interested: "少推荐此类",
};

export default function PaperCard({ paper, onChat, feedbackRunId }: PaperCardProps) {
  const [submittingAction, setSubmittingAction] = useState<FeedbackAction | null>(null);
  const [submittedAction, setSubmittedAction] = useState<FeedbackAction | null>(null);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const uniqueAffiliations = useMemo(
    () => getUniqueAffiliations(paper.affiliations),
    [paper.affiliations],
  );

  const submitFeedback = async (action: FeedbackAction) => {
    setSubmittingAction(action);
    setFeedbackError(null);
    try {
      await submitPaperFeedback(paper, feedbackRunId, action);
      setSubmittedAction(action);
    } catch (error) {
      setFeedbackError(error instanceof Error ? error.message : "反馈提交失败，请稍后重试。");
    } finally {
      setSubmittingAction(null);
    }
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5 hover:shadow-md transition-shadow">
      <div className="flex flex-wrap gap-1.5 mb-3">
        {paper.categories.slice(0, 3).map((category) => (
          <span key={category} className={`text-xs px-2 py-0.5 rounded font-medium ${categoryColor(category)}`}>
            {category}
          </span>
        ))}
        {paper.similarity_score !== undefined && paper.similarity_score > 0 && (
          <span className="text-xs px-2 py-0.5 rounded font-medium bg-indigo-100 text-indigo-800">
            匹配度 {formatSimilarityPercentage(paper.similarity_score)}
          </span>
        )}
        {paper.matched_by && (
          <span className="text-xs px-2 py-0.5 rounded font-medium bg-amber-100 text-amber-800">
            {paper.matched_by}
          </span>
        )}
        {paper.source === "interest_profile" && (
          <span className="text-xs px-2 py-0.5 rounded font-medium bg-emerald-100 text-emerald-800">
            Interest profile
          </span>
        )}
        {paper.source === "huggingface" && (
          <span className="text-xs px-2 py-0.5 rounded font-medium bg-yellow-100 text-yellow-800">HF</span>
        )}
        {(paper.hf_upvotes ?? 0) > 0 && (
          <span className="text-xs px-2 py-0.5 rounded font-medium bg-yellow-100 text-yellow-800">
            {paper.hf_upvotes} upvotes
          </span>
        )}
      </div>

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

      <p className="text-sm text-gray-600 mb-1.5">
        {paper.authors.slice(0, 5).join(", ")}
        {paper.authors.length > 5 && ` et al. (${paper.authors.length} authors)`}
      </p>

      {uniqueAffiliations.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 mb-3">
          <svg className="w-3.5 h-3.5 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
          </svg>
          <span className="text-xs text-gray-400">{uniqueAffiliations.join(" · ")}</span>
        </div>
      )}

      <p className="text-sm text-gray-500 leading-relaxed mb-4">{truncateAbstract(paper.abstract)}</p>

      {paper.recommendation_reason && (
        <div className="mb-4 rounded-md border border-emerald-100 bg-emerald-50 px-3 py-2 text-xs leading-relaxed text-emerald-900">
          <span className="font-semibold">Why recommended: </span>
          {paper.recommendation_reason}
          {(paper.matched_keywords?.length ?? 0) > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {paper.matched_keywords?.slice(0, 4).map((keyword) => (
                <span key={keyword} className="rounded bg-white px-1.5 py-0.5 text-emerald-800">
                  {keyword}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
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
          type="button"
          onClick={() => onChat(paper)}
          className="inline-flex items-center gap-1.5 text-sm px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
          讨论
        </button>
        <div className="flex items-center gap-1 border-l border-gray-200 pl-3">
          {(["like", "interested", "not_interested"] as FeedbackAction[]).map((action) => (
            <button
              key={action}
              type="button"
              disabled={submittingAction !== null}
              onClick={() => void submitFeedback(action)}
              title={feedbackLabels[action]}
              className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-2 text-xs transition-colors cursor-pointer disabled:cursor-wait disabled:opacity-60 ${
                submittedAction === action
                  ? "border-emerald-300 bg-emerald-50 text-emerald-700"
                  : action === "not_interested"
                    ? "border-gray-300 text-gray-600 hover:border-rose-300 hover:bg-rose-50 hover:text-rose-700"
                    : "border-gray-300 text-gray-600 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700"
              }`}
            >
              {submittingAction === action ? "提交中…" : feedbackLabels[action]}
            </button>
          ))}
        </div>
      </div>
      {submittedAction && (
        <p className="mt-2 text-xs text-emerald-700">已记录：{feedbackLabels[submittedAction]}</p>
      )}
      {feedbackError && <p className="mt-2 text-xs text-rose-700">{feedbackError}</p>}
    </div>
  );
}
