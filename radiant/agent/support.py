"""The support agent: retrieval -> answer -> citation verification (docs/05).

The Claude call sits behind the `Responder` protocol so the whole orchestration
— scope, context assembly, the verify/bounce-back loop, and honest refusal —
is testable without API credentials. `ClaudeResponder` activates when creds
are configured; a stub Responder drives the tests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from radiant.agent.contract import Answer, no_answer, verify
from radiant.agent.retrieval import Context, ScopedRetriever, render_context
from radiant.settings import AgentConfig, Settings

PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPT_BY_AGENT = {"support": "support.md", "chief-of-staff": "chief.md"}


class Responder(Protocol):
    def respond(self, question: str, ctx: Context, retry_note: str | None) -> Answer: ...


@dataclass
class AnswerResult:
    answer: Answer
    context_pages: list[str]
    verify_problems: list[str]   # problems on the FINAL answer (empty if clean)
    retried: bool


def answer_question(
    retriever: ScopedRetriever,
    responder: Responder,
    settings: Settings,
    question: str,
) -> AnswerResult:
    max_pages = retriever.agent.max_pages or settings.max_pages
    ctx = retriever.assemble(question, max_pages, settings.max_context_chars)

    # No confident retrieval -> honest refusal, no model call.
    if ctx.is_empty or ctx.max_score < settings.score_floor:
        gap = f"No knowledge page matches: {question!r}"
        return AnswerResult(no_answer(gap), [], [], retried=False)

    pages = [p.slug for p in ctx.pages]
    ans = responder.respond(question, ctx, retry_note=None)
    problems = verify(ans, ctx)
    retried = False
    if problems:
        # One bounce-back with the specific problems (docs/05 answer contract).
        retried = True
        note = (
            "Your previous answer failed citation verification: "
            + "; ".join(problems)
            + ". Fix the citations to reference only page#section pairs in the evidence, "
            "or return confidence 'none' if the evidence truly doesn't support an answer."
        )
        ans = responder.respond(question, ctx, retry_note=note)
        problems = verify(ans, ctx)

    if problems:
        # Still unverifiable -> refuse honestly rather than emit a bad citation.
        refusal = no_answer(f"Answer failed citation verification: {'; '.join(problems)}")
        return AnswerResult(refusal, pages, problems, retried)

    return AnswerResult(ans, pages, [], retried)


def make_responder(agent: AgentConfig) -> Responder:
    """The Claude responder for an agent, with its role-specific prompt."""
    return ClaudeResponder(agent)


class ClaudeResponder:
    """Structured-output answers via Claude (docs/05 answer contract). The
    system prompt is selected by agent — support vs. chief-of-staff."""

    def __init__(self, agent: AgentConfig):
        self.model = os.environ.get("RADIANT_ANSWER_MODEL", agent.model)
        self.prompt_path = PROMPTS_DIR / PROMPT_BY_AGENT.get(agent.name, "support.md")

    def respond(self, question: str, ctx: Context, retry_note: str | None) -> Answer:
        from radiant.agent.client import make_client, parse_structured

        client = make_client()
        system = [
            {
                "type": "text",
                "text": self.prompt_path.read_text(encoding="utf-8"),
                "cache_control": {"type": "ephemeral"},
            }
        ]
        user = f"Question: {question}\n\n# Evidence\n\n{render_context(ctx)}"
        if retry_note:
            user += f"\n\n# Correction\n{retry_note}"
        resp = parse_structured(
            client,
            model=self.model,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=Answer,
        )
        if resp.stop_reason == "refusal":
            return no_answer("model declined to answer")
        return resp.parsed_output
