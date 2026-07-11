from pathlib import Path

import pytest

from radiant import events, webdata
from radiant.indexer import build_index


@pytest.fixture()
def indexed(repo_copy: Path) -> Path:
    build_index(repo_copy)
    return repo_copy


# --- events store ---

def test_feed_falls_back_to_samples_when_empty(repo_copy):
    feed = events.feed(repo_copy)
    assert len(feed) == len(events.SAMPLE_EVENTS)
    assert all(e.id for e in feed)                 # samples get stable ids
    assert events.get_event(repo_copy, 1) is not None


def test_add_event_takes_over_from_samples(repo_copy):
    events.add_event(repo_copy, events.Event(
        lat=48.85, lon=2.35, category="funding", headline="Paris robotics seed",
        body="…", cron_job="funding-radar", related_slugs=["scrubber50"]))
    feed = events.feed(repo_copy)
    assert len(feed) == 1                          # real events replace the demo feed
    assert feed[0].headline == "Paris robotics seed"


def test_import_events_file(repo_copy, tmp_path):
    f = tmp_path / "events.json"
    f.write_text('{"events":[{"lat":1,"lon":2,"category":"geo","headline":"x"},'
                 '{"lat":3,"lon":4,"category":"startup","headline":"y"}]}')
    assert events.import_file(repo_copy, f) == 2
    assert len(events.feed(repo_copy)) == 2


# --- graph payload (real index) ---

def test_graph_json_reflects_real_index(indexed):
    g = webdata.graph_json(indexed)
    ids = {n["id"] for n in g["nodes"]}
    assert {"scrubber50", "error203", "v2_8", "example_ventures"} <= ids
    # error203 and scrubber50 are the hubs -> highest degree
    by_deg = {n["id"]: n["degree"] for n in g["nodes"]}
    assert by_deg["error203"] >= 4 and by_deg["scrubber50"] >= 3
    top = max(g["nodes"], key=lambda n: n["degree"])
    assert top["id"] in {"error203", "scrubber50"}
    # links reference real edges
    assert any(l["source"] == "error203" and l["target"] == "v2_8" for l in g["links"])
    # every link endpoint is a known node
    for l in g["links"]:
        assert l["source"] in ids and l["target"] in ids


def test_page_json_has_sections_and_connections(indexed):
    p = webdata.page_json(indexed, "error203")
    assert p["type"] == "error_code" and p["status"] == "active"
    headings = {s["heading"] for s in p["sections"]}
    assert "Root causes" in headings
    connected = {c["slug"] for c in p["connected"]}
    assert {"v2_8", "lidar_cleaning", "scrubber50"} <= connected


def test_page_json_unknown_slug(indexed):
    assert webdata.page_json(indexed, "nope") is None


def test_graph_requires_index(repo_copy):
    with pytest.raises(FileNotFoundError, match="no index"):
        webdata.graph_json(repo_copy)


def test_events_and_report_json(indexed):
    ev = webdata.events_json(indexed)
    assert len(ev["events"]) == len(events.SAMPLE_EVENTS)
    first = ev["events"][0]
    assert {"lat", "lon", "category", "headline", "cron_job"} <= first.keys()
    rep = webdata.report_json(indexed, first["id"])
    assert rep["headline"] == first["headline"]
