"""Format-specific parsers. Every parser emits (text, locator) segments so
citations survive from raw source to knowledge page (docs/03-pipelines.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# WhatsApp export formats:
#   iOS:     [13/06/2026, 14:22:01] Alice: message
#   Android: 13/06/2026, 14:22 - Alice: message
_WA_IOS_RE = re.compile(
    r"^\[(\d{1,2}/\d{1,2}/\d{2,4}),? (\d{1,2}:\d{2}(?::\d{2})?)\] ([^:]+): (.*)$"
)
_WA_ANDROID_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}), (\d{1,2}:\d{2}) - ([^:]+): (.*)$"
)
_HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$")

_MAX_PLAIN_SEGMENT_LINES = 60


@dataclass
class Segment:
    text: str
    locator: str  # "p. 3" | "§ Heading" | "lines 12-40" | "13/06/2026 14:22 Alice"


@dataclass
class ParsedDoc:
    path: Path
    kind: str  # pdf | text | chat
    segments: list[Segment]


def parse_source(path: Path, type_hint: str | None = None) -> ParsedDoc:
    kind = type_hint or _detect_kind(path)
    if kind == "pdf":
        return ParsedDoc(path, "pdf", _parse_pdf(path))
    text = path.read_text(encoding="utf-8", errors="replace")
    if kind == "chat":
        return ParsedDoc(path, "chat", _parse_whatsapp(text))
    return ParsedDoc(path, "text", _parse_text(text))


def _detect_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in (".txt", ".log"):
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
        lines = head.splitlines()[:20]
        wa_hits = sum(1 for l in lines if _WA_IOS_RE.match(l) or _WA_ANDROID_RE.match(l))
        if wa_hits >= 3:
            return "chat"
    return "text"


def _parse_text(text: str) -> list[Segment]:
    """Split on markdown headings when present; otherwise fixed line windows."""
    lines = text.splitlines()
    heading_idx = [i for i, l in enumerate(lines) if _HEADING_RE.match(l)]

    segments: list[Segment] = []
    if len(heading_idx) >= 2:
        bounds = heading_idx + [len(lines)]
        if heading_idx[0] > 0:
            intro = "\n".join(lines[: heading_idx[0]]).strip()
            if intro:
                segments.append(Segment(intro, f"lines 1-{heading_idx[0]}"))
        for start, end in zip(bounds, bounds[1:]):
            chunk = "\n".join(lines[start:end]).strip()
            if chunk:
                heading = _HEADING_RE.match(lines[start]).group(1)
                segments.append(Segment(chunk, f"§ {heading}"))
    else:
        for start in range(0, len(lines), _MAX_PLAIN_SEGMENT_LINES):
            end = min(start + _MAX_PLAIN_SEGMENT_LINES, len(lines))
            chunk = "\n".join(lines[start:end]).strip()
            if chunk:
                segments.append(Segment(chunk, f"lines {start + 1}-{end}"))
    return segments


def _parse_whatsapp(text: str) -> list[Segment]:
    """One segment per message; continuation lines are appended to it."""
    segments: list[Segment] = []
    current: Segment | None = None
    for line in text.splitlines():
        m = _WA_IOS_RE.match(line) or _WA_ANDROID_RE.match(line)
        if m:
            date, time, sender, body = m.groups()
            current = Segment(body, f"{date} {time} {sender.strip()}")
            segments.append(current)
        elif current is not None and line.strip():
            current.text += "\n" + line
    return segments


def _parse_pdf(path: Path) -> list[Segment]:
    try:
        import fitz  # pymupdf
    except ImportError as e:
        raise RuntimeError(
            "PDF parsing requires pymupdf — install with: pip install 'radiant-brain[pdf]'"
        ) from e
    segments = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            if text:
                segments.append(Segment(text, f"p. {i}"))
    return segments


def doc_as_prompt_text(doc: ParsedDoc, char_budget: int = 300_000) -> list[str]:
    """Render segments as locator-tagged text, chunked to a character budget."""
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for seg in doc.segments:
        rendered = f"<segment locator={seg.locator!r}>\n{seg.text}\n</segment>"
        if buf and size + len(rendered) > char_budget:
            chunks.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(rendered)
        size += len(rendered)
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks
