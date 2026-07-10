import sqlite3
from pathlib import Path

import pytest

from radiant import digest, lint, notes
from radiant.frontmatter import split_page
from radiant.indexer import build_index


def errors(issues):
    return [i for i in issues if i.severity == "error"]


# --- quick capture (radiant note) ---

def test_note_appends_to_existing_investor_concerns(repo_copy):
    dest, created = notes.add_note(
        repo_copy, "investor", "example_ventures",
        "Pushed again on CAC scaling", section="Concerns raised", on="2026-07-09")
    assert not created
    fm, body = split_page(dest.read_text())
    assert "2026-07-09 — Pushed again on CAC scaling" in body
    # existing content preserved
    assert "hard to scale without owning the fleet" in body
    assert fm["updated"] == "2026-07-09"
    assert errors(lint.run(repo_copy)) == []


def test_note_creates_page_from_template(repo_copy):
    dest, created = notes.add_note(
        repo_copy, "competitor", "brightbot",
        "Announced a $200 price cut", on="2026-07-08")
    assert created and dest.name == "brightbot.md"
    fm, body = split_page(dest.read_text())
    assert fm["type"] == "competitor" and fm["title"] == "Brightbot"
    # default section for competitor is the Intel log
    assert "## Intel log" in body
    assert "2026-07-08 — Announced a $200 price cut" in body
    assert errors(lint.run(repo_copy)) == []


def test_note_meeting_gets_date_prefix(repo_copy):
    dest, created = notes.add_note(
        repo_copy, "meeting", "sequoia-partner-call", "They liked the deflection metric",
        on="2026-07-10")
    assert dest.name == "2026-07-10-sequoia-partner-call.md"
    assert "2026-07-10 — They liked the deflection metric" in dest.read_text()


def test_note_rejects_unknown_type(repo_copy):
    with pytest.raises(ValueError, match="unknown page type"):
        notes.add_note(repo_copy, "gizmo", "x", "y")


# --- digest / monitoring ---

def test_digest_concerns_preset(repo_copy):
    # add a second, echoing concern via capture, then collate
    notes.add_note(repo_copy, "investor", "example_ventures",
                   "Still worried about scaling support headcount",
                   section="Concerns raised", on="2026-07-09")
    d = digest.collate(repo_copy, "investor", "Concerns raised")
    texts = [e.text for e in d.entries]
    assert any("scale without owning the fleet" in t for t in texts)
    assert any("scaling support headcount" in t for t in texts)
    assert all(e.when for e in d.entries)          # all dated


def test_digest_competitors_and_timeline(repo_copy):
    ptype, section = digest.PRESETS["competitors"]
    d = digest.collate(repo_copy, ptype, section)
    assert any("aggressive pricing" in e.text for e in d.entries)
    chron = d.chronological()
    assert [e.when for e in chron] == sorted((e.when for e in chron), reverse=True)


def test_digest_ignores_placeholder_bullets(repo_copy):
    # a fresh meeting's Action items has the "owner — action" placeholder
    notes.add_note(repo_copy, "meeting", "board-sync", "note", on="2026-07-10")
    d = digest.collate(repo_copy, "meeting", "Action items")
    assert all("owner" not in e.text.lower() for e in d.entries)


def test_digest_empty_for_unused_section(repo_copy):
    d = digest.collate(repo_copy, "idea", "Status & next step")
    assert d.entries == []


# --- chief-of-staff agent wiring ---

def test_chief_has_full_scope_and_bigger_budget(repo_copy):
    from radiant.settings import load_settings

    s = load_settings(repo_copy)
    chief = s.agent("chief-of-staff")
    assert chief.allows("investor") and chief.allows("meeting") and chief.allows("customer")
    assert chief.max_pages == 16
    # support still can't see personal pages
    assert not s.agent("support").allows("investor")


def test_chief_responder_uses_chief_prompt(repo_copy):
    from radiant.agent import support
    from radiant.settings import load_settings

    chief = support.make_responder(load_settings(repo_copy).agent("chief-of-staff"))
    assert chief.prompt_path.name == "chief.md"
    sup = support.make_responder(load_settings(repo_copy).agent("support"))
    assert sup.prompt_path.name == "support.md"


def test_chief_retrieval_reaches_personal_pages(repo_copy):
    from radiant.agent.retrieval import ScopedRetriever
    from radiant.settings import load_settings

    build_index(repo_copy)
    con = sqlite3.connect(str((repo_copy / "build" / "index.db")))
    con.row_factory = sqlite3.Row
    s = load_settings(repo_copy)
    chief = ScopedRetriever(con, s.agent("chief-of-staff"))
    ctx = chief.assemble("investor concerns about scaling", chief.agent.max_pages, s.max_context_chars)
    assert "example_ventures" in ctx.cited_pages()
    # support agent, same query, cannot reach the investor page
    support_r = ScopedRetriever(con, s.agent("support"))
    sctx = support_r.assemble("investor concerns about scaling", s.max_pages, s.max_context_chars)
    assert "example_ventures" not in sctx.cited_pages()
