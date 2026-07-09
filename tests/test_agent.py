import sqlite3
from pathlib import Path

import pytest

from radiant import config
from radiant.agent.contract import Answer, Citation, no_answer, verify
from radiant.agent.evals import EvalCase, run_case
from radiant.agent.retrieval import ScopedRetriever, render_context
from radiant.agent.support import Responder, answer_question
from radiant.indexer import build_index
from radiant.settings import load_settings


@pytest.fixture()
def indexed(repo_copy: Path) -> sqlite3.Connection:
    build_index(repo_copy)
    con = sqlite3.connect(config.index_path(repo_copy))
    con.row_factory = sqlite3.Row
    return con


@pytest.fixture()
def settings(repo_copy: Path):
    return load_settings(repo_copy)


@pytest.fixture()
def support_retriever(indexed, settings):
    return ScopedRetriever(indexed, settings.agent("support"))


# --- Canned responders (stand in for the Claude call) ---

class StubResponder(Responder):
    """Returns a fixed answer, or different answers across the bounce-back."""

    def __init__(self, *answers: Answer):
        self.answers = list(answers)
        self.calls = 0

    def respond(self, question, ctx, retry_note):
        ans = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return ans


class GraphCitingResponder(Responder):
    """Cites the first section of every page in context — always valid."""

    def respond(self, question, ctx, retry_note):
        cites = [
            Citation(page=p.slug, section=p.sections[0].heading, status=p.status)
            for p in ctx.pages if p.sections
        ]
        return Answer(
            answer_md="LiDAR timeout; fixed in firmware 2.8. Clean the window.",
            citations=cites,
            confidence="high",
        )


# --- Scope enforcement ---

def test_support_scope_excludes_personal_and_customer(repo_copy, indexed, settings):
    # add a customer page that would otherwise match a query
    cust = repo_copy / "knowledge/customers/acme.md"
    cust.write_text(
        "---\nid: acme\ntype: customer\ntitle: \"Acme — LiDAR fleet\"\naliases: []\n"
        "tags: []\nstatus: active\nrobots_deployed: [scrubber50]\ndistributor: []\n"
        "sources: []\ncreated: 2026-07-07\nupdated: 2026-07-07\n---\n\n"
        "# Acme\n\n## Environment\n\nDusty; lots of lidar issues.\n\n"
        "## Support notes\n\nn/a\n\n## History\n\nn/a\n"
    )
    build_index(repo_copy)
    con = sqlite3.connect(config.index_path(repo_copy))
    con.row_factory = sqlite3.Row

    retriever = ScopedRetriever(con, settings.agent("support"))
    hits = retriever.search("lidar", k=20)
    assert all(h.type != "customer" for h in hits)
    assert "acme" not in {h.slug for h in hits}

    # chief-of-staff has full scope and CAN see it
    cos = ScopedRetriever(con, settings.agent("chief-of-staff"))
    assert "acme" in {h.slug for h in cos.search("lidar", k=20)}


def test_scope_config_allows():
    from radiant.settings import AgentConfig

    support = AgentConfig("support", scope=["error_code", "robot"], deny=["customer"])
    assert support.allows("error_code")
    assert not support.allows("customer")
    assert not support.allows("meeting")
    everything = AgentConfig("cos", scope=["all"])
    assert everything.allows("meeting") and everything.allows("customer")


# --- Context assembly ---

def test_assemble_pulls_sections_and_graph_paths(support_retriever, settings):
    ctx = support_retriever.assemble("E203", settings.max_pages, settings.max_context_chars)
    assert not ctx.is_empty
    assert "error203" in ctx.cited_pages()
    headings = {h for (slug, h) in ctx.valid_citations() if slug == "error203"}
    assert "Root causes" in headings
    # graph expansion recorded an evidence path
    assert any("→" in p for p in ctx.evidence_paths)
    rendered = render_context(ctx)
    assert "[[error203]]" in rendered and "#### Root causes" in rendered


def test_assemble_respects_char_budget(support_retriever):
    ctx = support_retriever.assemble("E203", max_pages=8, max_chars=1)
    assert len(ctx.pages) == 1  # always at least the top hit, then budget stops


# --- Citation verifier ---

