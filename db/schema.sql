-- RadiantBrain operational store — PostgreSQL schema (docs/06-operational-data.md).
--
-- This is the Phase 5 migration target. Until a Postgres instance is wired in,
-- the radiant CLI keeps the same operational data in per-store SQLite files
-- under build/ (tickets.db, answers.db, jobs.db) that mirror these tables.
-- Operational data links to the Markdown knowledge base by page SLUG — the
-- slug is the foreign key that crosses the Git/SQL boundary (see
-- `radiant doctor` for the integrity check on those references).

-- ============ Fleet & accounts ============

CREATE TABLE IF NOT EXISTS distributors (
  id            SERIAL PRIMARY KEY,
  name          TEXT NOT NULL,
  kb_slug       TEXT,                    -- knowledge/distributors/<slug>.md
  regions       TEXT[]
);

CREATE TABLE IF NOT EXISTS customers (
  id            SERIAL PRIMARY KEY,
  name          TEXT NOT NULL,
  kb_slug       TEXT,                    -- knowledge/customers/<slug>.md, nullable
  distributor_id INT REFERENCES distributors(id),
  region        TEXT,
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS robots (
  serial        TEXT PRIMARY KEY,        -- physical unit
  model_slug    TEXT NOT NULL,           -- knowledge/robots/<slug>.md
  customer_id   INT REFERENCES customers(id),
  firmware_version TEXT,                 -- current, e.g. 'v2.7'
  commissioned_at DATE,
  status        TEXT DEFAULT 'active'    -- active | in_repair | retired
);

-- ============ Tickets ============

CREATE TABLE IF NOT EXISTS tickets (
  id            SERIAL PRIMARY KEY,
  external_ref  TEXT,
  customer_id   INT REFERENCES customers(id),
  robot_serial  TEXT REFERENCES robots(serial),
  channel       TEXT,                    -- email | whatsapp | phone | portal
  status        TEXT NOT NULL DEFAULT 'open',   -- open | pending | closed
  error_slugs   TEXT[] DEFAULT '{}',     -- knowledge/error_codes slugs observed
  summary       TEXT,
  resolution    TEXT,                    -- filled at close; input to radiant learn
  kb_page_slug  TEXT,                    -- set iff a knowledge/tickets/ page exists
  learn_status  TEXT DEFAULT 'pending',  -- pending | applied | pr_open | merged | skipped | lint_failed
  opened_at     TIMESTAMPTZ DEFAULT now(),
  closed_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ticket_messages (
  id            SERIAL PRIMARY KEY,
  ticket_id     INT REFERENCES tickets(id),
  author        TEXT,                    -- customer | support | agent:<name>
  sent_at       TIMESTAMPTZ,
  body          TEXT
);

-- ============ Telemetry ============

CREATE TABLE IF NOT EXISTS telemetry_events (
  id            BIGSERIAL PRIMARY KEY,
  robot_serial  TEXT REFERENCES robots(serial),
  occurred_at   TIMESTAMPTZ NOT NULL,
  event_type    TEXT NOT NULL,           -- error | warning | metric
  error_slug    TEXT,                    -- when event_type = 'error'
  payload       JSONB
);
CREATE INDEX IF NOT EXISTS telemetry_robot_time ON telemetry_events (robot_serial, occurred_at);
CREATE INDEX IF NOT EXISTS telemetry_error ON telemetry_events (error_slug) WHERE error_slug IS NOT NULL;

-- ============ AI system tables ============

CREATE TABLE IF NOT EXISTS agent_answers (
  id            SERIAL PRIMARY KEY,
  asked_at      TIMESTAMPTZ DEFAULT now(),
  agent         TEXT NOT NULL,
  channel       TEXT,
  question      TEXT NOT NULL,
  answer_md     TEXT,
  citations     JSONB,                   -- [{page, section, status}]
  confidence    TEXT,                    -- high | medium | low | none
  feedback      SMALLINT,                -- 1 / -1 / NULL
  latency_ms    INT
);

CREATE TABLE IF NOT EXISTS ingest_jobs (
  id            SERIAL PRIMARY KEY,
  source_uri    TEXT NOT NULL,
  content_hash  TEXT UNIQUE,             -- idempotency key
  type_hint     TEXT,
  status        TEXT DEFAULT 'running',
  branch        TEXT,
  pages_touched TEXT[],
  created_at    TIMESTAMPTZ DEFAULT now(),
  finished_at   TIMESTAMPTZ,
  error         TEXT
);

-- ============ Read-only views for agents & dashboard ============

-- "Has another distributor solved this before?"
CREATE OR REPLACE VIEW v_error_resolutions AS
SELECT unnest(t.error_slugs) AS error_slug, d.name AS distributor,
       t.resolution, t.closed_at
FROM tickets t
LEFT JOIN customers c ON c.id = t.customer_id
LEFT JOIN distributors d ON d.id = c.distributor_id
WHERE t.status = 'closed' AND t.resolution IS NOT NULL;

-- "What's trending in the field this month?"
CREATE OR REPLACE VIEW v_error_frequency AS
SELECT error_slug, date_trunc('week', occurred_at) AS week, count(*) AS events
FROM telemetry_events
WHERE error_slug IS NOT NULL
GROUP BY 1, 2;

-- Curator backlog: errors happening in the field with thin documentation.
CREATE OR REPLACE VIEW v_kb_gaps AS
SELECT error_slug, count(*) AS events_30d
FROM telemetry_events
WHERE occurred_at > now() - interval '30 days' AND error_slug IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC;
