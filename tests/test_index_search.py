import sqlite3
from pathlib import Path

import pytest

from radiant import config
from radiant.indexer import build_index
from radiant.search import search, walk


@pytest.fixture()
def indexed(repo_copy: Path) -> sqlite3.Connection:
    stats = build_index(repo_copy)
    assert stats.skipped == []
    con = sqlite3.connect(config.index_path(repo_copy))
    con.row_factory = sqlite3.Row
    return con


def test_index_contents(indexed):
    slugs = {r["slug"] for r in indexed.execute("SELECT slug FROM pages")}
    assert {"scrubber50", "error203", "lidar_cleaning", "v2_8", "ticket_0001"} <= slugs

    edges = {tuple(r) for r in indexed.execute("SELECT src, rel, dst FROM edges")}
    assert ("scrubber50", "known_errors", "error203") in edges
    assert ("error203", "fixed_in", "v2_8") in edges
    assert ("error203", "resolved_by", "lidar_cleaning") in edges

    alias = indexed.execute("SELECT slug FROM aliases WHERE alias = 'e203'").fetchone()
    assert alias["slug"] == "error203"  # COLLATE NOCASE

    sections = {
        r["heading"]
        for r in indexed.execute("SELECT heading FROM sections WHERE slug = 'error203'")
    }
    assert {"Symptoms", "Root causes", "Diagnosis", "Resolution", "History", "_intro"} <= sections


def test_tier0_alias_match(indexed):
    hits = search(indexed, "E203")
    assert hits[0].slug == "error203"
    assert hits[0].score >= 1000
    assert any("alias" in w for w in hits[0].why)


def test_tier1_fulltext(indexed):
    hits = search(indexed, "isopropyl")
    assert hits, "expected a full-text hit"
    assert hits[0].slug == "lidar_cleaning"
    assert any("text match" in w for w in hits[0].why)


def test_tier2_graph_expansion(indexed):
    hits = search(indexed, "E203")
    slugs = {h.slug for h in hits}
    # neighbors of error203 arrive via typed edges
    assert {"v2_8", "lidar_cleaning", "scrubber50"} <= slugs
    graph_hit = next(h for h in hits if h.slug == "v2_8")
    assert any("─fixed_in→" in w for w in graph_hit.why)


def test_deprecated_excluded_by_default(repo_copy: Path):
    page = repo_copy / "knowledge/firmware/v2_8.md"
    page.write_text(
        page.read_text().replace("status: active", "status: deprecated")
    )
    build_index(repo_copy)
    con = sqlite3.connect(config.index_path(repo_copy))
    con.row_factory = sqlite3.Row
    assert all(h.slug != "v2_8" for h in search(con, "v2.8"))
    assert any(h.slug == "v2_8" for h in search(con, "v2.8", include_deprecated=True))


def test_walk_all_edges(indexed):
    result = walk(indexed, "error203")
    assert ("fixed_in", "v2_8") in result["outgoing"]
    assert ("known_errors", "scrubber50") in result["incoming"]


def test_walk_relation_bfs(indexed):
    result = walk(indexed, "scrubber50", "known_errors", depth=2)
    assert result["levels"][0] == ["error203"]
