from pathlib import Path

import pytest

from radiant import events, geo


# --- geocoding ---

def test_geocode_cities_and_countries():
    assert geo.geocode("Tehran")[0] == pytest.approx(35.69, abs=0.1)
    assert geo.geocode("san francisco") is not None
    assert geo.geocode("Nigeria") is not None
    assert geo.geocode("SÃO PAULO") is not None          # case + accent


def test_geocode_extracts_place_from_phrase():
    assert geo.geocode("renewed protests in France") == geo.geocode("france")
    assert geo.geocode("nowhere-land") is None


# --- normalize_event: tolerant field mapping ---

def test_normalize_maps_loose_fields():
    ev = events.normalize_event({
        "title": "YC backs Lagos logistics startup",
        "summary": "W26 batch, $500K seed.",
        "location": "Lagos",
        "type": "startup",
        "agent": "openclaw",
        "job": "startup-radar",
        "source": "yc.com",
        "related": ["idea_leasing"],
    })
    assert ev.headline.startswith("YC backs")
    assert ev.lat == pytest.approx(6.52, abs=0.1)
    assert ev.category == "startup" and ev.agent == "openclaw"
    assert ev.sources == ["yc.com"] and ev.related_slugs == ["idea_leasing"]


def test_normalize_infers_category_from_text():
    war = events.normalize_event({"headline": "War escalates near the strait", "place": "Iran"})
    assert war.category == "geo"
    raise_ = events.normalize_event({"headline": "Robotics startup raises Series B", "place": "Berlin"})
    assert raise_.category == "funding"


def test_normalize_accepts_explicit_coords():
    ev = events.normalize_event({"headline": "x", "lat": 12.3, "lon": 45.6})
    assert (ev.lat, ev.lon) == (12.3, 45.6)


def test_normalize_requires_headline_and_location():
    with pytest.raises(events.NormalizeError, match="headline"):
        events.normalize_event({"place": "Tokyo"})
    with pytest.raises(events.NormalizeError, match="locate"):
        events.normalize_event({"headline": "somewhere unknown", "place": "Atlantis"})


def test_ingest_dir_reads_json_and_jsonl_then_moves(repo_copy: Path, tmp_path: Path):
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "a.json").write_text('{"headline":"Berlin robotics seed","place":"Berlin","agent":"openclaw"}')
    (drop / "b.jsonl").write_text(
        '{"headline":"Tokyo export rule change","place":"Tokyo","agent":"hermes"}\n'
        '{"headline":"unlocatable","place":"Atlantis"}\n')
    created, errors = events.ingest_dir(repo_copy, drop)
    assert len(created) == 2 and len(errors) == 1        # one bad row reported
    agents = {e.agent for e in events.feed(repo_copy)}
    assert agents == {"openclaw", "hermes"}
    # processed files are moved aside, so a second pass is a no-op
    assert not list(drop.glob("*.json")) and (drop / ".processed").exists()
    assert events.ingest_dir(repo_copy, drop) == ([], [])


def test_add_normalized_event_shows_agent(repo_copy: Path):
    events.add_event(repo_copy, events.normalize_event({
        "headline": "Hermes flags AI export policy shift", "place": "Japan",
        "agent": "hermes", "job": "geopolitics-watch"}))
    feed = events.feed(repo_copy)
    assert len(feed) == 1
    assert feed[0].agent == "hermes" and feed[0].category == "geo"


# --- HTTP ingest endpoint (skips if FastAPI/TestClient unavailable) ---

@pytest.fixture()
def client(repo_copy: Path):
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    from radiant.indexer import build_index
    from radiant.webapp import create_app

    build_index(repo_copy)
    return fastapi_testclient.TestClient(create_app(repo_copy))


def test_post_events_ingests_and_shows_on_feed(client, repo_copy):
    r = client.post("/api/events", json={
        "events": [
            {"title": "OpenClaw: African fintech raises $10M", "place": "Nairobi",
             "agent": "openclaw", "job": "funding-radar"},
            {"headline": "no location here"},          # invalid -> reported, not fatal
        ]})
    assert r.status_code == 207                          # partial: 1 created, 1 error
    data = r.json()
    assert len(data["created"]) == 1 and len(data["errors"]) == 1
    feed = client.get("/api/events").json()["events"]
    assert any(e["agent"] == "openclaw" for e in feed)


def test_post_events_token_guard(client, monkeypatch, repo_copy):
    monkeypatch.setenv("RADIANT_INGEST_TOKEN", "s3cret")
    bad = client.post("/api/events", json={"headline": "x", "place": "Tokyo"})
    assert bad.status_code == 401
    ok = client.post("/api/events", headers={"Authorization": "Bearer s3cret"},
                     json={"headline": "authed event", "place": "Tokyo", "agent": "hermes"})
    assert ok.status_code == 201
