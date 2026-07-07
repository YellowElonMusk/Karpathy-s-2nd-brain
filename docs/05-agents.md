# 05 — Agents

All agents are built on the Claude Agent SDK, share the same retrieval tools, and differ in **scope**, **prompt**, and **output contract**. Agents never touch `build/index.db` or Git directly — they call `radiant` tools, which enforce scoping and the PR-only write path.

## Roster

| Agent | Model class | Scope (folders) | Writes? | Purpose |
|---|---|---|---|---|
| **support** | Opus-class | `robots, error_codes, procedures, firmware, products, distributors, tickets` | No | Citation-backed answers for tech support / distributors / dashboard |
| **curator** | Sonnet | all of `knowledge/` | Via PRs only | Runs ingestion & learning extractions; housekeeping (stale pages, missing relations, orphan links) |
| **chief-of-staff** | Opus-class | everything incl. `personal/` | Via PRs only | Personal-brain queries, meeting synthesis, weekly reviews |

Scoping is declared in `radiant.yaml` and enforced in the retrieval layer (not in the prompt):

```yaml
agents:
  support:
    scope: [robots, error_codes, procedures, firmware, products, distributors, tickets]
    deny: [personal, customers]      # customer pages may hold commercial terms
    write: false
  curator:
    scope: ["knowledge/**"]
    write: pr-only
  chief-of-staff:
    scope: ["knowledge/**"]
    write: pr-only
```

A denied folder is invisible to the agent: excluded at index-query time, so scope violations are structurally impossible rather than prompt-discouraged.

## Tools exposed to agents

| Tool | Backing | Notes |
|---|---|---|
| `search(query, tiers?)` | retrieval cascade | returns pages + why-retrieved |
| `get_page(slug)` / `get_section(slug, heading)` | index | scope-filtered |
| `walk(slug, rel, depth)` | graph tier | typed traversal |
| `ops_query(sql_view)` | PostgreSQL read-only views | e.g. open tickets per error code; support agent gets aggregate views only |
| `propose_edit(ops)` | pipeline stage 5 | curator/chief-of-staff only; lands as PR |

## The answer contract (support agent)

Every answer is structured, and citations are **verified before the user sees anything**:

```json
{
  "answer_md": "Error 203 is a navigation LiDAR timeout... Two known root causes: ...",
  "citations": [
    {"page": "error_codes/error203", "section": "Root causes", "status": "active"},
    {"page": "firmware/v2_8", "section": "Fixes", "status": "active"}
  ],
  "evidence_chain": [
    "scrubber50 ─known_errors→ error203 ─fixed_in→ v2_8"
  ],
  "confidence": "high",          // high | medium | low
  "gaps": ["No documented behavior for firmware v2.9+"]
}
```

Rules:

1. **Every factual claim maps to a citation.** The verifier checks each cited `page#section` exists in the index and that cited pages were actually in the retrieved context. A failed check bounces the answer back to the agent once; failing again returns an honest "not documented" response.
2. **Draft pages are usable but labeled** `(draft — not yet reviewed)`.
3. **No retrieval hit above the confidence floor ⇒ say so.** The correct answer to an undocumented question is "the knowledge base doesn't cover this yet", plus a suggested `gaps` entry — never a plausible guess. Unanswerable questions are logged (`agent_answers.confidence = 'none'`) and become the curator's backlog.
4. Answers and their citations are logged to PostgreSQL (`agent_answers`) with user feedback (👍/👎) for the eval loop.

## Curator housekeeping (scheduled, weekly)

- Pages not updated in N months with open tickets referencing them → flag for review.
- Frontmatter relations that exist one-way (error says `fixed_in: v2_8`, firmware page missing `fixes: error203`) → propose the symmetric edge.
- `gaps` entries and unanswerable-question log → propose stub `draft` pages so the gap is visible in the KB itself.
- Alias suggestions from search misses (queries that hit tier 3 or nothing).

## Evals

Golden-set evaluation lives in `evals/` and runs in CI on every `knowledge/` or pipeline change.

```yaml
# evals/questions.yaml
- id: q001
  agent: support
  question: "Why is Error 203 happening on a Scrubber 50?"
  must_cite: [error_codes/error203]
  must_mention: ["LiDAR", "timeout"]
- id: q014
  agent: support
  question: "Which firmware fixed the nav lidar timeout?"
  must_cite: [firmware/v2_8]
- id: q020
  agent: support
  question: "How do I bake a cake?"        # out-of-domain probe
  expect: no_answer
```

Metrics tracked per run:

| Metric | Target |
|---|---|
| Citation validity (cited sections exist & were retrieved) | 100% — hard gate |
| Golden citation recall (`must_cite` present) | ≥ 90% |
| Honest refusal on out-of-domain probes | 100% |
| Answer latency (p95, cascade tiers 0–2) | < 10 s |

Grow the golden set from real logged questions: every 👎 answer and every unanswerable question is a candidate eval case. The eval set is the regression suite for the *knowledge base itself* — a page edit that breaks q014 fails CI just like a code change breaking a unit test.
