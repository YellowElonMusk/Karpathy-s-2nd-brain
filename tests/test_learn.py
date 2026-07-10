from pathlib import Path

import pytest

from radiant import lint, tickets
from radiant.agent import answerlog, curator
from radiant.agent.contract import Answer, Citation, no_answer
from radiant.frontmatter import split_page
from radiant.kb import load_kb
from radiant.pipeline import policy
from radiant.pipeline.learn import LearnExtractor, learn
from radiant.pipeline.ops import IngestPlan, PageOp, Relation, Section, SourceRef

TICKET_YAML = """\
external_ref: ZD-1042
robot: scrubber50
error_slugs: [error203]
channel: whatsapp
status: closed
summary: "Recurring E203 at a dusty warehouse"
resolution: "Dust film on the lidar window; cleaning resolved it, no parts."
messages:
  - author: customer
    sent_at: 2026-06-13T14:22:00Z
    body: "SN-4411 keeps stopping with E203, several times a shift"
  - author: support
    sent_at: 2026-06-13T14:30:00Z
    body: "Telemetry shows gradual frame-gap growth — that's occlusion, not a bad unit. Clean the lidar window."
  - author: customer
    sent_at: 2026-06-13T15:10:00Z
    body: "Cleaned it, no more E203 all afternoon."
"""


def errors(issues):
    return [i for i in issues if i.severity == "error"]


@pytest.fixture()
def ticket_id(repo_copy: Path) -> int:
    f = repo_copy / "ticket.yaml"
    f.write_text(TICKET_YAML)
    return tickets.import_file(repo_copy, f)[0]


# --- ticket store ---

def test_import_and_read_ticket(repo_copy, ticket_id):
    t = tickets.get_ticket(repo_copy, ticket_id)
    assert t.status == "closed"
    assert t.robot_slug == "scrubber50"
    assert t.error_slugs == ["error203"]
    assert len(t.messages) == 3
    assert t.closed_at is not None
    thread = t.thread_text()
    assert "Error codes observed: error203" in thread
    assert "gradual frame-gap growth" in thread


def test_list_and_status_filter(repo_copy, ticket_id):
    assert len(tickets.list_tickets(repo_copy, status="closed")) == 1
    assert tickets.list_tickets(repo_copy, learn_status="applied") == []


# --- merge policy engine ---

def test_policy_classify():
    confirm = [PageOp(op="update", slug="error203",
                      add_sources=[SourceRef(doc="ticket:1")])]
    assert policy.classify(confirm) == "confirmation"

    additive = [PageOp(op="update", slug="error203",
                       sections=[Section(heading="History", content="note [SRC:1]")],
                       add_sources=[SourceRef(doc="ticket:1")])]
    assert policy.classify(additive) == "additive"

    risky = [PageOp(op="update", slug="error203",
                    sections=[Section(heading="Resolution", content="new step [SRC:1]")],
                    add_sources=[SourceRef(doc="ticket:1")])]
    assert policy.classify(risky) == "structural"

    creating = [PageOp(op="create", slug="new_proc", type="procedure", title="X")]
    assert policy.classify(creating) == "structural"


def test_policy_eligibility():
    assert not policy.auto_merge_eligible("human-review", "confirmation")
    assert policy.auto_merge_eligible("auto-confirmations", "confirmation")
    assert not policy.auto_merge_eligible("auto-confirmations", "additive")
    assert policy.auto_merge_eligible("auto-additive", "additive")
    assert not policy.auto_merge_eligible("auto-additive", "structural")


# --- learn runner (stub extractor) ---

class StubLearn(LearnExtractor):
    def __init__(self, plan: IngestPlan):
        self.plan = plan

    def extract(self, ticket, kb) -> IngestPlan:
        return self.plan


def _variant_plan(tid: int) -> IngestPlan:
    return IngestPlan(ops=[
        PageOp(
            op="update", slug="error203",
            reason="ticket confirms a new root cause",
            add_sources=[SourceRef(doc=f"ticket:{tid}")],
            sections=[Section(
                heading="History",
                content=f"Confirmed dust-film occlusion in the field; gradual frame-gap "
                        f"growth distinguishes it from hardware failure [SRC:1].")],
        )
    ])


def test_learn_applies_and_updates_status(repo_copy, ticket_id):
    result = learn(repo_copy, ticket_id, extractor=StubLearn(_variant_plan(ticket_id)))
    assert result.status == "done"
    assert "knowledge/error_codes/error203.md" in result.pages
    assert result.merge_category == "additive"
    assert result.auto_merge_eligible is False        # default policy: human-review

    fm, body = split_page((repo_copy / "knowledge/error_codes/error203.md").read_text())
    assert "frame-gap growth" in body
    # ticket-derived source recorded with a ticket: doc ref
    assert any(str(s["doc"]) == f"ticket:{ticket_id}" for s in fm["sources"])
    assert errors(lint.run(repo_copy)) == []

    t = tickets.get_ticket(repo_copy, ticket_id)
    assert t.learn_status == "applied"


