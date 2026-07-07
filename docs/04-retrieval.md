# 04 — Retrieval & search

Retrieval is a **cascade**: cheap, explainable methods first; embeddings last and optional. Every tier returns *pages with provenance*, never anonymous text chunks.

## The index (`build/index.db`)

One SQLite file, fully derived from `knowledge/` by `radiant index`, gitignored, rebuilt by CI on every merge. Schema:

```sql
-- Nodes: one row per page
CREATE TABLE pages (
  slug TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL,           -- draft | active | deprecated
  path TEXT NOT NULL,             -- knowledge/error_codes/error203.md
  summary TEXT,                   -- first paragraph / generated abstract
  updated TEXT
);

CREATE TABLE aliases (
  alias TEXT PRIMARY KEY COLLATE NOCASE,
  slug TEXT REFERENCES pages(slug)
);

-- Typed edges from frontmatter relations + untyped 'mentions' from body links
CREATE TABLE edges (
  src TEXT REFERENCES pages(slug),
  rel TEXT NOT NULL,              -- fixed vocabulary from 02-knowledge-spec
  dst TEXT REFERENCES pages(slug),
  PRIMARY KEY (src, rel, dst)
);

-- Sections: agents cite at section granularity
CREATE TABLE sections (
  slug TEXT REFERENCES pages(slug),
  heading TEXT,
  body TEXT,
  source_ids TEXT,                -- JSON list of [Sn] markers present
  PRIMARY KEY (slug, heading)
);

-- Full text
CREATE VIRTUAL TABLE fts USING fts5(
  slug, title, aliases, tags, body, content=''
);

-- Optional, phase 5
CREATE VIRTUAL TABLE vec USING vec0(
  embedding float[1024], slug TEXT, heading TEXT
);
```

Indexing pass: parse every page's frontmatter + body → populate tables → validate (same checks as `radiant lint`) → atomically swap the db file. Full rebuild of a few thousand pages takes seconds; no incremental complexity needed until it doesn't.

## Search cascade (`radiant search`, and what agents call)

```
Query
 │
 ├─ Tier 0: exact match ─ slug or alias hit? ("E203" → error203)
 │           → return page immediately, confidence: exact
 │
 ├─ Tier 1: full-text (FTS5, BM25) over title/aliases/tags/body
 │           → top-k pages with matched snippets
 │
 ├─ Tier 2: graph expansion
 │           seed = tiers 0-1 hits + entities recognized in the query
 │           follow typed edges 1-2 hops, rel-aware:
 │             troubleshooting intent → known_errors, resolved_by, fixed_in, requires
 │             history intent        → supersedes, introduced_in, tickets
 │           → related pages, each tagged with its PATH from the seed
 │             (robot:scrubber50 ─known_errors→ error203 ─resolved_by→ lidar_cleaning)
 │
 └─ Tier 3 (optional): vector search over section embeddings
             run only when tiers 0-2 return < N results above score floor,
             or when the query is explicitly semantic ("robot drifts sideways")
             → sections, mapped back to their pages
```

Results are merged and ranked: exact > FTS score > graph proximity (weighted by edge type) > vector similarity, with `status: active` boosted over `draft` and `deprecated` excluded by default. The response carries, for every result, **why it was retrieved** (matched alias, snippet, or graph path) — this is what makes answers explainable downstream.

### Why the graph tier matters

Keyword search finds `error203.md` when the user says "error 203". It cannot answer *"Which firmware fixed this, and is there a workaround for units that can't upgrade?"* — that requires walking `error203 ─fixed_in→ v2_8` and `error203 ─resolved_by→ lidar_cleaning`. The graph turns retrieval into one-hop reasoning and gives the agent a ready-made evidence chain to cite.

### Query understanding

A lightweight pre-step (Claude Haiku-class or rules) tags the query with intent (`troubleshoot | how-to | history | lookup | synthesis`) and recognized entities (robot models, error codes, firmware versions — matched against the alias table). Intent selects which edge types tier 2 follows and how much context tier assembly packs.

## Context assembly (for `radiant ask` / agents)

1. Take top-ranked pages/sections within a budget (default ~8 pages or 12k tokens).
2. For each, include: frontmatter summary, the relevant **sections** (not the whole page when large), the source list, and the graph path that led here.
3. Deduplicate overlapping sections; prefer `active` pages.
4. Hand to the agent with the citation contract from [05-agents.md](05-agents.md).

## Personal-brain queries

Same machinery, different scope and intent mix. "What concerns did investors repeatedly raise?" is a **synthesis** query: FTS + graph over `personal/investors/` and `personal/meetings/`, assemble *all* matching meeting sections (budget permitting), and let the agent aggregate across them with per-meeting citations. This works because meetings are one-page-per-meeting with stable headings — the retrieval unit matches the citation unit.
