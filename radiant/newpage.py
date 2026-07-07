"""radiant new — create a page from its type template."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from radiant import config
from radiant.schema import MODELS, SLUG_RE


def create(root: Path, page_type: str, slug: str, title: str | None = None) -> Path:
    if page_type not in MODELS:
        known = ", ".join(sorted(MODELS))
        raise ValueError(f"unknown page type {page_type!r} (known: {known})")
    if not SLUG_RE.match(slug):
        raise ValueError(f"slug {slug!r} must match [a-z0-9_-]+")

    template = root / config.TEMPLATES_DIR / f"{page_type}.md"
    if not template.exists():
        raise ValueError(f"missing template: {template}")

    dest = root / config.TYPE_FOLDERS[page_type] / f"{slug}.md"
    if dest.exists():
        raise ValueError(f"page already exists: {dest.relative_to(root)}")

    today = date.today().isoformat()
    text = template.read_text(encoding="utf-8")
    text = text.replace("SLUG", slug).replace("DATE", today)
    if title:
        text = text.replace('title: ""', f'title: "{title}"', 1)
        text = text.replace("# TITLE", f"# {title}", 1)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest
