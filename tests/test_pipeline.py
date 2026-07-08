from pathlib import Path

import pytest

from radiant import lint
from radiant.frontmatter import split_page
from radiant.kb import load_kb
from radiant.pipeline.apply import apply_plan
from radiant.pipeline.ops import IngestPlan, load_plan
from radiant.pipeline.reconcile import reconcile
from radiant.pipeline.runner import ingest

PLAN_YAML = """\
ops:
  - op: create
    slug: error502
    type: error_code
    title: "Error 502 — Brush Motor Stall"
    reason: "New error documented in bulletin 17"
    add_aliases: ["E502"]
    add_sources:
      - doc: sources/bulletins/bulletin-17.md
        locator: "§ Fix"
    add_relations:
      - rel: affects_robots
        targets: [scrubber50]
    sections:
      - heading: _intro
        content: "Brush motor stall under heavy debris load [SRC:1]."
      - heading: Symptoms
        content: "Robot halts with E502 on the display [SRC:1]."
  - op: update
    slug: E203
    reason: "Bulletin adds a root cause"
    add_sources:
      - doc: sources/bulletins/bulletin-17.md
        locator: "§ Affected units"
    sections:
      - heading: Root causes
        content: |
          1. Dust film on the LiDAR window [SRC:1].
          2. Aggressive timeout in firmware v2.6-v2.7 [SRC:1].
          3. Loose sensor-mast connector after transport [SRC:1].
"""


@pytest.fixture()
def plan_file(tmp_path: Path) -> Path:
    p = tmp_path / "plan.yaml"
    p.write_text(PLAN_YAML)
    return p


@pytest.fixture()
def bulletin(repo_copy: Path) -> Path:
    src = repo_copy / "sources/bulletins/bulletin-17.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("# Bulletin 17\n\n## Affected units\n\nv2.6-v2.7\n\n## Fix\n\nUpgrade.\n")
    return src


def errors(issues):
    return [i for i in issues if i.severity == "error"]


def test_load_plan_and_alias_field(plan_file):
    plan = load_plan(plan_file)
    assert plan.ops[0].page_type == "error_code"  # YAML key "type"
    assert plan.ops[1].op == "update"


def test_reconcile_converts_existing_create_to_update(repo_copy, plan_file):
    kb = load_kb(repo_copy)
    plan = load_plan(plan_file)
    plan.ops[0].slug = "error203"  # collides with existing page
    ops, notes = reconcile(kb, plan.ops)
    converted = next(o for o in ops if o.slug == "error203" and "Brush" not in (o.title or ""))
    assert all(o.op == "update" for o in ops if o.slug == "error203")
    assert any("already exists" in n for n in notes)
    assert converted.page_type is None


def test_reconcile_fuzzy_title_match(repo_copy, plan_file):
    kb = load_kb(repo_copy)
    plan = load_plan(plan_file)
    plan.ops[0].slug = "nav_lidar_timeout_error"
    plan.ops[0].title = "Error 203 — Navigation LiDAR timeout"
    ops, notes = reconcile(kb, plan.ops)
    assert {o.slug for o in ops} == {"error203"}


def test_reconcile_resolves_update_alias_and_rejects_unknown(repo_copy, plan_file):
    kb = load_kb(repo_copy)
    plan = load_plan(plan_file)
    ops, _ = reconcile(kb, plan.ops)
    assert ops[1].slug == "error203"  # E203 alias resolved
    plan.ops[1].slug = "does_not_exist"
    with pytest.raises(ValueError, match="unknown page"):
        reconcile(kb, plan.ops)


def test_reconcile_merges_duplicate_ops(repo_copy, plan_file):
    kb = load_kb(repo_copy)
    plan = load_plan(plan_file)
    dup = plan.ops[1].model_copy(deep=True)
    dup.sections[0].heading = "History"
    ops, notes = reconcile(kb, plan.ops + [dup])
    assert len([o for o in ops if o.slug == "error203"]) == 1
    merged = next(o for o in ops if o.slug == "error203")
    assert {s.heading for s in merged.sections} == {"Root causes", "History"}
    assert len(merged.add_sources) == 1  # deduped by (doc, locator)


