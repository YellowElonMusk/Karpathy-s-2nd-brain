"""Continuous learning: fold a closed ticket back into the KB (docs/03 Pipeline B).

Reuses the ingestion reconcile/apply/lint stages. The ticket-resolution
extraction sits behind the `LearnExtractor` interface so the runner —
extract -> reconcile -> apply -> lint -> status/policy — is testable without
API credentials; `--plan` applies a pre-written ops plan through the same path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from radiant import tickets as ticket_store
from radiant.kb import load_kb
from radiant.pipeline import policy
from radiant.pipeline.apply import apply_plan
from radiant.pipeline.common import git as _git, lint_errors_for
from radiant.pipeline.extractor import build_context_pack
from radiant.pipeline.ops import IngestPlan, load_plan, plan_to_yaml
from radiant.pipeline.reconcile import reconcile
from radiant.settings import load_settings
from radiant.tickets import Ticket

PROMPT_PATH = Path(__file__).parent / "prompts" / "learn.md"
DEFAULT_MODEL = "claude-opus-4-8"


class LearnExtractor(Protocol):
    def extract(self, ticket: Ticket, kb) -> IngestPlan: ...


@dataclass
class LearnResult:
    status: str  # done | dry-run | empty | lint_failed | skipped
    ticket_id: int
    pages: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    plan_yaml: str = ""
    lint_errors: list[str] = field(default_factory=list)
    merge_category: str = ""
    auto_merge_eligible: bool = False


def learn(
    root: Path,
    ticket_id: int,
    *,
    plan_file: Path | None = None,
    dry_run: bool = False,
    branch: bool = False,
    extractor: LearnExtractor | None = None,
) -> LearnResult:
    ticket = ticket_store.get_ticket(root, ticket_id)
    if ticket is None:
        raise SystemExit(f"error: no ticket #{ticket_id}")
    if ticket.status != "closed":
        raise SystemExit(f"error: ticket #{ticket_id} is {ticket.status!r}; only closed tickets are learned from")

    settings = load_settings(root)
    kb = load_kb(root)

    if plan_file is not None:
        plan = load_plan(plan_file)
    else:
        plan = (extractor or ClaudeLearnExtractor()).extract(ticket, kb)

    ops, notes = reconcile(kb, plan.ops)
    if not ops:
        ticket_store.set_learn_status(root, ticket_id, "skipped")
        return LearnResult("empty", ticket_id, notes=notes + ["nothing new to learn from this ticket"])

    category = policy.classify(ops)
    eligible = policy.auto_merge_eligible(settings.merge_policy, category)
    plan.ops = ops

    if dry_run:
        return LearnResult("dry-run", ticket_id, notes=notes, plan_yaml=plan_to_yaml(plan),
                           merge_category=category, auto_merge_eligible=eligible)

    changed = apply_plan(root, kb, ops)
    rel_changed = [str(p.relative_to(root)) for p in changed]

    lint_errors = lint_errors_for(root, rel_changed)
    if lint_errors:
        ticket_store.set_learn_status(root, ticket_id, "lint_failed")
        return LearnResult("lint_failed", ticket_id, pages=rel_changed, notes=notes,
                           lint_errors=lint_errors, merge_category=category)

    notes.append(f"merge policy {settings.merge_policy!r}: category {category!r}, "
                 f"auto-merge {'eligible' if eligible else 'requires human review'}")
    if branch:
        _git(root, "checkout", "-b", f"learn/ticket-{ticket_id}")
        _git(root, "add", *rel_changed)
        _git(root, "commit", "-m", f"learn: ticket #{ticket_id}")
        ticket_store.set_learn_status(root, ticket_id, "pr_open")
        notes.append(f"committed on branch learn/ticket-{ticket_id} — push and open a PR")
    else:
        ticket_store.set_learn_status(root, ticket_id, "applied")
        notes.append("applied to working tree — review with `git diff`, then commit")

    return LearnResult("done", ticket_id, pages=rel_changed, notes=notes,
                       merge_category=category, auto_merge_eligible=eligible)


class ClaudeLearnExtractor:
    """Ticket-resolution extraction via Claude structured outputs."""

    def __init__(self, model: str | None = None):
        import os

        self.model = model or os.environ.get("RADIANT_LEARN_MODEL", DEFAULT_MODEL)

    def extract(self, ticket: Ticket, kb) -> IngestPlan:
        from radiant.agent.client import make_client, parse_structured

        client = make_client()
        system = [
            {
                "type": "text",
                "text": PROMPT_PATH.read_text(encoding="utf-8")
                + "\n\n# Knowledge-base context\n\n"
                + build_context_pack(kb),
                "cache_control": {"type": "ephemeral"},
            }
        ]
        resp = parse_structured(
            client,
            model=self.model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=system,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Resolved ticket #{ticket.id}. Cite facts with "
                        f'doc: "ticket:{ticket.id}".\n\n{ticket.thread_text()}'
                    ),
                }
            ],
            output_format=IngestPlan,
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("learn extraction was refused by the model")
        return resp.parsed_output
