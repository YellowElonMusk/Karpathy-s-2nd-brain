"""Personal-brain digests — `radiant digest`.

Collate one section across every page of a type: recurring investor concerns,
competitor moves, open action items. Reads Markdown directly (always current,
no reindex needed) and is fully deterministic — the monitoring view you can
use before any AI synthesis. The chief-of-staff agent adds the "what does this
add up to?" layer on top.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from radiant.kb import load_kb

_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S)\s*$", re.MULTILINE)
_DATED_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*[—-]\s*(.*)$")
# Bullets that are just template scaffolding, not real entries.
_PLACEHOLDER = re.compile(r"^\s*(owner\b|\[ \]\s*owner)", re.IGNORECASE)

# name -> (page_type, section)
PRESETS: dict[str, tuple[str, str]] = {
    "concerns": ("investor", "Concerns raised"),
    "competitors": ("competitor", "Intel log"),
    "actions": ("meeting", "Action items"),
    "ideas": ("idea", "Status & next step"),
}


@dataclass
class Entry:
    page: str          # slug
    page_title: str
    text: str
    when: str | None   # ISO date if the bullet was dated


@dataclass
class Digest:
    page_type: str
    section: str
    entries: list[Entry] = field(default_factory=list)

    def by_page(self) -> dict[str, list[Entry]]:
        out: dict[str, list[Entry]] = {}
        for e in self.entries:
            out.setdefault(e.page, []).append(e)
        return out

    def chronological(self) -> list[Entry]:
        """Dated entries, newest first — the trend/timeline view."""
        dated = [e for e in self.entries if e.when]
        return sorted(dated, key=lambda e: e.when, reverse=True)


def _section_body(body: str, heading: str) -> str | None:
    m = re.search(
        rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s|\Z)", body, re.MULTILINE | re.DOTALL
    )
    return m.group(1) if m else None


def collate(root: Path, page_type: str, section: str) -> Digest:
    digest = Digest(page_type=page_type, section=section)
    for page in load_kb(root).pages:
        if page.fm is None or page.fm.type != page_type:
            continue
        sec = _section_body(page.body, section)
        if sec is None:
            continue
        for raw in _BULLET_RE.findall(sec):
            text = raw.strip()
            if _PLACEHOLDER.match(text):   # template scaffolding, e.g. "[ ] owner — action"
                continue
            m = _DATED_RE.match(text)
            when, shown = (m.group(1), m.group(2).strip()) if m else (None, text)
            digest.entries.append(Entry(page.slug, page.fm.title, shown, when))
    return digest
