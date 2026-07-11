# RadiantBrain

A Git-based "second brain" with two jobs:

1. **Personal knowledge management** — ideas, meetings, investor notes, research, strategy.
2. **RadiantBots technical knowledge engine** — powering AI support agents that give explainable, citation-backed answers about robots, error codes, firmware, and repair procedures.

Unlike a traditional RAG system, the knowledge base is **Markdown-first**: human-readable, version-controlled, continuously improved by AI, and inspectable at every step. Vector embeddings are an optional accelerator, never the source of truth.

## Status

**Phases 0–5 are built and tested** (see [docs/07-build-plan.md](docs/07-build-plan.md)): the `radiant` CLI with `new`, `lint`, `index`, `search`, `walk`, `ingest`, `ask`, `eval`, `learn`, `tickets`, `curator`, `ops`, `doctor`, and `dashboard`, plus CI. This closes the core loop — **source → page → answer → resolved ticket → better page** — and adds the operational layer: prior-resolution lookup, a slug-integrity check across the Git/SQL boundary, and a self-contained read-only dashboard. The Claude-powered stages (ingestion extractor, support agent, ticket-resolution extractor, chief-of-staff) are fully wired but dormant until an `ANTHROPIC_API_KEY` is configured; everything around them runs and is tested today. The **personal brain** is now built (Phase 6): `radiant note` for frictionless capture and `radiant digest` for monitoring VC-investing trends and competitor moves — both deterministic and usable with no API key — plus the chief-of-staff synthesis agent. The optional **semantic vector tier** is built too (`radiant index --embed` / `radiant search --semantic`). Remaining scale-out (live Postgres, served dashboard, real embedding provider, PR-authoring chief-of-staff) is deferred to Phase 7.

## Repository map

```
docs/                    Design blueprint (read in order)
  01-architecture.md       System overview, components, decision log
  02-knowledge-spec.md     Markdown conventions: folders, frontmatter, links, citations
  03-pipelines.md          Ingestion pipeline + continuous-learning loop
  04-retrieval.md          Search tiers: pages → graph → vectors, index build
  05-agents.md             Agent roster, scoping, answer contract, evals
  06-operational-data.md   PostgreSQL schema for tickets/CRM/telemetry
  07-build-plan.md         Phased milestones with acceptance criteria

templates/               Page templates for every document type
knowledge/               The knowledge base itself (contains worked examples)
sources/                 Original documents (PDFs, exports) that pages cite
radiant/                 The radiant CLI (Python package)
tests/                   Test suite (pytest)
build/                   Derived search index — gitignored, `radiant index` rebuilds it
```

## Core idea in one diagram

```
Raw sources (PDFs, tickets, emails, notes)
        │  radiant ingest
        ▼
Markdown knowledge base  ←── the single source of truth, reviewed via Git PRs
        │  radiant index (derived, disposable)
        ▼
SQLite index: full-text + knowledge graph + optional vectors
        │
        ▼
AI agents (support, curator, chief-of-staff)
        │  every answer cites knowledge pages, which cite raw sources
        ▼
Users / tech support / dashboard
```

## Design principles

- **Markdown is the source of truth.** Everything else (indexes, graphs, vectors) is derived and rebuildable.
- **Everything is version-controlled.** AI edits arrive as branches/PRs a human can review.
- **AI generates and maintains documentation; humans can inspect and edit every page.**
- **Operational data (tickets, telemetry, CRM) lives in PostgreSQL, not in Markdown.** The two link by page slug.
- **Every AI answer is traceable**: answer → knowledge page section → original source document.
- **The system learns**: every closed support ticket becomes a knowledge-base improvement.

## Quick start

```bash
# install (Python >= 3.11)
uv venv && uv pip install -e ".[dev]"     # or: pip install -e ".[dev]"
source .venv/bin/activate

radiant new error_code error502 -t "Error 502 — Brush Motor Stall"
radiant lint                           # validate frontmatter, links, citations
radiant index                          # rebuild build/index.db (FTS + graph)
radiant search "lidar timeout"         # tiered: alias -> full-text -> graph
radiant search "E203" --json           # machine-readable, for agents
radiant index --embed                  # also build the optional semantic vector tier
radiant search "sensor stops responding" --semantic   # semantic fallback (tier 3)
radiant walk error203                  # explore the knowledge graph
radiant walk scrubber50 known_errors --depth 2

pytest                                 # run the test suite
```

Ingestion (Phase 2 — Claude extraction activates once `ANTHROPIC_API_KEY` is set):

```bash
radiant ingest bulletin-17.pdf --dry-run     # Claude proposes ops; print, change nothing
radiant ingest bulletin-17.pdf --branch      # apply + commit on ingest/bulletin-17
radiant ingest notes.md --plan plan.yaml     # no API key needed: apply a pre-written ops plan
```

Ask the support agent (Phase 3 — activates once `ANTHROPIC_API_KEY` is set):

```bash
radiant ask "Why is Error 203 happening on a Scrubber 50?"   # citation-verified answer
radiant ask "How do I bake a cake?"      # out-of-domain -> honest refusal (no key needed)
radiant ask "..." --json                 # raw answer contract
radiant eval                             # run the golden-set evaluation
```

Continuous learning (Phase 4 — the Claude extractor activates once the key is set):

```bash
radiant tickets import ticket.yaml       # load a resolved ticket + its thread
radiant learn --ticket 1 --dry-run       # propose KB updates from the ticket
radiant learn --ticket 1 --branch        # apply + commit on learn/ticket-1
radiant tickets list                     # track learn_status per ticket
radiant learn --pending                  # process every closed ticket awaiting learning
radiant curator                          # backlog of questions the KB couldn't answer
```

Operations (Phase 5 — no API key needed):

```bash
radiant ops error203                     # prior ticket resolutions for an error
radiant doctor                           # verify operational slugs resolve against the KB
radiant dashboard -o dashboard.html      # self-contained read-only ops dashboard
```

Personal brain — capture & monitor (Phase 6 — no API key needed):

```bash
radiant note investor example_ventures "Pushed again on CAC scaling"     # log a concern
radiant note competitor acme_robotics "Launched at aggressive pricing"   # log a move
radiant note meeting sequoia-call "They liked the deflection metric"     # auto date-prefixed
radiant digest concerns                  # recurring investor concerns, across all investors
radiant digest competitors --timeline    # competitor moves, newest first
radiant review --since 2026-06-01        # weekly rollup: recurring themes + moves + actions
radiant review --write                   # save the rollup as a dated research page
radiant ask --agent chief-of-staff "What concerns did investors repeatedly raise?"   # (needs key)
```

The ops console — a sci-fi dashboard toggling an Earth globe of world events and an
Obsidian-style neural graph of your knowledge (`pip install -e ".[web]"` first):

```bash
radiant serve                            # → http://127.0.0.1:8787
radiant events import events.json        # feed the globe (cron jobs write here later)
radiant events list
```

The **neural view** is your live `radiant index` graph — clicking a node opens the real
page and its connections. The **globe** shows geolocated world events; clicking a pin opens
the cron-job report. Runs in any browser; wrap in Tauri (desktop) or install as a PWA (phone)
later without a rewrite.

See [docs/07-build-plan.md](docs/07-build-plan.md) for the phase map and what's next (Phase 7 scale-out).
