# 02 — Knowledge base specification

This document defines the Markdown conventions. Everything downstream — the graph, search, agents, lint — parses what is specified here, so treat this as the contract.

## Folder structure

```
knowledge/
  robots/            One page per robot MODEL (fleet units live in PostgreSQL)
  error_codes/       One page per error code
  procedures/        One page per repair/maintenance procedure
  firmware/          One page per firmware release
  products/          Components & consumables (batteries, sensors, brushes)
  customers/         One page per customer ACCOUNT (contacts/CRM events in PostgreSQL)
  distributors/      One page per distributor
  tickets/           One page per NOTEWORTHY ticket (see "Ticket pages" below)
  personal/
    ideas/           One page per startup/product idea
    meetings/        One page per meeting (YYYY-MM-DD-slug.md)
    investors/       One page per investor/firm
    competitors/     One page per competitor
    research/        Market analysis, interview synthesis, blog drafts

sources/             Original documents cited by pages (Git LFS)
  manuals/  bulletins/  faqs/  exports/   (email/WhatsApp/CRM dumps)

templates/           One template per page type — radiant new copies these
build/               Derived artifacts (index.db) — gitignored
```

Rules:

- **Filename = slug = page id.** Lowercase, `[a-z0-9_-]`, e.g. `error203.md`, `battery_calibration.md`. Slugs are globally unique across all of `knowledge/` (the linker resolves `[[error203]]` without a path).
- **Meetings are date-prefixed**: `2026-07-03-acme-facilities-pilot.md`.
- One concept per page. If a section of a page grows past ~150 lines or gets linked from 3+ other pages, split it into its own page.

## Frontmatter

### Base schema (every page)

```yaml
---
id: error203                  # must equal filename without .md
type: error_code              # one of the types below
title: "Error 203 — Navigation LiDAR Timeout"
aliases: ["E203", "nav lidar timeout"]   # resolved by [[links]] and search
tags: [navigation, lidar]
status: active                # draft | active | deprecated
sources:                      # every technical page needs ≥1 source
  - id: S1
    doc: sources/manuals/scrubber50-service-manual-2024.pdf
    locator: "pp. 34-36"      # page / section / message timestamp
  - id: S2
    doc: ticket:1042          # operational refs use ticket:<postgres id>
    locator: ""
created: 2026-07-07
updated: 2026-07-07
---
```

### Typed relations (the knowledge graph)

Each type adds relation fields whose values are **lists of slugs**. These become typed graph edges; body `[[links]]` become untyped `mentions` edges. Traversal-quality relations belong in frontmatter, not just prose.

| Type | Relation fields |
|---|---|
| `robot` | `components: [products]`, `firmware_history: [firmware]`, `known_errors: [error_codes]`, `procedures: [procedures]` |
| `error_code` | `affects_robots`, `caused_by: [products/procedures]`, `introduced_in: [firmware]`, `fixed_in: [firmware]`, `resolved_by: [procedures]` |
| `procedure` | `applies_to: [robots]`, `resolves: [error_codes]`, `requires: [products]` |
| `firmware` | `applies_to: [robots]`, `fixes: [error_codes]`, `introduces: [error_codes]`, `supersedes: [firmware]` |
| `product` | `used_in: [robots]`, `related_procedures: [procedures]` |
| `customer` | `robots_deployed: [robots]`, `distributor: [distributors]` |
| `distributor` | `customers`, `regions: [strings]`, `certified_on: [robots]` |
| `ticket` | `customer`, `robot`, `error_codes`, `resolved_by: [procedures]`, `postgres_id: 1042` |
| `meeting` | `attendees: [strings]`, `relates_to: [any slugs]` |
| `idea` / `investor` / `competitor` / `research` | `relates_to: [any slugs]` |

The full edge vocabulary is fixed: `components, firmware_history, known_errors, procedures, affects_robots, caused_by, introduced_in, fixed_in, resolved_by, applies_to, resolves, requires, fixes, introduces, supersedes, used_in, related_procedures, robots_deployed, distributor, customers, certified_on, customer, robot, error_codes, attendees, relates_to, mentions`. `radiant lint` rejects unknown relation keys — extend the vocabulary here first, then in the lint config.

## Linking

- Wiki links: `[[error203]]` or with display text `[[error203|Error 203]]`. Resolution order: exact slug → alias (case-insensitive). Ambiguous aliases are a lint error.
- Section links: `[[error203#Root causes]]` — agents cite at this granularity.
- Broken links are a **CI failure** on `knowledge/` changes. A link may point to a `draft` page; it may not point to nothing.

## Citations

Two-hop traceability: **agent answer → page section → source document.**

1. Sources are declared in frontmatter with stable ids `S1, S2, …` (append-only — never renumber, so old citations stay valid).
2. Fact-bearing statements in the body carry inline markers: `LiDAR timeout threshold is 2.5 s [S1].`
3. `radiant lint` enforces: every `[Sn]` marker resolves to a frontmatter source; technical types (`robot`, `error_code`, `procedure`, `firmware`, `product`) must have ≥1 source; warn on declared-but-unused sources.
4. Knowledge derived from tickets cites `doc: ticket:<id>` — the ticket row in PostgreSQL is the source of record, and the ticket page (if any) is a readable summary.
5. Personal pages (`personal/`) are exempt from the source requirement — your own thoughts don't need citations, though meeting pages should name attendees and date.

## Page body layout

Templates in `templates/` define the canonical section headings per type (e.g. every `error_code` page has `## Symptoms`, `## Root causes`, `## Diagnosis`, `## Resolution`, `## History`). Keep the headings stable: agents cite `[[page#Section]]`, and renaming a heading breaks citations. `radiant lint` warns when a page is missing its template's required headings.

## Page lifecycle

```
draft ──review/merge──▶ active ──superseded/obsolete──▶ deprecated
```

- **draft**: created by ingestion, not yet human-reviewed. Agents may read drafts but must label the citation `(draft)` in answers.
- **active**: reviewed. Default citation material.
- **deprecated**: kept for history; body must open with a pointer to the replacement (`> Superseded by [[v2_9]]`). Excluded from retrieval by default.

Pages are deprecated, not deleted, unless they were created in error.

## Dedup rules (ingestion must obey)

Before creating any page, the ingestion agent must:

1. Search slugs and aliases for exact/near matches (`error-203`, `E203`, `err_203` are the same page).
2. Run FTS over the proposed title + summary; any hit scoring above the dedupe threshold ⇒ **update that page** (merge content, append a source, extend relations) instead of creating a new one.
3. When genuinely new, register discoverable aliases in frontmatter at creation time.

“Update, don’t duplicate” is the prime directive of ingestion. A duplicate page silently forks the truth.

## Lint rules summary (`radiant lint`, enforced in CI)

| Rule | Severity |
|---|---|
| Frontmatter parses and matches the type schema | error |
| `id` equals filename; slug charset valid; slug unique | error |
| All `[[links]]` and relation slugs resolve | error |
| All `[Sn]` markers resolve to declared sources | error |
| Technical page has ≥1 source | error |
| Unknown relation key | error |
| Ambiguous alias (two pages claim it) | error |
| Declared source never cited | warning |
| Missing template-required headings | warning |
| `deprecated` page without replacement pointer | warning |
