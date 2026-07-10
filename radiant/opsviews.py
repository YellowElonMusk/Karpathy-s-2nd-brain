"""Read-only aggregate views over the operational stores (docs/06).

These are the SQLite-interim equivalents of the PostgreSQL views in
db/schema.sql — the data layer shared by the `ops_query` agent capability,
the `radiant ops` CLI, and the dashboard. Aggregates only; no per-message or
per-unit rows leak to callers (the privacy boundary from docs/05).
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from radiant import config


def _open(root: Path, name: str) -> sqlite3.Connection | None:
    db = root / config.BUILD_DIR / name
    if not db.exists():
        return None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


@dataclass
class Resolution:
    error_slug: str
    distributor: str | None
    resolution: str
    closed_at: str | None


def error_resolutions(root: Path, error_slug: str | None = None) -> list[Resolution]:
    """Prior closed-ticket resolutions, optionally for one error code —
    "has another distributor solved this before?" (docs/05)."""
    con = _open(root, "tickets.db")
    if con is None:
        return []
    out: list[Resolution] = []
    with con:
        rows = con.execute(
            "SELECT error_slugs, distributor_slug, resolution, closed_at FROM tickets "
            "WHERE status = 'closed' AND resolution IS NOT NULL AND resolution != ''"
        ).fetchall()
    for r in rows:
        for slug in json.loads(r["error_slugs"] or "[]"):
            if error_slug is None or slug == error_slug:
                out.append(Resolution(slug, r["distributor_slug"], r["resolution"], r["closed_at"]))
    out.sort(key=lambda x: (x.error_slug, x.closed_at or ""))
    return out


def error_frequency(root: Path) -> dict[str, int]:
    """Error-code occurrence across tickets (telemetry rolls in with Postgres)."""
    con = _open(root, "tickets.db")
    if con is None:
        return {}
    counter: Counter = Counter()
    with con:
        for r in con.execute("SELECT error_slugs FROM tickets"):
            for slug in json.loads(r["error_slugs"] or "[]"):
                counter[slug] += 1
    return dict(counter.most_common())


def ticket_volume(root: Path) -> dict[str, int]:
    con = _open(root, "tickets.db")
    if con is None:
        return {}
    with con:
        rows = con.execute("SELECT status, count(*) AS n FROM tickets GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


def learn_status_counts(root: Path) -> dict[str, int]:
    con = _open(root, "tickets.db")
    if con is None:
        return {}
    with con:
        rows = con.execute(
            "SELECT learn_status, count(*) AS n FROM tickets GROUP BY learn_status"
        ).fetchall()
    return {r["learn_status"]: r["n"] for r in rows}


@dataclass
class AnswerQuality:
    total: int
    by_confidence: dict[str, int]
    thumbs_up: int
    thumbs_down: int

    @property
    def answered_rate(self) -> float:
        if not self.total:
            return 0.0
        answered = self.total - self.by_confidence.get("none", 0)
        return answered / self.total


def answer_quality(root: Path) -> AnswerQuality:
    con = _open(root, "answers.db")
    if con is None:
        return AnswerQuality(0, {}, 0, 0)
    with con:
        conf = {
            r["confidence"]: r["n"]
            for r in con.execute(
                "SELECT confidence, count(*) AS n FROM agent_answers GROUP BY confidence"
            )
        }
        fb = con.execute(
            "SELECT sum(feedback = 1) AS up, sum(feedback = -1) AS down FROM agent_answers"
        ).fetchone()
    total = sum(conf.values())
    return AnswerQuality(total, conf, fb["up"] or 0, fb["down"] or 0)
