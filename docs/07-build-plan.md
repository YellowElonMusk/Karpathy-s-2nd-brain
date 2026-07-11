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

> **Status:** built (see `radiant/tickets.py`, `radiant/pipeline/learn.py`, `radiant/pipeline/policy.py`, `radiant/agent/curator.py`). Tested end to end via a stub extractor and `--plan`: the ticket store (YAML import + thread rendering, interim SQLite mirroring the docs/06 schema), `radiant learn --ticket` reusing the Phase 2 reconcile/apply/lint stages with `learn_status` tracking, the merge-policy engine (classifies confirmation/additive/structural and reports auto-merge eligibility under the `radiant.yaml` policy — starts `human-review`), and the curator's unanswered-question backlog. The demo loop imports a resolved ticket, learns from it, and the error page gains a ticket-cited diagnosis. Remaining for full acceptance: the `ClaudeLearnExtractor` activates once API credentials are configured; PR opening and the ticket-system webhook are Phase 5.

## Phase 5 — Operational layer & dashboard · ~2 weeks

**Build:**
- Full PostgreSQL schema ([06-operational-data.md](06-operational-data.md)): fleet, customers, distributors, telemetry, agent views.
- Ticket-system webhook → auto-trigger learning; nightly slug-integrity job.
- Read-only dashboard: KB browser (rendered Markdown + graph view), error trends, ticket volume, answer quality (feedback rate, citation validity over time).
- `ops_query` tool for the support agent ("has another distributor solved this?" via `v_error_resolutions`).

**Accept when:** a support lead can browse the KB, see error-frequency trends, and read agent-answer quality metrics without touching a terminal.

> **Status:** built (see `radiant/opsviews.py`, `radiant/integrity.py`, `radiant/dashboard.py`, `db/schema.sql`). The full PostgreSQL schema is delivered as `db/schema.sql` (the migration target); operational data stays in the interim per-store SQLite files that mirror it, keeping the toolchain portable and testable. `radiant ops` exposes prior-resolution lookup ("has another distributor solved this?"), `radiant doctor` runs the nightly slug-integrity check across the Git/SQL boundary, `radiant learn --pending` is the webhook's poller alternative, and `radiant dashboard` generates a self-contained, theme-aware HTML view (KB browser, error frequency, ticket volume, learning pipeline, answer quality, documentation gaps). Remaining: standing up a live Postgres instance and a served (vs. generated-file) dashboard; the ticket-system webhook that triggers `learn --pending`.

## Phase 6 — Personal brain (VC trends, competitor moves, notes) · built

Pulled forward as the current phase so the founder can start using RadiantBrain daily. The value splits into **capture** (deterministic, works with no API key) and **synthesis** (the chief-of-staff agent, activates with the key).

- **Quick capture** — `radiant note <type> <slug> "..."` appends a dated bullet to the right section of a personal page (investor concern → "Concerns raised", competitor move → "Intel log", meeting note → "Notes"), creating the page from its template if needed. Meetings are auto date-prefixed. (`radiant/notes.py`)
- **Monitoring digests** — `radiant digest concerns | competitors | actions | ideas` (or `--type`/`--section`) collate one section across every page of a type, with a `--timeline` view newest-first. This is the VC-trends and competitor-moves monitor; it reads Markdown directly (always current) and is fully deterministic. (`radiant/digest.py`)
- **Weekly review** — `radiant review [--since DATE] [--write]` composes the digests into one rollup: recurring themes (a transparent keyword-overlap signal that surfaces a concern raised across *different* investors), all investor concerns, competitor moves, open action items, and active ideas — each line cited to its source page. `--write` saves it as a dated research page under `personal/research/`, so reviews accumulate in the KB. Deterministic; the chief-of-staff agent narrates over this backbone. (`radiant/review.py`)
- **Chief-of-staff agent** — `radiant ask --agent chief-of-staff "..."` runs the citation-verified answer pipeline over full scope (including `personal/`) with a synthesis prompt and a larger page budget (16), so aggregate questions ("what concerns did investors repeatedly raise?", "how are competitors moving on pricing?") are answered across many notes with per-page citations. Behind the same interface as the other agents — activates once `ANTHROPIC_API_KEY` is set. (`radiant/agent/prompts/chief.md`, `radiant/agent/support.py`)
- Seeded worked examples: `personal/investors/example_ventures.md`, `personal/competitors/acme_robotics.md`.

**Vector tier** (built earlier this cycle) also lands here: `radiant index --embed` / `radiant search --semantic`, behind the `Embedder` interface — `VoyageEmbedder` (hosted, needs `VOYAGE_API_KEY`) is the real semantic tier; `LocalEmbedder` is a deterministic offline fallback. Tier 3 sits below graph proximity and activates only when an embedder is supplied and the index carries vectors; pure-Python cosine keeps the index portable.

- **Ops console (sci-fi dashboard)** — `radiant serve` launches a local web app (`pip install -e ".[web]"`): a command-deck HUD that toggles between an **Earth globe** of geolocated world events (from the agent cron feed; clicking a pin opens the cron-job report) and an **Obsidian-style neural graph** of the knowledge base. The neural view is the real `build/index.db` — nodes/edges the agents traverse — and clicking a node opens the actual page, its sections, and its connections. Right panel: command buttons, layer/type filters, and collapsible projects derived from the real KB. Pure-canvas frontend (no JS build step); a thin FastAPI shell serves a tested JSON data layer (`radiant/webdata.py`) over the index + the world-event store (`radiant/events.py`). Runs in any browser; a Tauri desktop wrap or a PWA install are later packaging steps, not rewrites. (`radiant/webapp.py`, `radiant/web/index.html`)

**Accept when:** the founder can log an investor concern or competitor move in one command, review recurring themes with `radiant digest`, open the console and explore their real knowledge graph + world-event globe, and (with the key) ask the chief-of-staff for a synthesis with citations to the underlying notes.

> **Form factor (decided):** web app first — the globe/graph libraries are native to the web and it plugs straight into the `radiant` CLI/index; desktop (Tauri) and phone (PWA) are later wraps of the same frontend. **First build scope (decided):** the neural graph runs on real index data now; the globe runs on a sample event feed until the agent cron jobs (Phase 7) populate the events store.

## Phase 7 — Scale-out & productionization · next

Moved out of the original Phase 6 so the personal brain could ship first. None of these block daily personal use:

- Live PostgreSQL instance (replacing the interim SQLite stores) and a *served* dashboard (vs. the generated HTML file); the ticket-system webhook that triggers `learn --pending`.
- **Agent cron jobs that feed the globe** — scheduled watchers (geopolitics, new-startup, funding radars) that fetch/synthesize world events, geolocate them, and write to the events store (`radiant/events.py`) with a drill-down report. Needs the API key + web-search/fetch. Until then the globe runs the built-in sample feed.
- A real embedding provider wired to the vector tier + semantic eval cases ("robot drifts sideways" → traction page).
- Email / CRM parsers and scheduled batch ingestion (the WhatsApp parser already exists from Phase 2).
- Chief-of-staff writes to `personal/` via PRs (weekly-review generation, meeting-synthesis pages) — currently the agent answers; letting it *author* pages reuses the ingest apply/PR path.
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
