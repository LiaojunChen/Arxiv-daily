ALTER TABLE feedback_events ADD COLUMN action_v2 TEXT;
ALTER TABLE feedback_events ADD COLUMN abstract_text TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS recommendation_preferences (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  preferences_json TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
