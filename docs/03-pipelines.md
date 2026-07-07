# 03 — Pipelines: ingestion & continuous learning

Two pipelines write to the knowledge base. Both produce **Git branches + PRs**, never direct writes to main. Both are runs of the same underlying machinery: parse → extract → reconcile → propose.

## Pipeline A: Ingestion (`radiant ingest`)

Turns a raw source into knowledge-page creations/updates.

```
radiant ingest sources/manuals/scrubber50-service-manual-2024.pdf
radiant ingest exports/whatsapp-distributor-a-2026-06.txt --type chat
radiant ingest "https://vendor.example/service-bulletin-17.pdf"
```

### Stages

**1. Acquire & archive.** Copy the original into `sources/` (Git LFS), compute a content hash. If the hash already exists in the ingest log (PostgreSQL `ingest_jobs`), stop — already ingested.

**2. Parse to intermediate Markdown.** Format-specific parsers, all emitting `(text, locator)` pairs so citations survive:

| Input | Parser | Locator granularity |
|---|---|---|
| PDF / manuals / SOPs / bulletins | docling (fallback pymupdf) | page number |
| FAQs / HTML | readability + html2text | section heading |
| Email exports | Python `mailbox` / `.eml` parser | message-id + date |
| WhatsApp export `.txt` | custom regex parser | timestamp + sender |
| CRM notes / meeting notes | passthrough | file + heading |
| Support tickets | PostgreSQL reader | ticket id + message id |

**3. Extract structured knowledge (Claude Sonnet).** The extractor receives the parsed document in chunks plus a **KB context pack**: the list of existing slugs/aliases/titles and the type schemas from [02-knowledge-spec.md](02-knowledge-spec.md). It emits a list of proposed operations:

```yaml
- op: update            # update | create
  page: error_codes/error203.md
  reason: "Manual documents two additional root causes"
  sections:
    "Root causes": |
      ...new content with [S3] markers...
  add_sources:
    - doc: sources/manuals/scrubber50-service-manual-2024.pdf
      locator: "p. 34"
  add_relations:
    fixed_in: [v2_8]
- op: create
  page: procedures/lidar_cleaning.md
  from_template: procedure
  ...
```

**4. Reconcile (dedupe).** For every `create`, run the dedup rules from the spec (alias match, FTS similarity). Above threshold ⇒ downgrade to `update`. This stage is deterministic code, not LLM judgment, so it can be tested.

**5. Apply & propose.** Apply operations on branch `ingest/<source-slug>`, run `radiant lint` (a failing lint aborts the PR — the agent must fix its own output first), regenerate summaries for touched pages, open a PR whose description lists every page touched, why, and with what sources. Record the run in `ingest_jobs`.

**6. Human review & merge.** The PR diff *is* the review interface. On merge, CI rebuilds the index.

### Design notes

- Chunking is only for extraction context limits; **pages, not chunks, are the unit of knowledge**. The extractor writes whole sections.
- Extraction runs page-type-aware prompts (an error-code page and a meeting note need different eyes). Prompts live in `pipeline/prompts/` in the repo, versioned like code.
- Idempotency: re-ingesting the same file is a no-op (hash check); re-ingesting a *revised* manual produces a clean update diff against existing pages.

## Pipeline B: Continuous learning (`radiant learn`)

Every resolved support ticket makes the KB smarter.

```
Ticket closed (webhook from ticketing system, or manual: radiant learn --ticket 1042)
    ↓
Load ticket thread from PostgreSQL (messages, robot serial → model slug, error codes seen)
    ↓
Claude: extract the CONFIRMED resolution
    - what was the symptom / error code?
    - what was the root cause?
    - what fixed it, verified how?
    - is this new knowledge, or confirmation of existing knowledge?
    ↓
Propose KB operations:
    - confirmation  → append a "confirmed by ticket:1042" source to the existing resolution
    - new variant   → new root cause / resolution subsection on the error page [Sticket]
    - new knowledge → new procedure page + relations (error → resolved_by → procedure)
    - notable case  → optional ticket page in knowledge/tickets/ (see below)
    ↓
Branch learn/ticket-1042 → lint → PR
    ↓
Merge policy (below) → index rebuild → future answers improve
```

### When does a ticket get its own page?

Most tickets should **not** become pages — their knowledge belongs on the error/procedure pages, and the raw thread stays queryable in PostgreSQL. Create a `knowledge/tickets/` page only when the case is a useful narrative: a novel failure mode, a multi-cause diagnosis worth reading start-to-finish, or a reference case distributors keep asking about. Rule of thumb: a ticket page earns its place when you'd link to it from at least one other page.

### Merge policy

Start strict, loosen with evidence:

| Stage | Policy |
|---|---|
| Phase 4 launch | All `learn:` PRs human-reviewed |
| After ~50 merged learn-PRs with >90% unedited-merge rate | Auto-merge **confirmations** (source-append only, no prose changes) |
| Mature | Auto-merge additive section edits; human review only for `create` ops and edits to `status: active` resolution steps |

The policy is a config knob in `radiant.yaml`, not code, so it can be tightened instantly if quality slips.

## Failure handling (both pipelines)

- Parser failure → `ingest_jobs.status = 'parse_error'`, original still archived; retry with fallback parser.
- Extractor produces invalid ops (unknown page type, bad slug) → op rejected, logged, rest of batch proceeds.
- Lint failure on the branch → agent gets one repair attempt with lint output; still failing → PR opened as **draft** with failures listed for a human.
- Nothing is ever lost: worst case is an archived source with a failed job row, re-runnable later.
