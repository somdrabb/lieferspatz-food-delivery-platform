BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS auditlog (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id INTEGER,
    event TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    ip TEXT
);

CREATE INDEX IF NOT EXISTS idx_auditlog_actor ON auditlog(actor_type, actor_id);
CREATE INDEX IF NOT EXISTS idx_auditlog_event ON auditlog(event);

COMMIT;
