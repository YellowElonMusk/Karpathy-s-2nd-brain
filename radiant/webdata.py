"""JSON payloads for the dashboard — pure functions over the real index.

The web server (radiant/webapp.py) is a thin shell around these; keeping the
data layer separate makes it testable without a running server. The graph is
the actual `build/index.db` — the same nodes/edges the agents traverse — so
clicking a node in the console opens the real knowledge page.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from radiant import config, events as events_mod

# Node colors are assigned client-side by type; the server just ships the type.
_TYPES = ["robot", "error_code", "procedure", "firmware", "product", "customer",
          "distributor", "ticket", "meeting", "idea", "investor", "competitor", "research"]


def _open(root: Path) -> sqlite3.Connection:
    db = config.index_path(root)
    if not db.exists():
        raise FileNotFoundError("no index — run `radiant index` first")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def graph_json(root: Path) -> dict:
    """Nodes + links for the neural view, straight from the index."""
    con = _open(root)
    try:
        pages = con.execute(
            "SELECT slug, type, title, status FROM pages ORDER BY slug"
        ).fetchall()
        edges = con.execute("SELECT src, rel, dst FROM edges").fetchall()
    finally:
        con.close()

    degree: dict[str, int] = {}
    for e in edges:
        degree[e["src"]] = degree.get(e["src"], 0) + 1
        degree[e["dst"]] = degree.get(e["dst"], 0) + 1

    nodes = [
        {"id": p["slug"], "type": p["type"], "title": p["title"],
         "status": p["status"], "degree": degree.get(p["slug"], 0)}
        for p in pages
    ]
    links = [{"source": e["src"], "target": e["dst"], "rel": e["rel"]} for e in edges]
    return {"nodes": nodes, "links": links}


def page_json(root: Path, slug: str) -> dict | None:
    """A node's detail drawer — title, sections, and connected nodes."""
    con = _open(root)
    try:
        p = con.execute(
            "SELECT slug, type, title, status, summary, path FROM pages WHERE slug = ?", (slug,)
        ).fetchone()
        if p is None:
            return None
        sections = con.execute(
            "SELECT heading, body, source_ids FROM sections WHERE slug = ? AND heading != '_intro'",
            (slug,),
        ).fetchall()
        out = con.execute("SELECT rel, dst FROM edges WHERE src = ?", (slug,)).fetchall()
        inc = con.execute("SELECT rel, src FROM edges WHERE dst = ?", (slug,)).fetchall()
    finally:
        con.close()

    return {
        "slug": p["slug"], "type": p["type"], "title": p["title"], "status": p["status"],
        "summary": p["summary"] or "", "path": p["path"],
        "sections": [
            {"heading": s["heading"], "body": s["body"],
             "sources": json.loads(s["source_ids"] or "[]")}
            for s in sections
        ],
        "connected": (
            [{"rel": r["rel"], "slug": r["dst"], "dir": "out"} for r in out]
            + [{"rel": r["rel"], "slug": r["src"], "dir": "in"} for r in inc]
        ),
    }


def events_json(root: Path) -> dict:
    return {"events": [e.to_json() for e in events_mod.feed(root)]}


def report_json(root: Path, event_id: int) -> dict | None:
    ev = events_mod.get_event(root, event_id)
    return ev.to_json() if ev else None