def test_learn_dry_run_changes_nothing(repo_copy, ticket_id):
    result = learn(repo_copy, ticket_id, dry_run=True, extractor=StubLearn(_variant_plan(ticket_id)))
    assert result.status == "dry-run"
    assert "error203" in result.plan_yaml
    assert tickets.get_ticket(repo_copy, ticket_id).learn_status == "pending"


def test_learn_empty_plan_marks_skipped(repo_copy, ticket_id):
    result = learn(repo_copy, ticket_id, extractor=StubLearn(IngestPlan(ops=[])))
    assert result.status == "empty"
    assert tickets.get_ticket(repo_copy, ticket_id).learn_status == "skipped"


def test_learn_refuses_open_ticket(repo_copy):
    tid = tickets.add_ticket(repo_copy, {"status": "open", "robot_slug": "scrubber50"})
    with pytest.raises(SystemExit, match="only closed tickets"):
        learn(repo_copy, tid, extractor=StubLearn(_variant_plan(tid)))


def test_learn_via_plan_file(repo_copy, ticket_id, tmp_path):
    plan = tmp_path / "plan.yaml"
    plan.write_text(
        "ops:\n"
        "  - op: update\n"
        "    slug: error203\n"
        f"    add_sources:\n      - doc: 'ticket:{ticket_id}'\n        locator: ''\n"
        "    sections:\n"
        "      - heading: History\n"
        "        content: 'Field-confirmed via a distributor ticket [SRC:1].'\n"
    )
    result = learn(repo_copy, ticket_id, plan_file=plan)
    assert result.status == "done"
    assert result.merge_category == "additive"


def test_learn_lint_gate(repo_copy, ticket_id):
    bad = IngestPlan(ops=[PageOp(
        op="update", slug="error203",
        sections=[Section(heading="History", content="See [[ghost_page]].")],
    )])
    result = learn(repo_copy, ticket_id, extractor=StubLearn(bad))
    assert result.status == "lint_failed"
    assert any("ghost_page" in e for e in result.lint_errors)
    assert tickets.get_ticket(repo_copy, ticket_id).learn_status == "lint_failed"


# --- the whole-system loop: ticket -> better page -> answerable ---

def test_learn_creates_new_procedure_and_relation(repo_copy, ticket_id):
    plan = IngestPlan(ops=[
        PageOp(op="create", slug="sensor_mast_reseat", type="procedure",
               title="Sensor Mast Connector Reseat",
               add_sources=[SourceRef(doc=f"ticket:{ticket_id}")],
               add_relations=[Relation(rel="resolves", targets=["error203"]),
                              Relation(rel="applies_to", targets=["scrubber50"])],
               sections=[
                   Section(heading="_intro", content="Reseat the sensor-mast connector [SRC:1]."),
                   Section(heading="Prerequisites", content="Powered off [SRC:1]."),
                   Section(heading="Steps", content="1. Open the mast. 2. Reseat. [SRC:1]"),
                   Section(heading="Verification", content="No E203 on a test route [SRC:1]."),
                   Section(heading="Troubleshooting", content="Persists → escalate [SRC:1]."),
               ]),
    ])
    result = learn(repo_copy, ticket_id, extractor=StubLearn(plan))
    assert result.status == "done"
    assert result.merge_category == "structural"
    assert errors(lint.run(repo_copy)) == []

    # the new page is discoverable via the graph after reindex
    from radiant.indexer import build_index
    from radiant import config as cfg
    import sqlite3

    build_index(repo_copy)
    con = sqlite3.connect(cfg.index_path(repo_copy))
    edges = {tuple(r) for r in con.execute("SELECT src, rel, dst FROM edges")}
    assert ("sensor_mast_reseat", "resolves", "error203") in edges


# --- curator backlog ---

def test_curator_backlog_lists_unanswered(repo_copy):
    answerlog.record(repo_copy, "support", "torque spec for scrubber 75?", no_answer("gap"))
    answerlog.record(repo_copy, "support", "torque spec for scrubber 75?", no_answer("gap"))  # dup
    answerlog.record(repo_copy, "support", "why E203?", Answer(
        answer_md="x", confidence="high",
        citations=[Citation(page="error203", section="Root causes")]))
    gaps = curator.backlog(repo_copy)
    assert [g.question for g in gaps] == ["torque spec for scrubber 75?"]  # deduped, answered excluded
