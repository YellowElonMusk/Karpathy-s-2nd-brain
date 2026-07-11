# 08 — Plugging external agents into the globe

The globe reads from **one events store** (`radiant/events.py`). Anything that
writes an event into that store appears on the globe — so integrating an
external agent (OpenClaw, Hermes, n8n, a cron script, anything) just means
giving its cron job a one-line way to push an event in. The store is
agent-agnostic; agents are tagged by an `agent` field so you can tell (and
filter) which one produced what.

## Two ways in

### 1. HTTP POST (best for agents on another host/process)

`radiant serve` exposes `POST /api/events`. Send one event or a list:

```bash
curl -X POST http://127.0.0.1:8787/api/events \
  -H 'content-type: application/json' \
  -d '{
    "headline": "YC backs Lagos AI logistics startup",
    "body": "W26 batch, $500K seed.",
    "place": "Lagos",
    "category": "startup",
    "agent": "openclaw",
    "job": "startup-radar",
    "sources": ["yc.com"],
    "related_slugs": ["idea_leasing"]
  }'
```

Response: `{"created": [id...], "errors": [...]}` — invalid events are reported,
not fatal, so one bad row doesn't sink a batch.

**Auth:** if the environment variable `RADIANT_INGEST_TOKEN` is set, requests
must send `Authorization: Bearer <token>`. Leave it unset for local-only use
(the server binds `127.0.0.1` by default). Set it before exposing the port.

### 2. CLI (best for an agent that can shell out)

```bash
radiant events add "War risk rises: strike near Hormuz" \
  --place Iran --agent hermes --job geopolitics-watch --link scrubber50
```

Same normalization and geocoding as the HTTP path.

## The event — only two things are required

| field | required | notes |
|---|---|---|
| `headline` (aka `title`, `name`, `summary`) | ✅ | the one-liner on the globe |
| a **location** | ✅ | either `place`/`location`/`city`/`country` (geocoded) **or** explicit `lat`+`lon` |
| `body` (aka `details`, `description`) | — | the drill-down report shown on click |
| `category` (aka `type`) | — | `geo` \| `startup` \| `funding`; auto-classified from the text if omitted |
| `agent` | — | which agent produced it (shown + filterable) |
| `job` (aka `cron_job`, `cron`) | — | the cron job name, shown in the report |
| `sources` / `source` | — | list of source links/names |
| `related_slugs` (aka `related`, `links`) | — | KB page slugs this event touches → clickable in the report, jumps to the graph |
| `occurred_at` (aka `timestamp`, `date`) | — | ISO time; defaults to now |

**Field names are tolerant** (`title` or `headline`, `location` or `place`, …) so
you usually don't have to reshape your agent's output — just POST it. Places are
resolved by an **offline gazetteer** (`radiant/geo.py`): major cities, tech hubs,
and countries, accent- and case-insensitive, with phrase extraction ("protests in
France" → France). Unknown places must send `lat`/`lon`; extend `PLACES` to add
more names.

## Wiring a cron job (pattern for any agent)

Your agent already runs jobs on a schedule and produces findings. Add a final
step that emits an event per finding. Two shapes:

**If the agent can call HTTP** — have the job `POST` its finding as JSON. Map your
fields once (or rely on the tolerant names above). Example post-step in Python:

```python
import requests
requests.post("http://HOST:8787/api/events",
    headers={"Authorization": "Bearer " + TOKEN},   # if RADIANT_INGEST_TOKEN is set
    json={"headline": finding.title, "body": finding.summary,
          "place": finding.location, "category": finding.kind,
          "agent": "hermes", "job": "geopolitics-watch",
          "sources": finding.urls, "related_slugs": finding.kb_hits})
```

**If the agent writes files/stdout** — point it at a drop folder and let
RadiantBrain pull. Each job writes a `*.json` (one event, a list, or
`{"events":[...]}`) or `*.jsonl` (one event per line) into the folder:

```bash
radiant events import findings.json     # one-off bulk load
radiant events watch ./agent-events --once     # ingest the folder once (schedule from cron)
radiant events watch ./agent-events            # or watch continuously
```

`watch` ingests every event file in the folder and moves it into
`.processed/`, so re-running is a safe no-op — the agents just keep dropping
files and never coordinate with the server.

Point each agent's `agent` field at its name (`openclaw`, `hermes`) so the globe
report shows the provenance and you can filter by producer.

## What's still needed for a fully-live globe

This ingestion surface is done and agent-agnostic. The remaining Phase 7 work is
the **watcher cron jobs themselves** (geopolitics / new-startup / funding radars)
that fetch and summarize world events — those need the model API key and web
search. Once they run, each firing just calls one of the two paths above and the
globe goes live. Until then, hand-fed events and the built-in sample feed drive it.
