"""Quick capture for the personal brain — `radiant note`.

Frictionless: append a dated bullet to the right section of a personal page,
creating the page from its template if it doesn't exist yet. This is the
daily driver for logging investor concerns, competitor moves, and meeting
notes. Deterministic — no API key needed.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from radiant import config
from radiant.frontmatter import dump_page, split_page
from radiant.newpage import create as create_page
from radiant.schema import MODELS, SLUG_RE

# Where an unqualified note lands, per page type.
DEFAULT_SECTION: dict[str, str | None] = {
    "investor": "Interaction history",
    "competitor": "Intel log",
    "meeting": "Notes",
    "idea": "Evidence for / against",
    "research": None,  # append to body
    "customer": "Support notes",
    "distributor": "Working notes",
}

_MEETING_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")


def _titleize(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip().title()


def _append_bullet(body: str, heading: str, bullet: str) -> str:
    """Append `bullet` to the end of the named section, creating it if absent.
    Existing section content (including template placeholders) is preserved."""
    pattern = re.compile(
        rf"(^##\s+{re.escape(heading)}\s*$\n)(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL
    )

    def repl(m: re.Match) -> str:
        content = m.group(2).rstrip()
        joined = f"{content}\n{bullet}" if content else bullet
        return f"{m.group(1)}{joined}\n\n"

    if pattern.search(body):
        return pattern.sub(repl, body, count=1).rstrip() + "\n"
    return body.rstrip() + f"\n\n## {heading}\n\n{bullet}\n"


def add_note(
    root: Path,
    page_type: str,
    slug: str,
    text: str,
    *,
    section: str | None = None,
    title: str | None = None,
    on: str | None = None,
) -> tuple[Path, bool]:
    """Append a dated note. Returns (page path, created?)."""
    if page_type not in MODELS:
        raise ValueError(f"unknown page type {page_type!r} (known: {', '.join(sorted(MODELS))})")
    when = on or date.today().isoformat()

    # Meetings are date-prefixed by convention; add it if the user didn't.
    if page_type == "meeting" and not _MEETING_DATE_RE.match(slug):
        slug = f"{when}-{slug}"
    if not SLUG_RE.match(slug):
        raise ValueError(f"slug {slug!r} must match [a-z0-9_-]+")

    section = section if section is not None else DEFAULT_SECTION.get(page_type)
    dest = root / config.TYPE_FOLDERS[page_type] / f"{slug}.md"

    created = False
    if not dest.exists():
        create_page(root, page_type, slug, title or _titleize(slug))
        created = True

    fm, body = split_page(dest.read_text(encoding="utf-8"))
    bullet = f"- {when} — {text}"
    if section:
        body = _append_bullet(body, section, bullet)
    else:
        body = body.rstrip() + f"\n\n{bullet}\n"
    fm["updated"] = when
    dest.write_text(dump_page(fm, body), encoding="utf-8")
    return dest, created
