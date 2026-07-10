from pathlib import Path

import pytest

from radiant import dashboard, integrity, opsviews, tickets
from radiant.agent import answerlog
from radiant.agent.contract import Answer, Citation, no_answer
from radiant.indexer import build_index
from radiant.pipeline.learn import LearnExtractor, learn_pending
from radiant.pipeline.ops import IngestPlan, PageOp, Section, SourceRef


@pytest.fixture()
def indexed_repo(repo_copy: Path) -> Path:
    build_index(repo_copy)
    return repo_copy


@pytest.fixture()
def seeded(indexed_repo: Path) -> Path:
    tickets.add_ticket(indexed_repo, {
        "robot": "scrubber50", "distributor_slug": "distributor_a",
        "error_slugs": ["error203"], "status": "closed",
        "resolution": "Cleaned the lidar window; resolved.",
    })
    tickets.add_ticket(indexed_repo, {
        "robot": "scrubber50", "error_slugs": ["error203"], "status": "closed",
        "resolution": "Upgraded to v2.8.",
    })
    tickets.add_ticket(indexed_repo, {"error_slugs": ["error203"], "status": "open"})
    answerlog.record(indexed_repo, "support", "why E203?", Answer(
        answer_md="x", confidence="high",
        citations=[Citation(page="error203", section="Root causes")]))
    answerlog.record(indexed_repo, "support", "torque for scrubber 75?", no_answer("gap"))
    return indexed_repo


# --- operational views ---

def test_error_resolutions(seeded):
    res = opsviews.error_resolutions(seeded, "error203")
    assert len(res) == 2
    assert any("lidar window" in r.resolution for r in res)
    assert any(r.distributor == "distributor_a" for r in res)


def test_error_frequency_and_volume(seeded):
    assert opsviews.error_frequency(seeded)["error203"] == 3
    vol = opsviews.ticket_volume(seeded)
    assert vol == {"closed": 2, "open": 1}


def test_answer_quality(seeded):
    q = opsviews.answer_quality(seeded)
    assert q.total == 2
    assert q.by_confidence == {"high": 1, "none": 1}
    assert q.answered_rate == 0.5


def test_views_empty_without_stores(indexed_repo):
    assert opsviews.error_frequency(indexed_repo) == {}
    assert opsviews.answer_quality(indexed_repo).total == 0


# --- slug integrity ---

def test_doctor_clean(seeded):
    assert integrity.check_slugs(seeded) == []


def test_doctor_flags_dangling(indexed_repo):
    tickets.add_ticket(indexed_repo, {
        "robot": "scrubber50", "error_slugs": ["error999"], "status": "closed",
        "resolution": "x",
    })
    dangling = integrity.check_slugs(indexed_repo)
    assert len(dangling) == 1
    assert dangling[0].slug == "error999"
    assert "error_slugs" in dangling[0].source


def test_doctor_requires_index(repo_copy):
    with pytest.raises(SystemExit, match="no index"):
        integrity.check_slugs(repo_copy)


# --- batch learn poller ---

class StubLearn(LearnExtractor):
    def extract(self, ticket, kb) -> IngestPlan:
        return IngestPlan(ops=[PageOp(
            op="update", slug="error203",
            add_sources=[SourceRef(doc=f"ticket:{ticket.id}")],
            sections=[Section(heading="History",
                              content=f"Confirmed by ticket {ticket.id} [SRC:1].")],
        )])


def test_learn_pending_processes_only_closed_pending(seeded):
    results = learn_pending(seeded, extractor=StubLearn())
    # 2 closed tickets in the seed (the open one is skipped)
    assert len(results) == 2
    assert all(r.status in ("done", "empty") for r in results)
    # no closed ticket is pending anymore; the open one is untouched
    assert tickets.list_tickets(seeded, status="closed", learn_status="pending") == []
    assert len(tickets.list_tickets(seeded, status="open", learn_status="pending")) == 1


# --- dashboard ---

def test_dashboard_generates_valid_html(seeded):
    html = dashboard.generate(seeded)
    assert html.startswith("<!doctype html>")
    assert "RadiantBrain" in html
    assert "error203" in html                    # KB browser lists pages
    assert "Error frequency" in html
    assert "Answer quality" in html
    assert "torque for scrubber 75?" in html     # documentation gap surfaced
    # self-contained: no external asset references
    assert "http://" not in html and "https://" not in html
    assert "<script" not in html


def test_dashboard_write(seeded, tmp_path):
    out = dashboard.write(seeded, tmp_path / "dash.html")
    assert out.exists() and out.read_text().startswith("<!doctype html>")


def test_dashboard_requires_index(repo_copy):
    with pytest.raises(SystemExit, match="no index"):
        dashboard.generate(repo_copy)
