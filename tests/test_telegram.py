from pathlib import Path

from radiant import events, telegram

PULSE = """\
Here's the 21:45 pulse 🌍
```json
{
  "event": "cron_pulse",
  "timestamp": "2026-07-11T21:45:00Z",
  "agent": "clara",
  "job": "geopolitics-watch",
  "findings": [
    {"headline": "Iran ceasefire wobbles", "place": "Iran", "category": "geo",
     "severity": "high", "related_slugs": ["distributor_a"]},
    {"headline": "Distributor A risk score rising", "place": "Nigeria",
     "category": "ops", "severity": "critical"}
  ]
}
```
"""


# --- extraction ---

def test_extract_fenced_json():
    blocks = telegram.extract_json(PULSE)
    assert len(blocks) == 1 and blocks[0]["agent"] == "clara"


def test_extract_bare_json():
    blocks = telegram.extract_json('{"headline":"x","place":"Tokyo"}')
    assert blocks and blocks[0]["headline"] == "x"


def test_extract_ignores_plain_text():
    assert telegram.extract_json("just a normal chat message, no json") == []


# --- envelope expansion: defaults cascade, findings override ---

def test_expand_pulse_merges_envelope_defaults():
    rows = telegram.expand(telegram.extract_json(PULSE)[0])
    assert len(rows) == 2
    assert all(r["agent"] == "clara" and r["job"] == "geopolitics-watch" for r in rows)
    assert rows[0]["headline"].startswith("Iran")


def test_expand_bare_event_passthrough():
    assert telegram.expand({"headline": "x", "place": "Tokyo"}) == [{"headline": "x", "place": "Tokyo"}]


def test_finding_overrides_envelope():
    rows = telegram.expand({"agent": "clara", "findings": [{"headline": "h", "place": "Tokyo", "agent": "hermes"}]})
    assert rows[0]["agent"] == "hermes"


# --- message -> events ---

def test_parse_message_produces_normalized_events():
    evs, errors = telegram.parse_message(PULSE)
    assert errors == [] and len(evs) == 2
    iran = next(e for e in evs if e.headline.startswith("Iran"))
    assert iran.agent == "clara" and iran.category == "geo" and iran.severity == "high"
    assert iran.cron_job == "geopolitics-watch"
    ops = next(e for e in evs if e.category == "ops")
    assert ops.severity == "critical"


def test_parse_message_reports_bad_finding():
    evs, errors = telegram.parse_message(
        '```json\n{"findings":[{"headline":"ok","place":"Tokyo"},{"headline":"nowhere"}]}\n```')
    assert len(evs) == 1 and len(errors) == 1


# --- poll_once with an injected fake Bot API (no network) ---

def _fake_updates(*messages, chat_id="8031693471"):
    result = [{"update_id": 100 + i, "message": {"chat": {"id": int(chat_id)}, "text": m}}
              for i, m in enumerate(messages)]

    def fake_api(token, method, **params):
        # respect the offset so a second poll returns nothing
        off = params.get("offset", 0)
        return {"ok": True, "result": [u for u in result if u["update_id"] >= off]}

    return fake_api


def test_poll_once_ingests_and_advances_offset(repo_copy: Path):
    api = _fake_updates(PULSE)
    created, errors = telegram.poll_once(repo_copy, "tok", "8031693471", _api=api)
    assert len(created) == 2 and errors == []
    assert {e.agent for e in events.feed(repo_copy)} == {"clara"}
    # offset advanced -> a second poll is a no-op
    again, _ = telegram.poll_once(repo_copy, "tok", "8031693471", _api=api)
    assert again == []


def test_poll_once_filters_other_chats(repo_copy: Path):
    api = _fake_updates(PULSE, chat_id="999")   # a different chat
    created, _ = telegram.poll_once(repo_copy, "tok", "8031693471", _api=api)
    assert created == []                          # nothing from the configured chat


# --- /api/sync: one-shot pull for the weekly-cron workflow ---

def test_api_sync_not_configured(repo_copy: Path, monkeypatch):
    fastapi_testclient = __import__("pytest").importorskip("fastapi.testclient")
    from radiant.indexer import build_index
    from radiant.webapp import create_app

    monkeypatch.delenv("RADIANT_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("RADIANT_TELEGRAM_CHAT", raising=False)
    build_index(repo_copy)
    client = fastapi_testclient.TestClient(create_app(repo_copy))
    r = client.post("/api/sync")
    assert r.status_code == 200
    assert r.json()["telegram"] == "not configured"


def test_api_sync_pulls_when_configured(repo_copy: Path, monkeypatch):
    fastapi_testclient = __import__("pytest").importorskip("fastapi.testclient")
    from radiant.indexer import build_index
    from radiant.webapp import create_app

    monkeypatch.setenv("RADIANT_TELEGRAM_TOKEN", "tok")
    monkeypatch.setenv("RADIANT_TELEGRAM_CHAT", "8031693471")
    monkeypatch.setattr(telegram, "poll_once", lambda root, t, c: ([7, 8], ["one skipped"]))
    build_index(repo_copy)
    client = fastapi_testclient.TestClient(create_app(repo_copy))
    r = client.post("/api/sync")
    assert r.status_code == 200
    data = r.json()
    assert data["telegram"] == "ok" and data["created"] == 2
    assert data["errors"] == ["one skipped"]
