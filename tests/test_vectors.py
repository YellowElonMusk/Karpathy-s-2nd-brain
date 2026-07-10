import sqlite3
from pathlib import Path

import pytest

from radiant import config
from radiant.indexer import build_index
from radiant.search import search
from radiant.vectors import LocalEmbedder, cosine, get_embedder


@pytest.fixture()
def embedder():
    return LocalEmbedder(dim=256)


def test_local_embedder_is_deterministic_and_normalized(embedder):
    a1 = embedder.embed(["lidar timeout on the scrubber"])[0]
    a2 = embedder.embed(["lidar timeout on the scrubber"])[0]
    assert a1 == a2                                   # deterministic
    assert abs(sum(x * x for x in a1) - 1.0) < 1e-9   # L2-normalized
    assert len(a1) == 256


def test_cosine_similarity_orders_by_overlap(embedder):
    base = embedder.embed(["navigation lidar timeout error"])[0]
    near = embedder.embed(["lidar timeout navigation"])[0]
    far = embedder.embed(["battery charging schedule"])[0]
    assert cosine(base, near) > cosine(base, far)


def test_get_embedder_selects_local_without_key(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("RADIANT_EMBED_PROVIDER", raising=False)
    assert get_embedder().name == "local"
    assert get_embedder("local").name == "local"
    assert get_embedder("voyage").name == "voyage"


def test_index_without_embedder_has_no_vectors(repo_copy):
    stats = build_index(repo_copy)
    assert stats.vectors == 0
    con = sqlite3.connect(config.index_path(repo_copy))
    assert con.execute("SELECT count(*) FROM vectors").fetchone()[0] == 0


def test_index_with_embedder_populates_vectors(repo_copy, embedder):
    stats = build_index(repo_copy, embedder=embedder)
    assert stats.vectors > 0
    con = sqlite3.connect(config.index_path(repo_copy))
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT slug, heading, dim FROM vectors").fetchall()
    assert all(r["dim"] == 256 for r in rows)
    # every non-intro section of error203 is embedded
    e203 = {r["heading"] for r in rows if r["slug"] == "error203"}
    assert {"Root causes", "Resolution"} <= e203


def test_cascade_tier3_activates_and_is_tagged(repo_copy, embedder):
    build_index(repo_copy, embedder=embedder)
    con = sqlite3.connect(config.index_path(repo_copy))
    con.row_factory = sqlite3.Row
    # a query whose words overlap error203's body; force the semantic tier
    hits = search(con, "navigation lidar timeout", embedder=embedder, semantic=True)
    assert any(h.slug == "error203" for h in hits)
    e203 = next(h for h in hits if h.slug == "error203")
    assert any("semantic match" in w for w in e203.why)


def test_tier3_skipped_without_embedder(repo_copy, embedder):
    build_index(repo_copy, embedder=embedder)
    con = sqlite3.connect(config.index_path(repo_copy))
    con.row_factory = sqlite3.Row
    hits = search(con, "navigation lidar timeout")   # no embedder passed
    assert all(not any("semantic" in w for w in h.why) for h in hits)


def test_tier3_noop_when_index_has_no_vectors(repo_copy, embedder):
    build_index(repo_copy)                            # no embedding
    con = sqlite3.connect(config.index_path(repo_copy))
    con.row_factory = sqlite3.Row
    # passing an embedder must not error when the vectors table is empty
    hits = search(con, "lidar", embedder=embedder, semantic=True)
    assert hits and all(not any("semantic" in w for w in h.why) for h in hits)
