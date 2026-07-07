"""Load the knowledge base from disk into memory.

Used by lint (reports problems) and the indexer (skips broken pages).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from radiant import config
from radiant.frontmatter import FrontmatterError, split_page
from radiant.schema import BaseFrontmatter, validate_frontmatter

# [[target]], [[target#Section]], [[target|label]], [[target#Section|label]]
WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#([^\]\|]+))?(?:\|([^\]]+))?\]\]")
# Inline citation markers: [S1], [S12]
MARKER_RE = re.compile(r"\[(S\d+)\]")
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class Page:
    path: Path
    rel_path: str  # e.g. knowledge/error_codes/error203.md
    slug: str  # filename stem
    raw: dict | None
    fm: BaseFrontmatter | None
    body: str
    load_errors: list[str] = field(default_factory=list)

    @property
    def headings(self) -> list[str]:
        return HEADING_RE.findall(self.body)

    @property
    def wiki_links(self) -> list[tuple[str, str | None]]:
        """[(target, section-or-None), ...] from the body."""
        return [(m.group(1).strip(), m.group(2)) for m in WIKILINK_RE.finditer(self.body)]

    @property
    def markers(self) -> list[str]:
        """Citation markers used in the body, e.g. ['S1', 'S2']."""
        return MARKER_RE.findall(self.body)


@dataclass
class KB:
    root: Path
    pages: list[Page]
    by_slug: dict[str, Page]
    alias_map: dict[str, str]  # lowercased alias -> slug (first claimant wins)

    def resolve(self, target: str) -> str | None:
        t = target.strip()
        if t in self.by_slug:
            return t
        return self.alias_map.get(t.lower())


def load_page(path: Path, root: Path) -> Page:
    rel = str(path.relative_to(root))
    slug = path.stem
    text = path.read_text(encoding="utf-8")
    try:
        raw, body = split_page(text)
    except FrontmatterError as e:
        return Page(path, rel, slug, None, None, "", [str(e)])

    errors: list[str] = []
    fm: BaseFrontmatter | None = None
    try:
        fm = validate_frontmatter(raw)
    except ValueError as e:
        if isinstance(e, ValidationError):
            for err in e.errors():
                loc = ".".join(str(p) for p in err["loc"])
                errors.append(f"frontmatter: {loc}: {err['msg']}")
        else:
            errors.append(f"frontmatter: {e}")
    return Page(path, rel, slug, raw, fm, body, errors)


def load_kb(root: Path) -> KB:
    knowledge = root / config.KNOWLEDGE_DIR
    pages = [load_page(p, root) for p in sorted(knowledge.rglob("*.md"))]

    by_slug: dict[str, Page] = {}
    for page in pages:
        by_slug.setdefault(page.slug, page)

    alias_map: dict[str, str] = {}
    for page in pages:
        if page.fm is None:
            continue
        for alias in page.fm.aliases:
            alias_map.setdefault(str(alias).lower(), page.slug)

    return KB(root=root, pages=pages, by_slug=by_slug, alias_map=alias_map)
