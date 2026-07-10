"""Merge-policy engine for learn PRs (docs/03-pipelines.md).

Starts strict and loosens with measured trust. The policy is a config knob
in radiant.yaml, not code, so it can be tightened instantly if quality slips.
This module only *classifies* a plan and reports whether the policy would
allow auto-merge — it never merges; that stays a git/PR operation.

Categories, least to most risky:
  confirmation  — only appends sources (a ticket confirms existing knowledge)
  additive      — adds new sections / relations, but creates no page
  structural    — creates pages, or edits resolution-bearing sections
"""

from __future__ import annotations

from radiant.pipeline.ops import PageOp

# Sections whose edits carry operational risk (a wrong repair step is worse
# than a wrong summary), so touching them is always "structural".
_RESOLUTION_SECTIONS = {"resolution", "steps", "diagnosis"}

# What each policy is willing to auto-merge.
_POLICY_ALLOWS = {
    "human-review": set(),
    "auto-confirmations": {"confirmation"},
    "auto-additive": {"confirmation", "additive"},
}


def classify(ops: list[PageOp]) -> str:
    category = "confirmation"
    for op in ops:
        if op.op == "create":
            return "structural"
        touched = {s.heading.strip().lower() for s in op.sections}
        if touched & _RESOLUTION_SECTIONS:
            return "structural"
        if op.sections or op.add_relations:
            category = "additive"
    return category


def auto_merge_eligible(policy: str, category: str) -> bool:
    return category in _POLICY_ALLOWS.get(policy, set())
