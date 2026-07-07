"""Repo layout constants and root discovery."""

from __future__ import annotations

import os
from pathlib import Path

KNOWLEDGE_DIR = "knowledge"
TEMPLATES_DIR = "templates"
BUILD_DIR = "build"
INDEX_DB = "index.db"

# Where each page type lives. Folder membership is a lint rule.
TYPE_FOLDERS: dict[str, str] = {
    "robot": "knowledge/robots",
    "error_code": "knowledge/error_codes",
    "procedure": "knowledge/procedures",
    "firmware": "knowledge/firmware",
    "product": "knowledge/products",
    "customer": "knowledge/customers",
    "distributor": "knowledge/distributors",
    "ticket": "knowledge/tickets",
    "meeting": "knowledge/personal/meetings",
    "idea": "knowledge/personal/ideas",
    "investor": "knowledge/personal/investors",
    "competitor": "knowledge/personal/competitors",
    "research": "knowledge/personal/research",
}


def find_root(start: Path | None = None) -> Path:
    """Locate the repo root: $RADIANT_ROOT, or the nearest ancestor
    containing both knowledge/ and templates/."""
    env = os.environ.get("RADIANT_ROOT")
    if env:
        return Path(env).resolve()
    cur = (start or Path.cwd()).resolve()
    for p in (cur, *cur.parents):
        if (p / KNOWLEDGE_DIR).is_dir() and (p / TEMPLATES_DIR).is_dir():
            return p
    raise SystemExit(
        "error: not inside a RadiantBrain repo (no knowledge/ + templates/ found; "
        "set RADIANT_ROOT to override)"
    )


def index_path(root: Path) -> Path:
    return root / BUILD_DIR / INDEX_DB
