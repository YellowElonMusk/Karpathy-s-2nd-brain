"""radiant search — the retrieval cascade (docs/04-retrieval.md).

Tier 0: exact slug/alias match      -> confidence "exact"
Tier 1: FTS5 (BM25) over title/aliases/tags/body
Tier 2: graph expansion, 1 hop from the seeds, typed edges over mentions

Every result carries a `why` explaining its retrieval — the raw material
for explainable, citation-backed answers downstream.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from radiant import config

_TIER_SCORE = {"exact": 1000.0, "fts": 100.0, "graph": 50.0, "mentions": 10.0}


@dataclass
class Hit:
    slug: str
    title: str
    type: str
    status: str
    score: float
    why: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "slug": self.slug, "title": self.title, "type": self.type,
            "status": self.status, "score": round(self.score, 2), "why": self.why,
        }


def open_index(root: Path) -> sqlite3.Connection:
    db = config.index_path(root)
    if not db.exists():
        raise SystemExit("error: no index found — run `radiant index` first")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _fts_query(query: str) -> str | None:
    tokens = re.findall(r"[\w']+", query)
    if not tokens:
        return None
    return " ".join(f'"{t}"' for t in tokens)


def _page_row(con: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM pages WHERE slug = ?", (slug,)).fetchone()


def search(
    con: sqlite3.Connection,
    query: str,
    k: int = 10,
    include_deprecated: bool = False,
) -> list[Hit]:
    hits: dict[str, Hit] = {}

    def add(slug: str, score: float, why: str) -> None:
        row = _page_row(con, slug)
        if row is None:
            return
        if row["status"] == "deprecated" and not include_deprecated:
            return
        hit = hits.get(slug)
        if hit is None:
            hits[slug] = Hit(slug, row["title"], row["type"], row["status"], score, [why])
        else:
            hit.score = max(hit.score, score)
            if why not in hit.why:
                hit.why.append(why)

    # Tier 0 — exact slug or alias
    q = query.strip()
    row = con.execute("SELECT slug FROM pages WHERE slug = ?", (q.lower(),)).fetchone()
    if row:
        add(row["slug"], _TIER_SCORE["exact"], "exact slug match")
    row = con.execute("SELECT alias, slug FROM aliases WHERE alias = ?", (q,)).fetchone()
    if row:
        add(row["slug"], _TIER_SCORE["exact"], f"alias match: {row['alias']!r}")

    # Tier 1 — full text (AND, falling back to OR)
    fts_q = _fts_query(query)
    fts_rows: list[sqlite3.Row] = []
    if fts_q:
        for candidate in (fts_q, fts_q.replace(" ", " OR ")):
            fts_rows = con.execute(
                """SELECT slug, snippet(fts, 4, '<', '>', '…', 12) AS snip, rank
                   FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?""",
                (candidate, k),
            ).fetchall()
            if fts_rows:
                break
    for row in fts_rows:
        # fts5 bm25 rank is negative; more negative = better
        score = _TIER_SCORE["fts"] + min(-row["rank"] * 10, 99)
        snip = re.sub(r"\s+", " ", row["snip"]).strip()
        add(row["slug"], score, f"text match: {snip}")

    # Tier 2 — graph expansion from the strongest seeds
    seeds = [h.slug for h in sorted(hits.values(), key=lambda h: -h.score)[:3]]
    for seed in seeds:
        rows = con.execute(
            "SELECT src, rel, dst FROM edges WHERE src = ? OR dst = ?", (seed, seed)
        ).fetchall()
        for row in rows:
            other = row["dst"] if row["src"] == seed else row["src"]
            if other in seeds:
                continue
            tier = "mentions" if row["rel"] == "mentions" else "graph"
            path = f"{row['src']} ─{row['rel']}→ {row['dst']}"
            add(other, _TIER_SCORE[tier], f"graph: {path}")

    ranked = sorted(
        hits.values(), key=lambda h: (-h.score, h.status != "active", h.slug)
    )
    return ranked[:k]


def walk(
    con: sqlite3.Connection, slug: str, rel: str | None = None, depth: int = 1
) -> dict:
    """Graph neighborhood of a page. rel=None -> all edges both directions;
    rel given -> BFS along that relation up to `depth` hops."""
    page = _page_row(con, slug)
    if page is None:
        raise SystemExit(f"error: no page with slug {slug!r}")
    result = {"slug": slug, "title": page["title"], "type": page["type"]}

    if rel is None:
        out = con.execute(
            "SELECT rel, dst FROM edges WHERE src = ? ORDER BY rel, dst", (slug,)
        ).fetchall()
        inc = con.execute(
            "SELECT rel, src FROM edges WHERE dst = ? ORDER BY rel, src", (slug,)
        ).fetchall()
        result["outgoing"] = [(r["rel"], r["dst"]) for r in out]
        result["incoming"] = [(r["rel"], r["src"]) for r in inc]
        return result

    levels: list[list[str]] = []
    frontier, seen = {slug}, {slug}
    for _ in range(depth):
        nxt: set[str] = set()
        for node in frontier:
            for row in con.execute(
                "SELECT dst FROM edges WHERE src = ? AND rel = ?", (node, rel)
            ):
                if row["dst"] not in seen:
                    nxt.add(row["dst"])
                    seen.add(row["dst"])
        if not nxt:
            break
        levels.append(sorted(nxt))
        frontier = nxt
    result["rel"] = rel
    result["levels"] = levels
    return result
