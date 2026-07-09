"""Golden-set evaluation for the support agent (docs/05-agents.md).

The eval set is the regression suite for the knowledge base itself: a page
edit that breaks a golden citation fails CI just like a broken unit test.

Metrics (per docs/05):
  - citation validity: cited sections exist & were retrieved (hard gate, 100%)
  - golden citation recall: must_cite pages present (target >= 90%)
  - honest refusal on out-of-domain probes (100%)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from radiant.agent.contract import verify
from radiant.agent.retrieval import ScopedRetriever
from radiant.agent.support import Responder, answer_question
from radiant.settings import Settings


@dataclass
class EvalCase:
    id: str
    question: str
    agent: str = "support"
    must_cite: list[str] = field(default_factory=list)
    must_mention: list[str] = field(default_factory=list)
    expect: str | None = None       # "no_answer" for out-of-domain probes


@dataclass
class CaseResult:
    id: str
    passed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    results: list[CaseResult]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def ok(self) -> bool:
        return self.passed == self.total


def load_cases(path: Path) -> list[EvalCase]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [EvalCase(**c) for c in data]


def run_case(
    retriever: ScopedRetriever, responder: Responder, settings: Settings, case: EvalCase
) -> CaseResult:
    result = answer_question(retriever, responder, settings, case.question)
    ans = result.answer
    reasons: list[str] = []

    # Citation validity is a hard gate for every case.
    ctx = retriever.assemble(case.question, settings.max_pages, settings.max_context_chars)
    if verify(ans, ctx):
        reasons.append("citation validity failed")

    if case.expect == "no_answer":
        if ans.confidence != "none":
            reasons.append(f"expected refusal, got confidence {ans.confidence!r}")
        return CaseResult(case.id, not reasons, reasons)

    if ans.confidence == "none":
        reasons.append("agent refused an in-domain question")
    cited = {c.page for c in ans.citations}
    for page in case.must_cite:
        if page not in cited:
            reasons.append(f"missing required citation: {page}")
    low = ans.answer_md.lower()
    for term in case.must_mention:
        if term.lower() not in low:
            reasons.append(f"answer missing term: {term!r}")
    return CaseResult(case.id, not reasons, reasons)


def run_all(
    retriever: ScopedRetriever, responder: Responder, settings: Settings, cases: list[EvalCase]
) -> EvalReport:
    return EvalReport([run_case(retriever, responder, settings, c) for c in cases])
