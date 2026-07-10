from pathlib import Path

from radiant import lint, notes, review


def errors(issues):
    return [i for i in issues if i.severity == "error"]


def test_recurring_theme_detects_cross_investor(repo_copy):
    # "scaling" is raised by two different investors + a meeting
    body, referenced = review.build_review(repo_copy)
    assert "## Recurring themes" in body
    assert "**scaling**" in body                      # the recurring VC concern
    assert {"example_ventures", "northwind_capital"} <= set(referenced)


def test_scaling_theme_spans_three_pages(repo_copy):
    body, _ = review.build_review(repo_copy)
    themes = review.recurring_themes(
        review.digest.collate(repo_copy, "investor", "Concerns raised").entries
        + review.digest.collate(repo_copy, "meeting", "Concerns raised").entries
    )
    scaling = next(t for t in themes if t.token == "scaling")
    assert len(scaling.pages) == 3                    # 2 investors + 1 meeting
    assert themes[0].token == "scaling"               # ranks first


def test_review_includes_competitor_moves(repo_copy):
    body, _ = review.build_review(repo_copy)
    assert "## Competitor moves" in body
    assert "aggressive pricing" in body
    assert "acme_robotics" in body


def test_since_filters_dated_entries(repo_copy):
    body, _ = review.build_review(repo_copy, since="2026-06-01")
    # the 2026-05-10 acme intel entry is filtered out; 2026-06-20 stays
    assert "aggressive pricing" in body
    assert "Hiring an AI support lead" not in body


def test_recurring_themes_needs_two_pages(repo_copy):
    from radiant.digest import Entry

    one = [Entry("p1", "P1", "unique concern about pricing", "2026-07-01")]
    assert review.recurring_themes(one) == []
    two = [Entry("p1", "P1", "pricing worry", "2026-07-01"),
           Entry("p2", "P2", "pricing pressure", "2026-07-02")]
    themes = review.recurring_themes(two)
    assert any(t.token == "pricing" and t.pages == ["p1", "p2"] for t in themes)


def test_write_review_creates_lint_clean_research_page(repo_copy):
    dest = review.write_review(repo_copy, on="2026-07-10")
    assert dest.name == "2026-07-10-review.md"
    text = dest.read_text()
    assert "# Personal review — 2026-07-10" in text
    # links to source pages must resolve -> repo still lints clean
    assert errors(lint.run(repo_copy)) == []


def test_review_reflects_new_captures(repo_copy):
    notes.add_note(repo_copy, "competitor", "brightbot",
                   "Cut prices 20% to chase our segment", on="2026-07-09")
    body, _ = review.build_review(repo_copy)
    assert "Cut prices 20%" in body
    assert "brightbot" in body
