# RadiantBrain

A Git-based "second brain" with two jobs:

1. **Personal knowledge management** — ideas, meetings, investor notes, research, strategy.
2. **RadiantBots technical knowledge engine** — powering AI support agents that give explainable, citation-backed answers about robots, error codes, firmware, and repair procedures.

Unlike a traditional RAG system, the knowledge base is **Markdown-first**: human-readable, version-controlled, continuously improved by AI, and inspectable at every step. Vector embeddings are an optional accelerator, never the source of truth.

## Status

**Phases 0–3 are built and tested** (see [docs/07-build-plan.md](docs/07-build-plan.md)): the `radiant` CLI with `new`, `lint`, `index`, `search`, `walk`, `ingest`, `ask`, and `eval`, plus CI. The two Claude-powered stages — the ingestion extractor and the support agent — are fully wired but dormant until an `ANTHROPIC_API_KEY` is configured. Everything around them runs and is tested today: retrieval, agent scoping, context assembly, the citation verifier, and the honest-refusal path (which needs no model call). Phases 4+ (continuous learning, dashboard) are designed but not yet implemented.

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

Coming in later phases (designed in `docs/`, not yet implemented):

```bash
radiant learn --ticket 1234            # fold a closed ticket back into the KB
```

Continue with [docs/07-build-plan.md](docs/07-build-plan.md) — next up is Phase 2 (ingestion).
