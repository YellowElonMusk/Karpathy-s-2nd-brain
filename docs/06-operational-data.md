# 06 — Operational data (PostgreSQL)

Operational data is everything with per-unit identity or high churn: individual robots in the field, ticket threads, CRM events, telemetry, agent answer logs. It lives in PostgreSQL and **links to the knowledge base by page slug** — never the other way around (pages cite tickets as sources via `ticket:<id>`, but never embed operational records).

> **Implementation status:** the full schema below ships as [`db/schema.sql`](../db/schema.sql), ready to apply to Postgres. Until a live instance is wired in, the `radiant` CLI keeps the same operational data in per-store SQLite files under `build/` (`tickets.db`, `answers.db`, `jobs.db`) that mirror these tables and views, so the toolchain stays portable and testable. `radiant doctor` runs the slug-integrity check; `radiant ops` and `radiant dashboard` read the aggregate views.

The dividing line: **Markdown holds knowledge about kinds of things; PostgreSQL holds facts about individual things and events.** `scrubber50.md` documents the model; the `robots` table knows that serial SN-4411 at Customer A runs v2.7 and threw Error 203 on Tuesday.

## Schema

```sql
-- ============ Fleet & accounts ============

CREATE TABLE customers (
  id            SERIAL PRIMARY KEY,
  name          TEXT NOT NULL,
  kb_slug       TEXT,                    -- knowledge/customers/<slug>.md, nullable
  distributor_id INT REFERENCES distributors(id),
  region        TEXT,
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE distributors (
  id            SERIAL PRIMARY KEY,
  name          TEXT NOT NULL,
  kb_slug       TEXT,
  regions       TEXT[]
);

CREATE TABLE robots (
  serial        TEXT PRIMARY KEY,        -- physical unit
  model_slug    TEXT NOT NULL,           -- knowledge/robots/<slug>.md
  customer_id   INT REFERENCES customers(id),
  firmware_version TEXT,                 -- current, e.g. 'v2.7'
  commissioned_at DATE,
  status        TEXT DEFAULT 'active'    -- active | in_repair | retired
);

-- ============ Tickets ============

CREATE TABLE tickets (
  id            SERIAL PRIMARY KEY,
  external_ref  TEXT,                    -- id in the ticketing system, if any
  customer_id   INT REFERENCES customers(id),
  robot_serial  TEXT REFERENCES robots(serial),
  channel       TEXT,                    -- email | whatsapp | phone | portal
  status        TEXT NOT NULL DEFAULT 'open',   -- open | pending | closed
  error_slugs   TEXT[] DEFAULT '{}',     -- knowledge/error_codes slugs observed
  summary       TEXT,
  resolution    TEXT,                    -- filled at close; input to radiant learn
  kb_page_slug  TEXT,                    -- set iff a knowledge/tickets/ page exists
  learn_status  TEXT DEFAULT 'pending',  -- pending | pr_open | merged | skipped
  opened_at     TIMESTAMPTZ DEFAULT now(),
  closed_at     TIMESTAMPTZ
);

CREATE TABLE ticket_messages (
  id            SERIAL PRIMARY KEY,
  ticket_id     INT REFERENCES tickets(id),
  author        TEXT,                    -- customer | support | agent:<name>
  sent_at       TIMESTAMPTZ,
  body          TEXT
);

-- ============ Telemetry ============

CREATE TABLE telemetry_events (
  id            BIGSERIAL PRIMARY KEY,
  robot_serial  TEXT REFERENCES robots(serial),
  occurred_at   TIMESTAMPTZ NOT NULL,
  event_type    TEXT NOT NULL,           -- error | warning | metric
  error_slug    TEXT,                    -- when event_type = 'error'
  payload       JSONB
);
CREATE INDEX ON telemetry_events (robot_serial, occurred_at);
CREATE INDEX ON telemetry_events (error_slug) WHERE error_slug IS NOT NULL;

-- ============ AI system tables ============

CREATE TABLE agent_answers (
  id            SERIAL PRIMARY KEY,
  asked_at      TIMESTAMPTZ DEFAULT now(),
  agent         TEXT NOT NULL,           -- support | chief-of-staff
  channel       TEXT,                    -- cli | dashboard | ticket:<id>
  question      TEXT NOT NULL,
  answer_md     TEXT,
  citations     JSONB,                   -- [{page, section, status}]
  confidence    TEXT,                    -- high | medium | low | none
  feedback      SMALLINT,                -- 1 / -1 / NULL
  latency_ms    INT
);

CREATE TABLE ingest_jobs (
  id            SERIAL PRIMARY KEY,
  source_uri    TEXT NOT NULL,
  content_hash  TEXT UNIQUE,             -- idempotency key
  type_hint     TEXT,
  status        TEXT DEFAULT 'running',  -- running | pr_open | merged | parse_error | failed
  branch        TEXT,
  pages_touched TEXT[],
  created_at    TIMESTAMPTZ DEFAULT now(),
  finished_at   TIMESTAMPTZ,
  error         TEXT
);
```

## Read-only views for agents

Agents get aggregate views, not raw tables — this is both a privacy boundary and a prompt-simplicity win:

```sql
-- "Has another distributor solved this before?"
CREATE VIEW v_error_resolutions AS
SELECT t.error_slugs, d.name AS distributor, t.resolution, t.closed_at
FROM tickets t
JOIN customers c ON c.id = t.customer_id
JOIN distributors d ON d.id = c.distributor_id
WHERE t.status = 'closed' AND t.resolution IS NOT NULL;

-- "What's trending in the field this month?"
CREATE VIEW v_error_frequency AS
SELECT error_slug, date_trunc('week', occurred_at) AS week, count(*) AS events
FROM telemetry_events
WHERE error_slug IS NOT NULL
GROUP BY 1, 2;

-- Curator backlog: errors happening in the field with thin documentation
CREATE VIEW v_kb_gaps AS
SELECT e.error_slug, count(*) AS events_30d
FROM telemetry_events e
WHERE e.occurred_at > now() - interval '30 days' AND e.error_slug IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC;
```

## Integration points

- **Ticket close → learning pipeline**: a webhook (or a poller on `tickets.status = 'closed' AND learn_status = 'pending'`) triggers `radiant learn --ticket <id>`; `learn_status` tracks the PR through merge.
- **Dashboard (Phase 5)**: reads PostgreSQL for metrics (ticket volume, error trends, agent answer quality) and renders Markdown pages for the knowledge browser. It is strictly read-only over both stores.
- **Slug integrity**: a nightly job checks every `*_slug` column against the index's `pages` table and reports dangling references (e.g. a page was renamed) — slugs are the foreign keys that cross the Git/SQL boundary, so they get their own referee.
