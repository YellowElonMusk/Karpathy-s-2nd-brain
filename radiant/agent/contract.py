"""The answer contract and its citation verifier (docs/05-agents.md).

Every factual claim maps to a citation; the verifier rejects any citation
that names a page#section not present in the retrieved context. This is what
makes "every answer is traceable back to documented evidence" enforceable
rather than aspirational.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from radiant.agent.retrieval import Context


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: str      # slug
    section: str   # heading exactly as it appears on the page
    status: Literal["active", "draft", "deprecated"] = "active"


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_md: str
    citations: list[Citation] = Field(default_factory=list)
    evidence_chain: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low", "none"] = "none"
    gaps: list[str] = Field(default_factory=list)


NO_ANSWER = "The knowledge base doesn't cover this yet."


def no_answer(gap: str | None = None) -> Answer:
    return Answer(
        answer_md=NO_ANSWER,
        confidence="none",
        gaps=[gap] if gap else [],
    )


class VerificationError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def verify(answer: Answer, ctx: Context) -> list[str]:
    """Return a list of problems; empty means the answer is citation-valid.

    Checks, per docs/05:
      - every cited page#section exists in the retrieved context
      - a non-refusal answer carries at least one citation
      - cited status matches the page's real status
    """
    problems: list[str] = []
    valid = ctx.valid_citations()
    by_slug = {p.slug: p for p in ctx.pages}

    if answer.confidence != "none":
        if not answer.citations:
            problems.append("answer makes claims but cites nothing")
        for c in answer.citations:
            if (c.page, c.section) not in valid:
                problems.append(
                    f"citation [[{c.page}#{c.section}]] is not in the retrieved context"
                )
            elif by_slug[c.page].status != c.status:
                problems.append(
                    f"citation {c.page!r} claims status {c.status!r} "
                    f"but the page is {by_slug[c.page].status!r}"
                )
    return problems


def format_answer(answer: Answer) -> str:
    """Human-readable rendering for the CLI."""
    lines = [answer.answer_md.rstrip()]
    if answer.citations:
        lines.append("\nSources:")
        for c in answer.citations:
            tag = "" if c.status == "active" else f" ({c.status})"
            lines.append(f"  - [[{c.page}#{c.section}]]{tag}")
    if answer.evidence_chain:
        lines.append("\nEvidence:")
        lines += [f"  - {e}" for e in answer.evidence_chain]
    if answer.gaps:
        lines.append("\nGaps:")
        lines += [f"  - {g}" for g in answer.gaps]
    lines.append(f"\nconfidence: {answer.confidence}")
    return "\n".join(lines)
