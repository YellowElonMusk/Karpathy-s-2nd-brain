from pathlib import Path

from radiant.pipeline.parsers import doc_as_prompt_text, parse_source

WHATSAPP = """\
[13/06/2026, 14:22:01] Alice (Distributor A): Hi, unit SN-4411 keeps stopping with E203
[13/06/2026, 14:23:10] Bob (RadiantBots): Which firmware is it on?
[13/06/2026, 14:25:44] Alice (Distributor A): v2.7
still happening after reboot
[13/06/2026, 14:30:02] Bob (RadiantBots): Clean the lidar window first, that fixes most E203s
"""

ANDROID_WA = """\
13/06/26, 14:22 - Alice: robot stopped again
13/06/26, 14:23 - Bob: same error?
13/06/26, 14:25 - Alice: yes E203
"""

NOTES_MD = """\
Intro paragraph before any heading.

# Service bulletin 17

## Affected units

Scrubber 50 units on firmware v2.6 and v2.7.

## Fix

Upgrade to v2.8.
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def test_whatsapp_ios_detected_and_parsed(tmp_path):
    doc = parse_source(_write(tmp_path, "chat.txt", WHATSAPP))
    assert doc.kind == "chat"
    assert len(doc.segments) == 4
    assert doc.segments[0].locator == "13/06/2026 14:22:01 Alice (Distributor A)"
    # continuation line folded into the message
    assert "still happening after reboot" in doc.segments[2].text


def test_whatsapp_android_format(tmp_path):
    doc = parse_source(_write(tmp_path, "chat2.txt", ANDROID_WA))
    assert doc.kind == "chat"
    assert len(doc.segments) == 3
    assert doc.segments[2].text == "yes E203"


def test_markdown_split_on_headings(tmp_path):
    doc = parse_source(_write(tmp_path, "bulletin.md", NOTES_MD))
    assert doc.kind == "text"
    locators = [s.locator for s in doc.segments]
    assert "§ Affected units" in locators and "§ Fix" in locators
    assert doc.segments[0].locator == "lines 1-2"  # intro before first heading


def test_plain_text_chunks_have_line_locators(tmp_path):
    text = "\n".join(f"line {i}" for i in range(1, 151))
    doc = parse_source(_write(tmp_path, "notes.txt", text))
    assert doc.segments[0].locator == "lines 1-60"
    assert doc.segments[2].locator == "lines 121-150"


def test_prompt_chunking_respects_budget(tmp_path):
    doc = parse_source(_write(tmp_path, "chat.txt", WHATSAPP))
    chunks = doc_as_prompt_text(doc, char_budget=200)
    assert len(chunks) > 1
    assert all("<segment locator=" in c for c in chunks)
