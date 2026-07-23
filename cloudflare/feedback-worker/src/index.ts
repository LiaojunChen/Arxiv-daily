export interface Env {
  DB: D1Database;
  ALLOWED_ORIGINS?: string;
  MAX_EVENTS_PER_HOUR?: string;
  FEEDBACK_ACCESS_CODE: string;
  FEEDBACK_RATE_LIMIT_SALT?: string;
  SYNC_API_TOKEN: string;
}

type FeedbackAction = "interested" | "like" | "not_interested";

interface BrowserFeedbackRequest {
  paper_id?: unknown;
  run_id?: unknown;
  action?: unknown;
  client_id?: unknown;
  paper?: {
    title?: unknown;
    keywords?: unknown;
    matched_keywords?: unknown;
  };
}

interface FeedbackRow {
  id: number;
  paper_id: string;
  run_id: string;
  action: FeedbackAction;
  paper_title: string;
  keywords_json: string;
  matched_keywords_json: string;
  created_at: string;
}

const ACTIONS = new Set<FeedbackAction>(["interested", "like", "not_interested"]);
const JSON_HEADERS = { "content-type": "application/json; charset=utf-8" };

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return handlePreflight(request, env);
    }

    try {
      if (url.pathname === "/v1/health" && request.method === "GET") {
        await env.DB.prepare("SELECT 1 AS ok").first();
        return json({ ok: true });
      }
      if (url.pathname === "/v1/feedback" && request.method === "POST") {
        return submitBrowserFeedback(request, env);
      }
      if (url.pathname === "/v1/internal/feedback" && request.method === "GET") {
        return listPendingFeedback(request, env, url);
      }
      if (url.pathname === "/v1/internal/ack" && request.method === "POST") {
        return acknowledgeFeedback(request, env);
      }
      return json({ error: "not_found" }, 404);
    } catch (error) {
      console.error("Unhandled feedback Worker error", error);
      return json({ error: "internal_error" }, 500, corsHeaders(request, env));
    }
  },
};

async function submitBrowserFeedback(request: Request, env: Env): Promise<Response> {
  const cors = requirePublicOrigin(request, env);
  if (cors instanceof Response) return cors;

  const accessCode = request.headers.get("x-feedback-access-code") || "";
  if (!(await secureEquals(accessCode, env.FEEDBACK_ACCESS_CODE || ""))) {
    return json({ error: "invalid_access_code" }, 401, cors);
  }

  const input = await parseJson<BrowserFeedbackRequest>(request);
  if (!input) return json({ error: "invalid_json" }, 400, cors);

  const event = validateBrowserFeedback(input);
  if (event instanceof Response) return withCors(event, cors);

  const clientHash = await sha256Hex(
    `${env.FEEDBACK_RATE_LIMIT_SALT || env.FEEDBACK_ACCESS_CODE}:${event.clientId}`,
  );
  const maxEvents = parseLimit(env.MAX_EVENTS_PER_HOUR, 20, 1, 100);
  const recent = await env.DB.prepare(
    "SELECT COUNT(*) AS count FROM feedback_events WHERE client_hash = ? AND created_at >= datetime('now', '-1 hour')",
  ).bind(clientHash).first<{ count: number | string }>();
  if (Number(recent?.count || 0) >= maxEvents) {
    return json({ error: "rate_limited" }, 429, cors);
  }

  const eventKey = await sha256Hex(
    `${event.clientId}:${event.runId}:${event.paperId}:${event.action}`,
  );
  const result = await env.DB.prepare(
    `INSERT INTO feedback_events (
      event_key, paper_id, run_id, action, paper_title,
      keywords_json, matched_keywords_json, client_hash
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(event_key) DO NOTHING`,
  ).bind(
    eventKey,
    event.paperId,
    event.runId,
    event.action,
    event.paperTitle,
    JSON.stringify(event.keywords),
    JSON.stringify(event.matchedKeywords),
    clientHash,
  ).run();

  return json(
    { ok: true, duplicate: Number(result.meta.changes || 0) === 0, action: event.action },
    Number(result.meta.changes || 0) === 0 ? 200 : 201,
    cors,
  );
}

async function listPendingFeedback(request: Request, env: Env, url: URL): Promise<Response> {
  if (!(await hasSyncAuthorization(request, env))) {
    return json({ error: "unauthorized" }, 401);
  }

  const limit = parseLimit(url.searchParams.get("limit"), 100, 1, 200);
  const result = await env.DB.prepare(
    `SELECT id, paper_id, run_id, action, paper_title, keywords_json,
            matched_keywords_json, created_at
     FROM feedback_events
     WHERE status = 'pending'
     ORDER BY id ASC
     LIMIT ?`,
  ).bind(limit).all<FeedbackRow>();

  const events = result.results.map((row) => ({
    feedback_id: row.id,
    paper_id: row.paper_id,
    run_id: row.run_id,
    action: row.action,
    created_at: row.created_at,
    source: "cloudflare",
    paper: {
      title: row.paper_title,
      keywords: parseKeywordArray(row.keywords_json),
      matched_keywords: parseKeywordArray(row.matched_keywords_json),
    },
  }));
  return json({ events });
}

