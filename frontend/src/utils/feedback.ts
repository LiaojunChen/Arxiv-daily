import type { Paper } from "../types";
import { loadSettings } from "./storage";

const CLIENT_ID_KEY = "arxiv-daily-feedback-client-id";

export type FeedbackAction = "like" | "interested" | "not_interested";

export class FeedbackSubmissionError extends Error {
  public readonly code:
    | "endpoint_missing"
    | "access_code_missing"
    | "unauthorized"
    | "rate_limited"
    | "request_failed";

  constructor(
    message: string,
    code:
      | "endpoint_missing"
      | "access_code_missing"
      | "unauthorized"
      | "rate_limited"
      | "request_failed",
  ) {
    super(message);
    this.name = "FeedbackSubmissionError";
    this.code = code;
  }
}

function feedbackApiUrl(): string {
  return String(import.meta.env.VITE_FEEDBACK_API_URL || "").trim().replace(/\/+$/, "");
}

function feedbackClientId(): string {
  const existing = localStorage.getItem(CLIENT_ID_KEY);
  if (existing) return existing;

  const generated = crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  localStorage.setItem(CLIENT_ID_KEY, generated);
  return generated;
}

function errorForStatus(status: number): FeedbackSubmissionError {
  if (status === 401) {
    return new FeedbackSubmissionError("反馈访问码不正确，请在设置中更新后重试。", "unauthorized");
  }
  if (status === 429) {
    return new FeedbackSubmissionError("提交过于频繁，请稍后再试。", "rate_limited");
  }
  return new FeedbackSubmissionError("反馈服务暂时不可用，请稍后重试。", "request_failed");
}

export async function submitPaperFeedback(
  paper: Paper,
  runId: string,
  action: FeedbackAction,
): Promise<{ duplicate: boolean }> {
  const apiUrl = feedbackApiUrl();
  if (!apiUrl) {
    throw new FeedbackSubmissionError(
      "反馈服务尚未配置。请先按仓库部署说明配置 Cloudflare Worker。",
      "endpoint_missing",
    );
  }

  const accessCode = loadSettings().feedback_access_code.trim();
  if (!accessCode) {
    throw new FeedbackSubmissionError(
      "请先在“设置”中填写反馈访问码。",
      "access_code_missing",
    );
  }

  let response: Response;
  try {
    response = await fetch(`${apiUrl}/v1/feedback`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-feedback-access-code": accessCode,
      },
      body: JSON.stringify({
        paper_id: paper.arxiv_id,
        run_id: runId,
        action,
        client_id: feedbackClientId(),
        paper: {
          title: paper.title,
          keywords: paper.matched_keywords ?? [],
          matched_keywords: paper.matched_keywords ?? [],
        },
      }),
    });
  } catch {
    throw new FeedbackSubmissionError("无法连接反馈服务，请检查网络后重试。", "request_failed");
  }

  if (!response.ok) throw errorForStatus(response.status);

  try {
    const result = (await response.json()) as { duplicate?: unknown };
    return { duplicate: result.duplicate === true };
  } catch {
    return { duplicate: false };
  }
}
