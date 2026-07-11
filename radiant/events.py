"""World-event feed for the globe view — operational data (docs/07 Phase 6/7).

Events are geolocated one-liners the agent's cron jobs surface (geopolitics,
new startups, funding) plus their drill-down report. Interim SQLite store
(build/events.db), consistent with the ticket/answer stores; the cron jobs
(Phase 7) write here, and `radiant events import` loads a JSON feed by hand.
When the store is empty the dashboard shows SAMPLE_EVENTS so the globe is
never blank.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from radiant import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  category TEXT NOT NULL,          -- geo | startup | funding
  headline TEXT NOT NULL,
  body TEXT,
  cron_job TEXT,
  sources TEXT DEFAULT '[]',
  related_slugs TEXT DEFAULT '[]',
  occurred_at TEXT
);
"""

CATEGORIES = ("geo", "startup", "funding")


@dataclass
class Event:
    lat: float
    lon: float
    category: str
    headline: str
    body: str = ""
    cron_job: str = ""
    sources: list[str] = field(default_factory=list)
    related_slugs: list[str] = field(default_factory=list)
    occurred_at: str | None = None
    id: int | None = None

    def to_json(self) -> dict:
        d = asdict(self)
        return d


# Illustrative feed shown until real cron events land (matches the prototype).
SAMPLE_EVENTS: list[Event] = [
    Event(32.4, 53.7, "geo", "Iran–Israel ceasefire wobbles again",
          "Two independent outlets report renewed strikes near the Strait. Oil futures +4%. "
          "Flagged because 2 distributors ship LiDAR units through Gulf ports — supply-risk memo drafted.",
          "geopolitics-watch · 06:00 UTC", ["reuters wire (sim)", "tanker-tracking feed"],
          ["distributor_a"], "2026-07-10T06:00:00Z"),
    Event(6.52, 3.37, "startup", "YC backs Lagos AI logistics startup",
          "W26 batch: last-mile routing for African fleets, $500K seed. Adjacent to your ops-automation "
          "thesis — a potential design partner, not a competitor.",
          "startup-radar · 05:30 UTC", ["yc launch page (sim)", "crunchbase delta"],
          ["idea_leasing"], "2026-07-10T05:30:00Z"),
    Event(37.77, -122.42, "funding", "a16z leads $40M robotics round",
          "Series B into a warehouse-automation incumbent. Valuation implies a 9x forward multiple — "
          "useful comp for your own raise.",
          "funding-radar · 04:15 UTC", ["sec form D (sim)", "the information"],
          ["example_ventures"], "2026-07-10T04:15:00Z"),
    Event(1.35, 103.82, "startup", "Singapore cleaning-robot rival raises seed",
          "Direct competitor: floor-care robotics, $3M seed, targeting APAC malls. Overlaps Acme "
          "territory. Auto-logged to Competitor Watch.",
          "competitor-watch · 05:30 UTC", ["tech in asia (sim)", "linkedin hiring delta"],
          ["acme_robotics"], "2026-07-10T05:30:00Z"),
    Event(51.5, -0.12, "geo", "UK unveils AI safety mandate for autonomy",
          "New rules require incident logging for autonomous machines. Your citation-backed answer trail "
          "already satisfies most of it.",
          "geopolitics-watch · 06:00 UTC", ["gov.uk press (sim)"], ["error203"], "2026-07-10T06:00:00Z"),
    Event(28.61, 77.21, "funding", "Sequoia India funds warehouse automation",
          "$22M into robotic picking. Same partner Northwind name-dropped — warm-intro path mapped.",
          "funding-radar · 04:15 UTC", ["entrackr (sim)"], ["northwind_capital"], "2026-07-10T04:15:00Z"),
    Event(-23.55, -46.63, "startup", "São Paulo fintech for fleet leasing hits $1B",
          "They finance robot fleets — a possible channel to put Scrubber 50 units on lease.",
          "startup-radar · 05:30 UTC", ["bloomberg linea (sim)"], ["idea_leasing"], "2026-07-09T05:30:00Z"),
    Event(35.68, 139.69, "geo", "Japan loosens robotics export rules",
          "Export friction down for service robots. Opens a Tokyo distributor conversation shelved in Q1.",
          "geopolitics-watch · 06:00 UTC", ["nikkei (sim)"], ["scrubber50"], "2026-07-10T06:00:00Z"),
]


def _connect(root: Path) -> sqlite3.Connection:
    build = root / config.BUILD_DIR
    build.mkdir(exist_ok=True)
    con = sqlite3.connect(build / "events.db")
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def add_event(root: Path, ev: Event) -> int:
    with _connect(root) as con:
        cur = con.execute(
            "INSERT INTO events (lat, lon, category, headline, body, cron_job, sources, "
            "related_slugs, occurred_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (ev.lat, ev.lon, ev.category, ev.headline, ev.body, ev.cron_job,
             json.dumps(ev.sources), json.dumps(ev.related_slugs),
             ev.occurred_at or datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def import_file(root: Path, path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("events", data) if isinstance(data, dict) else data
    n = 0
    for r in rows:
        add_event(root, Event(**{k: r[k] for k in r if k in Event.__dataclass_fields__ and k != "id"}))
        n += 1
    return n


def list_events(root: Path) -> list[Event]:
    with _connect(root) as con:
        rows = con.execute("SELECT * FROM events ORDER BY occurred_at DESC").fetchall()
    return [
        Event(
            lat=r["lat"], lon=r["lon"], category=r["category"], headline=r["headline"],
            body=r["body"] or "", cron_job=r["cron_job"] or "",
            sources=json.loads(r["sources"] or "[]"),
            related_slugs=json.loads(r["related_slugs"] or "[]"),
            occurred_at=r["occurred_at"], id=r["id"],
        )
        for r in rows
    ]


def feed(root: Path) -> list[Event]:
    """Stored events, or the sample feed when the store is empty (demo)."""
    stored = list_events(root)
    if stored:
        return stored
    return [Event(**{**asdict(e), "id": i + 1}) for i, e in enumerate(SAMPLE_EVENTS)]


def get_event(root: Path, event_id: int) -> Event | None:
    return next((e for e in feed(root) if e.id == event_id), None)