def test_apply_create_and_update(repo_copy, plan_file, bulletin):
    kb = load_kb(repo_copy)
    ops, _ = reconcile(kb, load_plan(plan_file).ops)
    changed = apply_plan(repo_copy, kb, ops)
    assert len(changed) == 2

    new_page = repo_copy / "knowledge/error_codes/error502.md"
    fm, body = split_page(new_page.read_text())
    assert fm["status"] == "draft"
    assert fm["affects_robots"] == ["scrubber50"]
    assert fm["sources"][0]["id"] == "S1"
    assert "[S1]" in body and "[SRC:" not in body

    fm2, body2 = split_page((repo_copy / "knowledge/error_codes/error203.md").read_text())
    # error203 already had S1+S2 — the new source gets S3, appended
    assert [s["id"] for s in fm2["sources"]] == ["S1", "S2", "S3"]
    assert "Loose sensor-mast connector" in body2 and "[S3]" in body2
    assert body2.count("## Root causes") == 1
    # untouched sections survive
    assert "## Diagnosis" in body2

    assert errors(lint.run(repo_copy)) == []


def test_apply_rejects_bad_relation_and_bad_placeholder(repo_copy, plan_file):
    kb = load_kb(repo_copy)
    plan = load_plan(plan_file)
    plan.ops[0].add_relations[0].rel = "fixes"  # not valid for error_code
    with pytest.raises(ValueError, match="not valid"):
        apply_plan(repo_copy, kb, plan.ops)

    plan = load_plan(plan_file)
    plan.ops[0].sections[0].content = "Cites nothing real [SRC:9]."
    ops = [plan.ops[0]]
    with pytest.raises(ValueError, match="SRC:9"):
        apply_plan(repo_copy, kb, ops)


def test_runner_end_to_end_with_plan(repo_copy, plan_file, bulletin):
    result = ingest(repo_copy, str(bulletin), plan_file=plan_file)
    assert result.status == "done"
    assert "knowledge/error_codes/error502.md" in result.pages
    # idempotency: same content hash is skipped without --force
    again = ingest(repo_copy, str(bulletin), plan_file=plan_file)
    assert again.status == "skipped"


def test_runner_dry_run_changes_nothing(repo_copy, plan_file, bulletin):
    result = ingest(repo_copy, str(bulletin), plan_file=plan_file, dry_run=True)
    assert result.status == "dry-run"
    assert "error502" in result.plan_yaml
    assert not (repo_copy / "knowledge/error_codes/error502.md").exists()


def test_runner_archives_outside_sources(repo_copy, plan_file, tmp_path):
    outside = tmp_path / "downloads" / "bulletin-17.md"
    outside.parent.mkdir()
    outside.write_text("# Bulletin 17\n\nUpgrade to v2.8.\n")
    result = ingest(repo_copy, str(outside), plan_file=plan_file)
    assert (repo_copy / "sources/exports/bulletin-17.md").exists()
    assert result.status == "done"


def test_runner_lint_gate(repo_copy, bulletin, tmp_path):
    bad_plan = tmp_path / "bad.yaml"
    bad_plan.write_text(
        "ops:\n"
        "  - op: update\n"
        "    slug: error203\n"
        "    sections:\n"
        "      - heading: Resolution\n"
        "        content: 'See [[no_such_page]] for details.'\n"
    )
    result = ingest(repo_copy, str(bulletin), plan_file=bad_plan)
    assert result.status == "lint_failed"
    assert any("no_such_page" in e for e in result.lint_errors)


def test_extractor_context_pack(repo_copy):
    from radiant.pipeline.extractor import build_context_pack

    pack = build_context_pack(load_kb(repo_copy))
    assert "error203 (error_code)" in pack
    assert "error_code: affects_robots" in pack
    assert "Symptoms" in pack


def test_empty_plan_reports_empty(repo_copy, bulletin, tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("ops: []\n")
    result = ingest(repo_copy, str(bulletin), plan_file=empty)
    assert result.status == "empty"
