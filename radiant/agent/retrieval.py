"""Scoped retrieval + context assembly for agents (docs/04, docs/05).

Scope is enforced HERE, at index-query time: a page whose type is denied to
the agent is dropped before it can reach the model, so scope violations are
structurally impossible rather than prompt-discouraged.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from radiant import search as search_mod
from radiant.search import Hit
from radiant.settings import AgentConfig


@dataclass
class SectionCtx:
    slug: str
    heading: str
    body: str
    source_ids: list[str]


@dataclass
class PageCtx:
    slug: str
    title: str
    type: str
    status: str
    summary: str
    why: list[str]
    sections: list[SectionCtx]
    sources: list[dict]         # [{id, doc, locator}, ...]


@dataclass
class Context:
    query: str
    pages: list[PageCtx]
    evidence_paths: list[str]   # graph paths that led to retrieval
    max_score: float

    @property
    def is_empty(self) -> bool:
        return not self.pages

    def valid_citations(self) -> set[tuple[str, str]]:
        """(slug, heading) pairs actually present in this context — the set a
        cited answer is allowed to reference."""
        return {(p.slug, s.heading) for p in self.pages for s in p.sections}

    def cited_pages(self) -> set[str]:
        return {p.slug for p in self.pages}


class ScopedRetriever:
    """Search + graph walk filtered to an agent's allowed page types."""

    def __init__(self, con: sqlite3.Connection, agent: AgentConfig):
        self.con = con
        self.agent = agent

    def _allowed(self, hit: Hit) -> bool:
        return self.agent.allows(hit.type)

    def search(self, query: str, k: int = 10) -> list[Hit]:
        # over-fetch so scope filtering doesn't starve results
        hits = search_mod.search(self.con, query, k=k * 3)
        return [h for h in hits if self._allowed(h)][:k]

    def _sources(self, slug: str) -> list[dict]:
        row = self.con.execute("SELECT path FROM pages WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            return []
        # sources live in the page frontmatter, not the index; the answer
        # cites page#section, and the section carries its [Sn] markers, which
        # is enough for the verifier. Full source docs are resolved lazily by
        # callers that need them (the learn pipeline), not for answering.
        return []

    def assemble(self, query: str, max_pages: int, max_chars: int) -> Context:
        hits = self.search(query, k=max_pages)
        pages: list[PageCtx] = []
        evidence: list[str] = []
        used = 0
        for hit in hits:
            page = self._page_ctx(hit)
            if page is None:
                continue
            cost = len(page.summary) + sum(len(s.body) for s in page.sections)
            if pages and used + cost > max_chars:
                break
            used += cost
            pages.append(page)
            for why in hit.why:
                if why.startswith("graph:") and why not in evidence:
                    evidence.append(why[len("graph:"):].strip())
        max_score = max((h.score for h in hits), default=0.0)
        return Context(query=query, pages=pages, evidence_paths=evidence, max_score=max_score)

    def _page_ctx(self, hit: Hit) -> PageCtx | None:
        prow = self.con.execute(
            "SELECT slug, title, type, status, summary FROM pages WHERE slug = ?", (hit.slug,)
        ).fetchone()
        if prow is None or not self.agent.allows(prow["type"]):
            return None
        srows = self.con.execute(
            "SELECT heading, body, source_ids FROM sections WHERE slug = ? AND heading != '_intro'",
            (hit.slug,),
        ).fetchall()
        sections = [
            SectionCtx(hit.slug, r["heading"], r["body"], json.loads(r["source_ids"] or "[]"))
            for r in srows
        ]
        return PageCtx(
            slug=prow["slug"], title=prow["title"], type=prow["type"], status=prow["status"],
            summary=prow["summary"] or "", why=hit.why, sections=sections, sources=[],
        )


def render_context(ctx: Context) -> str:
    """The evidence block handed to the model."""
    if ctx.is_empty:
        return "(no matching knowledge pages)"
    parts = []
    for p in ctx.pages:
        draft = " (draft — not yet reviewed)" if p.status == "draft" else ""
        block = [f"### [[{p.slug}]] — {p.title}{draft}", p.summary]
        for s in p.sections:
            block.append(f"#### {s.heading}\n{s.body}")
        parts.append("\n\n".join(x for x in block if x))
    ev = ""
    if ctx.evidence_paths:
        ev = "\n\nEvidence paths (knowledge graph):\n" + "\n".join(
            f"- {p}" for p in ctx.evidence_paths
        )
    return "\n\n---\n\n".join(parts) + ev
