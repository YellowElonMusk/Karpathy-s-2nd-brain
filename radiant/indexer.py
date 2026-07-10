"""radiant index — build build/index.db from the Markdown knowledge base.

The index is derived and disposable (docs/04-retrieval.md): pages, aliases,
typed edges + mentions, sections, and an FTS5 table. Built to a temp file,
then atomically swapped in.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from radiant import config
from radiant.kb import KB, MARKER_RE, Page, load_kb

_SCHEMA = """
CREATE TABLE pages (
  slug TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  path TEXT NOT NULL,
  summary TEXT,
  updated TEXT
);
CREATE TABLE aliases (
  alias TEXT PRIMARY KEY COLLATE NOCASE,
  slug TEXT REFERENCES pages(slug)
);
CREATE TABLE edges (
  src TEXT REFERENCES pages(slug),
  rel TEXT NOT NULL,
  dst TEXT REFERENCES pages(slug),
  PRIMARY KEY (src, rel, dst)
);
CREATE INDEX edges_dst ON edges (dst);
CREATE TABLE sections (
  slug TEXT REFERENCES pages(slug),
  heading TEXT,
  body TEXT,
  source_ids TEXT,
  PRIMARY KEY (slug, heading)
);
CREATE VIRTUAL TABLE fts USING fts5(
  slug UNINDEXED, title, aliases, tags, body
);
CREATE TABLE vectors (
  slug TEXT, heading TEXT, dim INTEGER, vec TEXT,
  PRIMARY KEY (slug, heading)
);
"""

_H2_SPLIT_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class IndexStats:
    pages: int
    aliases: int
    edges: int
    sections: int
    skipped: list[str]
    vectors: int = 0


def _summary(body: str) -> str:
    """First real paragraph: skip the H1, blockquote callouts, blanks."""
    for block in re.split(r"\n\s*\n", body):
        text = block.strip()
        if not text or text.startswith("#") or text.startswith(">"):
            continue
        return re.sub(r"\s+", " ", text)
    return ""


def _sections(body: str) -> list[tuple[str, str]]:
    """Split body into (heading, text) pairs; pre-heading content -> '_intro'."""
    parts = _H2_SPLIT_RE.split(body)
    out: list[tuple[str, str]] = []
    intro = parts[0].strip()
    if intro:
        out.append(("_intro", intro))
    for i in range(1, len(parts) - 1, 2):
        out.append((parts[i], parts[i + 1].strip()))
    return out


def _edges_for(kb: KB, page: Page) -> set[tuple[str, str, str]]:
    edges: set[tuple[str, str, str]] = set()
    for rel, targets in page.fm.relation_targets().items():
        for target in targets:
            resolved = kb.resolve(str(target))
            if resolved and resolved != page.slug:
                edges.add((page.slug, rel, resolved))
    typed_dsts = {dst for _, _, dst in edges}
    for target, _section in page.wiki_links:
        resolved = kb.resolve(target)
        if resolved and resolved != page.slug and resolved not in typed_dsts:
            edges.add((page.slug, "mentions", resolved))
    return edges


def build_index(root: Path, embedder=None) -> IndexStats:
    """Build build/index.db from the KB. When `embedder` is given, also embed
    each non-empty section into the vectors table for cascade tier 3."""
    kb = load_kb(root)
    good = [p for p in kb.pages if p.fm is not None]
    skipped = [p.rel_path for p in kb.pages if p.fm is None]

    build_dir = root / config.BUILD_DIR
    build_dir.mkdir(exist_ok=True)
    tmp = build_dir / (config.INDEX_DB + ".tmp")
    if tmp.exists():
        tmp.unlink()

    con = sqlite3.connect(tmp)
    try:
        con.executescript(_SCHEMA)
        n_aliases = n_edges = n_sections = 0
        to_embed: list[tuple[str, str, str]] = []  # (slug, heading, text)
        for page in good:
            fm = page.fm
            con.execute(
                "INSERT INTO pages VALUES (?,?,?,?,?,?,?)",
                (page.slug, fm.type, fm.title, fm.status, page.rel_path,
                 _summary(page.body), str(fm.updated)),
            )
            for alias in fm.aliases:
                cur = con.execute(
                    "INSERT OR IGNORE INTO aliases VALUES (?,?)", (str(alias), page.slug)
                )
                n_aliases += cur.rowcount
            for heading, text in _sections(page.body):
                markers = sorted(set(MARKER_RE.findall(text)))
                con.execute(
                    "INSERT OR REPLACE INTO sections VALUES (?,?,?,?)",
                    (page.slug, heading, text, json.dumps(markers)),
                )
                n_sections += 1
                if embedder is not None and text.strip():
                    to_embed.append((page.slug, heading, f"{fm.title} — {heading}\n{text}"))
            con.execute(
                "INSERT INTO fts VALUES (?,?,?,?,?)",
                (page.slug, fm.title, " ".join(str(a) for a in fm.aliases),
                 " ".join(str(t) for t in fm.tags), page.body),
            )
        for page in good:
            for src, rel, dst in sorted(_edges_for(kb, page)):
                cur = con.execute("INSERT OR IGNORE INTO edges VALUES (?,?,?)", (src, rel, dst))
                n_edges += cur.rowcount

        n_vectors = 0
        if embedder is not None and to_embed:
            vecs = embedder.embed([t for _, _, t in to_embed])
            for (slug, heading, _), vec in zip(to_embed, vecs):
                con.execute(
                    "INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)",
                    (slug, heading, embedder.dim, json.dumps([round(x, 6) for x in vec])),
                )
                n_vectors += 1
        con.commit()
    finally:
        con.close()

    os.replace(tmp, config.index_path(root))
    return IndexStats(len(good), n_aliases, n_edges, n_sections, skipped, n_vectors)
