"""Curator housekeeping (docs/05-agents.md).

Phase 4 scope: the unanswered-question backlog. Every time the support agent
refuses (confidence 'none'), the question is logged; the curator surfaces those
as documentation gaps so the KB's blind spots are visible and actionable.

Turning a backlog entry into a typed stub page is a judgment call that belongs
to the curator *agent* (Phase 6) — this module produces the backlog it works
from.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from radiant.agent import answerlog


@dataclass
class Gap:
    question: str
    asked_at: str


def backlog(root: Path) -> list[Gap]:
    """Documentation gaps: questions the agent couldn't answer, newest first,
    de-duplicated."""
    seen: set[str] = set()
    gaps: list[Gap] = []
    for row in answerlog.unanswered(root):
        q = row["question"].strip()
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        gaps.append(Gap(question=q, asked_at=row["asked_at"]))
    return gaps
