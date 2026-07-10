"""Weekly review — `radiant review`.

Composes the personal-brain digests into one snapshot: recurring investor
concerns (with cross-source theme detection), recent competitor moves, open
action items, and active ideas. Deterministic — the monitoring rollup you can
run today. The chief-of-staff agent later narrates over this backbone.

`--write` saves it as a dated research page under personal/research/, so
reviews accumulate in the KB and are themselves searchable and linkable.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from radiant import config, digest
from radiant.frontmatter import dump_page
from radiant.search import _STOPWORDS

_WORD_RE = re.compile(r"[a-z][a-z-]{3,}")


def _significant(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS}


@dataclass
class Theme:
    token: str
    pages: list[str]
    mentions: int = 0


def recurring_themes(entries) -> list[Theme]:
    """Significant words appearing in concern entries across >= 2 pages —
    the transparent, deterministic 'raised repeatedly' signal. Ranked by how
    many distinct pages, then total mentions. It's a keyword hint; the
    chief-of-staff agent does the real thematic synthesis."""
    token_pages: dict[str, set[str]] = defaultdict(set)
    token_mentions: dict[str, int] = defaultdict(int)
    for e in entries:
        for tok in _significant(e.text):
            token_pages[tok].add(e.page)
            token_mentions[tok] += 1
    themes = [
        Theme(tok, sorted(ps), token_mentions[tok])
        for tok, ps in token_pages.items()
        if len(ps) >= 2
    ]
    themes.sort(key=lambda t: (-len(t.pages), -t.mentions, t.token))
    return themes


def _filter_since(entries, since: str | None):
    if not since:
        return entries
    return [e for e in entries if e.when and e.when >= since]


def build_review(root: Path, since: str | None = None) -> tuple[str, list[str]]:
    """Return (markdown body, referenced slugs)."""
    inv = digest.collate(root, "investor", "Concerns raised")
    mtg_concerns = digest.collate(root, "meeting", "Concerns raised")
    comp = digest.collate(root, "competitor", "Intel log")
    actions = digest.collate(root, "meeting", "Action items")
    ideas = digest.collate(root, "idea", "Status & next step")

    concern_entries = _filter_since(inv.entries + mtg_concerns.entries, since)
    comp_entries = _filter_since(comp.entries, since)

    referenced: set[str] = set()
    out: list[str] = []

    scope = f" since {since}" if since else ""
    out.append(f"Personal review — generated {date.today().isoformat()}{scope}.\n")

    # Recurring themes across all concern sources
    themes = recurring_themes(concern_entries)
    out.append("## Recurring themes")
    if themes:
        for t in themes[:10]:
            pages = ", ".join(f"[[{p}]]" for p in t.pages)
            referenced.update(t.pages)
            out.append(f"- **{t.token}** — raised across {len(t.pages)} pages: {pages}")
    else:
        out.append("- (no theme appears across multiple notes yet)")

    out.append("\n## Investor concerns")
    if concern_entries:
        for e in concern_entries:
            referenced.add(e.page)
            when = f"{e.when} — " if e.when else ""
            out.append(f"- {when}{e.text}  ([[{e.page}]])")
    else:
        out.append("- (none in scope)")

    out.append("\n## Competitor moves")
    if comp_entries:
        for e in sorted(comp_entries, key=lambda e: e.when or "", reverse=True):
            referenced.add(e.page)
            when = f"{e.when} — " if e.when else ""
            out.append(f"- {when}{e.text}  ([[{e.page}]])")
    else:
        out.append("- (none in scope)")

    out.append("\n## Open action items")
    act = _filter_since(actions.entries, since)
    if act:
        for e in act:
            referenced.add(e.page)
            out.append(f"- {e.text}  ([[{e.page}]])")
    else:
        out.append("- (none)")

    out.append("\n## Active ideas")
    if ideas.entries:
        for e in ideas.entries:
            referenced.add(e.page)
            out.append(f"- {e.text}  ([[{e.page}]])")
    else:
        out.append("- (none)")

    return "\n".join(out) + "\n", sorted(referenced)


def write_review(root: Path, since: str | None = None, on: str | None = None) -> Path:
    """Write the review as a dated research page under personal/research/."""
    when = on or date.today().isoformat()
    slug = f"{when}-review"
    body_md, referenced = build_review(root, since)
    fm = {
        "id": slug,
        "type": "research",
        "title": f"Personal review — {when}",
        "aliases": [],
        "tags": ["review"],
        "status": "active",
        "relates_to": referenced,
        "sources": [],
        "created": when,
        "updated": when,
    }
    body = f"# Personal review — {when}\n\n{body_md}"
    dest = root / config.TYPE_FOLDERS["research"] / f"{slug}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(dump_page(fm, body), encoding="utf-8")
    return dest