def test_verify_accepts_valid_citation(support_retriever, settings):
    ctx = support_retriever.assemble("E203", settings.max_pages, settings.max_context_chars)
    ans = Answer(answer_md="x", confidence="high",
                 citations=[Citation(page="error203", section="Root causes")])
    assert verify(ans, ctx) == []


def test_verify_rejects_unknown_section(support_retriever, settings):
    ctx = support_retriever.assemble("E203", settings.max_pages, settings.max_context_chars)
    ans = Answer(answer_md="x", confidence="high",
                 citations=[Citation(page="error203", section="Nonexistent")])
    assert any("not in the retrieved context" in p for p in verify(ans, ctx))


def test_verify_requires_citation_for_claims(support_retriever, settings):
    ctx = support_retriever.assemble("E203", settings.max_pages, settings.max_context_chars)
    ans = Answer(answer_md="confident but uncited", confidence="high", citations=[])
    assert any("cites nothing" in p for p in verify(ans, ctx))


def test_verify_ignores_citations_on_refusal():
    from radiant.agent.retrieval import Context

    ans = no_answer("nope")
    assert verify(ans, Context("q", [], [], 0.0)) == []


# --- Orchestration: refusal, bounce-back, honest failure ---

def test_refuses_out_of_domain_without_model_call(support_retriever, settings):
    responder = StubResponder(Answer(answer_md="should not be used", confidence="high"))
    result = answer_question(support_retriever, responder, settings, "How do I bake a cake?")
    assert result.answer.confidence == "none"
    assert responder.calls == 0            # no model call when nothing retrieved
    assert result.answer.gaps


def test_good_answer_passes_first_try(support_retriever, settings):
    result = answer_question(support_retriever, GraphCitingResponder(), settings,
                             "Why is Error 203 happening?")
    assert result.answer.confidence == "high"
    assert result.verify_problems == []
    assert not result.retried


def test_bad_citation_triggers_one_bounce_back(support_retriever, settings):
    bad = Answer(answer_md="x", confidence="high",
                 citations=[Citation(page="error203", section="Made Up")])
    good = Answer(answer_md="x", confidence="high",
                  citations=[Citation(page="error203", section="Root causes")])
    responder = StubResponder(bad, good)
    result = answer_question(support_retriever, responder, settings, "why E203?")
    assert responder.calls == 2
    assert result.retried and result.verify_problems == []
    assert result.answer.citations[0].section == "Root causes"


def test_repeated_bad_citations_become_honest_refusal(support_retriever, settings):
    bad = Answer(answer_md="x", confidence="high",
                 citations=[Citation(page="error203", section="Still Wrong")])
    responder = StubResponder(bad, bad)
    result = answer_question(support_retriever, responder, settings, "why E203?")
    assert responder.calls == 2
    assert result.answer.confidence == "none"     # refused rather than emit bad citation
    assert result.verify_problems


# --- Eval harness ---

def test_eval_case_pass_and_fail(support_retriever, settings):
    good = GraphCitingResponder()
    passing = run_case(support_retriever, good, settings,
                       EvalCase(id="q1", question="why E203?", must_cite=["error203"],
                                must_mention=["lidar"]))
    assert passing.passed, passing.reasons

    failing = run_case(support_retriever, good, settings,
                       EvalCase(id="q2", question="why E203?", must_cite=["nonexistent_page"]))
    assert not failing.passed
    assert any("missing required citation" in r for r in failing.reasons)


def test_eval_out_of_domain_expects_refusal(support_retriever, settings):
    responder = StubResponder(Answer(answer_md="cake!", confidence="high"))
    r = run_case(support_retriever, responder, settings,
                 EvalCase(id="q3", question="bake a cake?", expect="no_answer"))
    assert r.passed  # nothing retrieved -> refusal -> matches expectation


def test_answerlog_records_and_lists_unanswered(repo_copy):
    from radiant.agent import answerlog

    answerlog.record(repo_copy, "support", "undocumented?", no_answer("gap"))
    answerlog.record(repo_copy, "support", "answered", Answer(
        answer_md="x", confidence="high",
        citations=[Citation(page="error203", section="Root causes")]))
    unanswered = answerlog.unanswered(repo_copy)
    assert [r["question"] for r in unanswered] == ["undocumented?"]
