"""Slug-integrity check across the Git/SQL boundary (docs/06).

Slugs are the foreign keys that link the operational store (PostgreSQL, or
the interim SQLite) to the Markdown knowledge base. A page rename can leave an
operational row pointing at nothing; this job catches those dangling
references. Runs nightly in production; `radiant doctor` runs it on demand.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from radiant import config, tickets as ticket_store


@dataclass
class DanglingRef:
    source: str      # e.g. "ticket #4.robot_slug"
    slug: str

    def __str__(self) -> str:
        return f"{self.source} -> missing page {self.slug!r}"


def _index_slugs(root: Path) -> set[str] | None:
    db = config.index_path(root)
    if not db.exists():
        return None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {r[0] for r in con.execute("SELECT slug FROM pages")}
    finally:
        con.close()


def check_slugs(root: Path) -> list[DanglingRef]:
    """Every ticket slug reference must resolve to a page in the index."""
    slugs = _index_slugs(root)
    if slugs is None:
        raise SystemExit("error: no index found — run `radiant index` first")
    # Checks the references the pipeline depends on (robot model, error codes,
    # and any explicit ticket page). Account slugs (customer/distributor) are
    # operational identifiers that may legitimately have no KB page yet, so
    # they're excluded from the strict check.
    dangling: list[DanglingRef] = []
    for t in ticket_store.list_tickets(root):
        for field, value in (("robot_slug", t.robot_slug), ("kb_page_slug", t.kb_page_slug)):
            if value and value not in slugs:
                dangling.append(DanglingRef(f"ticket #{t.id}.{field}", value))
        for slug in t.error_slugs:
            if slug not in slugs:
                dangling.append(DanglingRef(f"ticket #{t.id}.error_slugs", slug))
    return dangling
