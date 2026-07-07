# RadiantBrain

A Git-based "second brain" with two jobs:

1. **Personal knowledge management** — ideas, meetings, investor notes, research, strategy.
2. **RadiantBots technical knowledge engine** — powering AI support agents that give explainable, citation-backed answers about robots, error codes, firmware, and repair procedures.

Unlike a traditional RAG system, the knowledge base is **Markdown-first**: human-readable, version-controlled, continuously improved by AI, and inspectable at every step. Vector embeddings are an optional accelerator, never the source of truth.

## Status

This repository currently contains the **design blueprint**. Nothing is implemented yet — the docs below are the build plan.

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

## Quick start (once built)

```bash
radiant new error_code error203        # create a page from a template
radiant ingest sources/manuals/scrubber50-service-manual.pdf
radiant index                          # rebuild the search index
radiant search "lidar timeout"
radiant ask "Why is Error 203 happening on a Scrubber 50?"
radiant learn --ticket 1234            # fold a closed ticket back into the KB
```

Start with [docs/07-build-plan.md](docs/07-build-plan.md) to build this system.