async function acknowledgeFeedback(request: Request, env: Env): Promise<Response> {
  if (!(await hasSyncAuthorization(request, env))) {
    return json({ error: "unauthorized" }, 401);
  }
  const body = await parseJson<{ feedback_ids?: unknown }>(request);
  const ids = Array.isArray(body?.feedback_ids)
    ? body.feedback_ids.filter((id): id is number => Number.isInteger(id) && id > 0).slice(0, 200)
    : [];
  if (!ids.length) return json({ error: "invalid_feedback_ids" }, 400);

  const placeholders = ids.map(() => "?").join(", ");
  const result = await env.DB.prepare(
    `UPDATE feedback_events
     SET status = 'processed', processed_at = CURRENT_TIMESTAMP
     WHERE status = 'pending' AND id IN (${placeholders})`,
  ).bind(...ids).run();
  return json({ ok: true, acknowledged: Number(result.meta.changes || 0) });
}

function validateBrowserFeedback(input: BrowserFeedbackRequest):
  | {
      paperId: string;
      runId: string;
      paperTitle: string;
      action: FeedbackAction;
      clientId: string;
      keywords: string[];
      matchedKeywords: string[];
    }
  | Response {
  const paperId = cleanString(input.paper_id, 160);
  const runId = cleanString(input.run_id, 160);
  const paperTitle = cleanString(input.paper?.title, 500);
  const action = input.action;
  const clientId = cleanString(input.client_id, 160);
  if (!paperId || !runId || !paperTitle || !clientId || !ACTIONS.has(action as FeedbackAction)) {
    return json({ error: "invalid_feedback" }, 400);
  }
  return {
    paperId,
    runId,
    paperTitle,
    action: action as FeedbackAction,
    clientId,
    keywords: cleanKeywords(input.paper?.keywords),
    matchedKeywords: cleanKeywords(input.paper?.matched_keywords),
  };
}

function cleanString(value: unknown, maxLength: number): string {
  if (typeof value !== "string") return "";
  return value.trim().replace(/\s+/g, " ").slice(0, maxLength);
}

function cleanKeywords(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const keywords: string[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    const keyword = cleanString(item, 100).toLowerCase();
    if (keyword && !seen.has(keyword)) {
      keywords.push(keyword);
      seen.add(keyword);
    }
    if (keywords.length >= 12) break;
  }
  return keywords;
}

function parseKeywordArray(value: string): string[] {
  try {
    return cleanKeywords(JSON.parse(value));
  } catch {
    return [];
  }
}

function parseLimit(value: string | null | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number.parseInt(value || "", 10);
  return Number.isFinite(parsed) ? Math.min(max, Math.max(min, parsed)) : fallback;
}

async function parseJson<T>(request: Request): Promise<T | null> {
  try {
    return (await request.json()) as T;
  } catch {
    return null;
  }
}

async function hasSyncAuthorization(request: Request, env: Env): Promise<boolean> {
  const authorization = request.headers.get("authorization") || "";
  return secureEquals(authorization, `Bearer ${env.SYNC_API_TOKEN || ""}`);
}

function allowedOrigins(env: Env): Set<string> {
  return new Set(
    (env.ALLOWED_ORIGINS || "")
      .split(",")
      .map((origin) => origin.trim())
      .filter(Boolean),
  );
}

function corsHeaders(request: Request, env: Env): HeadersInit {
  const origin = request.headers.get("origin") || "";
  if (!origin || !allowedOrigins(env).has(origin)) return {};
  return {
    "access-control-allow-origin": origin,
    "access-control-allow-headers": "content-type, x-feedback-access-code",
    "access-control-allow-methods": "POST, OPTIONS",
    "access-control-max-age": "86400",
    "vary": "Origin",
  };
}

function requirePublicOrigin(request: Request, env: Env): HeadersInit | Response {
  const origin = request.headers.get("origin") || "";
  if (!origin || !allowedOrigins(env).has(origin)) {
    return json({ error: "origin_not_allowed" }, 403);
  }
  return corsHeaders(request, env);
}

function handlePreflight(request: Request, env: Env): Response {
  const cors = requirePublicOrigin(request, env);
  return cors instanceof Response ? cors : new Response(null, { status: 204, headers: cors });
}

function json(body: unknown, status = 200, headers: HeadersInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...JSON_HEADERS, ...headers },
  });
}

function withCors(response: Response, headers: HeadersInit): Response {
  const nextHeaders = new Headers(response.headers);
  new Headers(headers).forEach((value, key) => nextHeaders.set(key, value));
  return new Response(response.body, { status: response.status, headers: nextHeaders });
}

async function secureEquals(left: string, right: string): Promise<boolean> {
  if (!left || !right) return false;
  const [leftDigest, rightDigest] = await Promise.all([sha256Bytes(left), sha256Bytes(right)]);
  let difference = 0;
  for (let index = 0; index < leftDigest.length; index += 1) {
    difference |= leftDigest[index] ^ rightDigest[index];
  }
  return difference === 0;
}

async function sha256Hex(value: string): Promise<string> {
  const bytes = await sha256Bytes(value);
  return Array.from(bytes, (item) => item.toString(16).padStart(2, "0")).join("");
}

async function sha256Bytes(value: string): Promise<Uint8Array> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return new Uint8Array(digest);
}
