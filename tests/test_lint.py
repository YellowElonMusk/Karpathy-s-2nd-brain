from pathlib import Path

from radiant import lint
from radiant.newpage import create


def errors(issues):
    return [i for i in issues if i.severity == "error"]


def test_repo_lints_clean(real_root: Path):
    issues = lint.run(real_root)
    assert issues == [], [str(i) for i in issues]


def test_broken_wikilink_is_error(repo_copy: Path):
    page = repo_copy / "knowledge/error_codes/error203.md"
    page.write_text(page.read_text() + "\nSee [[no_such_page]].\n")
    msgs = [i.message for i in errors(lint.run(repo_copy))]
    assert any("no_such_page" in m for m in msgs)


def test_broken_link_on_draft_is_warning(repo_copy: Path):
    page = repo_copy / "knowledge/error_codes/error203.md"
    text = page.read_text().replace("status: active", "status: draft")
    page.write_text(text + "\nSee [[no_such_page]].\n")
    issues = [i for i in lint.run(repo_copy) if "no_such_page" in i.message]
    assert issues and all(i.severity == "warning" for i in issues)


def test_unknown_citation_marker_is_error(repo_copy: Path):
    page = repo_copy / "knowledge/firmware/v2_8.md"
    page.write_text(page.read_text() + "\nUndeclared claim [S9].\n")
    msgs = [i.message for i in errors(lint.run(repo_copy))]
    assert any("[S9]" in m for m in msgs)


def test_unused_source_is_warning(repo_copy: Path):
    page = repo_copy / "knowledge/firmware/v2_8.md"
    page.write_text(page.read_text().replace("[S1]", ""))
    issues = [i for i in lint.run(repo_copy) if "never cited" in i.message]
    assert issues and all(i.severity == "warning" for i in issues)


def test_duplicate_alias_is_error(repo_copy: Path):
    page = repo_copy / "knowledge/firmware/v2_8.md"
    page.write_text(page.read_text().replace('aliases: ["v2.8", "2.8"]', 'aliases: ["v2.8", "E203"]'))
    msgs = [i.message for i in errors(lint.run(repo_copy))]
    assert any("ambiguous alias" in m for m in msgs)


def test_wrong_folder_is_error(repo_copy: Path):
    src = repo_copy / "knowledge/firmware/v2_8.md"
    dst = repo_copy / "knowledge/robots/v2_8.md"
    dst.write_text(src.read_text())
    src.unlink()
    msgs = [i.message for i in errors(lint.run(repo_copy))]
    assert any("belongs in knowledge/firmware/" in m for m in msgs)


def test_unresolved_relation_is_error_even_on_draft(repo_copy: Path):
    page = repo_copy / "knowledge/error_codes/error203.md"
    text = page.read_text().replace("status: active", "status: draft")
    page.write_text(text.replace("fixed_in: [v2_8]", "fixed_in: [v9_9]"))
    issues = [i for i in lint.run(repo_copy) if "v9_9" in i.message]
    assert issues and all(i.severity == "error" for i in issues)


def test_missing_sources_on_active_technical_page(repo_copy: Path):
    page = repo_copy / "knowledge/procedures/lidar_cleaning.md"
    text = page.read_text()
    text = text.replace(
        "sources:\n  - id: S1\n    doc: sources/manuals/scrubber50-service-manual-2024.pdf\n    locator: \"p. 41\"",
        "sources: []",
    )
    page.write_text(text.replace(" [S1]", ""))
    issues = [i for i in lint.run(repo_copy) if "no sources" in i.message]
    assert issues and issues[0].severity == "error"


def test_new_page_has_no_lint_errors(repo_copy: Path):
    create(repo_copy, "error_code", "error502", title="Error 502 — Test")
    assert errors(lint.run(repo_copy)) == []
    # template placeholder links downgrade to warnings on the draft page
    assert any(i.severity == "warning" for i in lint.run(repo_copy))


def test_new_page_rejects_bad_type_and_duplicate(repo_copy: Path):
    import pytest

    with pytest.raises(ValueError, match="unknown page type"):
        create(repo_copy, "gizmo", "g1")
    with pytest.raises(ValueError, match="already exists"):
        create(repo_copy, "error_code", "error203")
