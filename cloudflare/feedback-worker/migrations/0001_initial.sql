CREATE TABLE IF NOT EXISTS feedback_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_key TEXT NOT NULL UNIQUE,
  paper_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('interested', 'like', 'not_interested')),
  paper_title TEXT NOT NULL,
  keywords_json TEXT NOT NULL DEFAULT '[]',
  matched_keywords_json TEXT NOT NULL DEFAULT '[]',
  source TEXT NOT NULL DEFAULT 'web',
  client_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processed')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_feedback_events_pending
  ON feedback_events(status, id);

CREATE INDEX IF NOT EXISTS idx_feedback_events_rate_limit
  ON feedback_events(client_hash, created_at);
