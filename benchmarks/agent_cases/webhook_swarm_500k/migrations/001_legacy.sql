PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER,
    endpoint_key TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_deliveries_event_id
    ON deliveries(event_id);
