# 07 — Build plan

Six phases, each independently shippable and each ending in an acceptance test you can run. Estimates assume one builder working with Claude Code; phases 1–4 are the critical path, 5–6 are expansion.

## Phase 0 — Foundation (repo & conventions) · ~2-3 days

Make the knowledge base real before writing any pipeline.

**Build:**
- Repo scaffold: `knowledge/` tree, `templates/`, `sources/` with Git LFS, `.gitignore` for `build/`.
- `radiant` CLI skeleton (Python 3.12, typer, uv): `radiant new`, `radiant lint`.
- Lint = the full rule table from [02-knowledge-spec.md](02-knowledge-spec.md): frontmatter schemas (pydantic models per page type), slug/link/alias resolution, citation-marker checks.
- GitHub Actions: run `radiant lint` on every PR touching `knowledge/`.
- Seed the KB by hand: ~10 real pages (2 robots, 3 error codes, 2 procedures, 1 firmware, 2 personal) to pressure-test the conventions.

**Accept when:** `radiant new error_code error502` creates a valid page; a PR with a broken `[[link]]` fails CI; the 10 seed pages lint clean.

## Phase 1 — Index & search · ~3-5 days

**Build:**
- `radiant index`: parse all pages → `build/index.db` (pages, aliases, edges, sections, FTS5 — schema in [04-retrieval.md](04-retrieval.md)). Atomic swap on rebuild.
- `radiant search`: tiers 0–2 (exact/alias, FTS, graph expansion) with "why retrieved" on every hit.
- `radiant walk <slug> <rel>` for manual graph exploration.
- CI: rebuild index on merge to main (artifact upload).

**Accept when:** `radiant search "E203"` returns error203 via alias, instantly; `radiant walk scrubber50 known_errors` lists its error codes; searching a term that only appears in a procedure body finds it via FTS.

## Phase 2 — Ingestion pipeline · ~1-2 weeks

**Build:**
- Parsers: PDF (docling), plain text/notes; email + WhatsApp parsers can wait for Phase 6.
- Extractor: Claude Sonnet with the KB context pack (slug/alias list + type schemas), emitting the ops format from [03-pipelines.md](03-pipelines.md). Prompts in `pipeline/prompts/`, versioned.
- Deterministic reconcile/dedup stage with tests (alias collision, FTS-similarity threshold).
- Apply stage: branch, write pages, self-lint with one repair loop, open PR via GitHub API, record in `ingest_jobs` (PostgreSQL can be a single Docker container at this point — only `ingest_jobs` is needed so far).

**Accept when:** ingesting one real robot manual produces a reviewable PR that creates/updates robot, error-code, and procedure pages with correct `[Sn]` citations and locators; re-running the same ingest is a no-op; ingesting a doc that mentions an existing error updates that page instead of duplicating it.

> **Status:** built (see `radiant/pipeline/` and docs/03 → Implementation status). The deterministic stages — parsers, ops format, reconcile/dedup, apply with citation-id assignment, job log, lint gate — are tested end to end via `--plan` mode. Remaining for full acceptance: run the `ClaudeExtractor` against a real manual once API credentials are configured, and tune `pipeline/prompts/extract.md` on the results.

## Phase 3 — Ask: the support agent · ~1-2 weeks

**Build:**
- Context assembly (budgeted sections + graph paths) per [04-retrieval.md](04-retrieval.md).
- Support agent on the Claude Agent SDK: scope enforcement in the retrieval tools, answer contract, citation verifier with one bounce-back, honest-refusal path.
- `radiant ask "..."` CLI entry; answers logged to `agent_answers`.
- Eval harness: `evals/questions.yaml` (~20 golden questions from the seeded KB), CI gate on citation validity + golden recall.

**Accept when:** "Why is Error 203 happening?" returns a correct answer citing `error203#Root causes`; "Which firmware fixed it?" cites the firmware page via the graph edge; an out-of-domain question gets an honest refusal; evals pass in CI.

> **Status:** built (see `radiant/agent/`). Deterministic and tested end to end via a stub responder: scope enforcement (`radiant.yaml`, support agent structurally can't see `customer`/`personal` pages), budgeted context assembly with graph evidence paths, the answer contract + citation verifier, the verify→one-bounce-back→honest-refusal loop, the golden-set eval harness (`evals/questions.yaml`), and the answer log. The honest-refusal path needs no model call and is demoable now (`radiant ask "bake a cake?"`). Remaining for full acceptance: the `ClaudeResponder` and `radiant eval` in CI activate once API credentials are configured (CI runs evals automatically when the `ANTHROPIC_API_KEY` secret is present).

## Phase 4 — Continuous learning · ~1 week

**Build:**
- `tickets` + `ticket_messages` tables; minimal ticket intake (CSV import or manual insert is fine — the ticketing-system webhook can come later).
- `radiant learn --ticket <id>`: resolution extraction → ops → `learn/ticket-<id>` PR, `learn_status` tracking.
- Merge policy knob in `radiant.yaml` (start: everything human-reviewed).
- Curator's unanswerable-question backlog: low-confidence `agent_answers` → suggested stub pages.

**Accept when:** closing a seeded ticket produces a learn-PR that improves an error page; after merging it, `radiant ask` answers the ticket's question *with the new knowledge cited*; asking something undocumented lands a row in the curator backlog.

**⬆ This is the whole-system milestone**: source → page → answer → ticket → better page. Everything after is scale-out.

## Phase 5 — Operational layer & dashboard · ~2 weeks

**Build:**
- Full PostgreSQL schema ([06-operational-data.md](06-operational-data.md)): fleet, customers, distributors, telemetry, agent views.
- Ticket-system webhook → auto-trigger learning; nightly slug-integrity job.
- Read-only dashboard: KB browser (rendered Markdown + graph view), error trends, ticket volume, answer quality (feedback rate, citation validity over time).
- `ops_query` tool for the support agent ("has another distributor solved this?" via `v_error_resolutions`).

**Accept when:** a support lead can browse the KB, see error-frequency trends, and read agent-answer quality metrics without touching a terminal.

## Phase 6 — Scale-out & personal brain polish · ongoing

- Vector tier: sqlite-vec + embedding pipeline, wired in as cascade tier 3 only; add semantic eval cases ("robot drifts sideways" → traction page).
- Email/WhatsApp/CRM parsers; scheduled batch ingestion.
- Chief-of-staff agent: meeting synthesis, weekly review ("what did I learn from OEMs?", "recurring investor concerns"), writing to `personal/` via PRs.
- Merge-policy loosening per [03-pipelines.md](03-pipelines.md) once learn-PR quality data supports it.
- Migrate `sources/` to object storage if LFS grows past ~2 GB.

## Build order rationale

Index before ingestion (Phase 1 ← 2) because the extractor needs dedup search from day one. Ask before learn (Phase 3 ← 4) because the learning loop's payoff — better answers — is only measurable once answers exist. Postgres appears bottom-up, table by table, as each phase needs it, rather than as an upfront schema project.

## Risks to watch

| Risk | Mitigation |
|---|---|
| Extraction quality varies across messy PDFs | Locator-preserving parsers + human PR review; keep prompts versioned and eval-covered |
| Duplicate pages sneak past dedup | Deterministic reconcile stage with tests; curator alias-suggestion sweep |
| Citation drift (renamed headings break `page#section` cites) | Lint warns on heading changes to cited sections; evals catch regressions |
| KB grows stale where tickets don't flow | Curator staleness sweep + `v_kb_gaps` telemetry view |
| Over-automation too early | Merge policy is config, starts strict, loosens only on measured unedited-merge rate |
