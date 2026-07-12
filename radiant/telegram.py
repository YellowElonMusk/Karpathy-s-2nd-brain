"""Telegram → globe bridge.

Your cron jobs (in the MiniMax sandbox) already deliver to a Telegram chat.
Each cron fire posts a `cron_pulse` JSON block; this reader polls the chat via
the Bot API, extracts the JSON, expands the findings, and feeds them to the
event store — so the globe lights up with no public endpoint and no change to
how the agents deliver.

The parsing (extract → expand → normalize) is pure and unit-tested; only the
poll loop touches the network (stdlib urllib, so no extra dependency).
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from radiant import config, events as events_mod

# Capture the whole content between ``` fences (non-greedy on the CLOSING fence,
# not on braces — brace-counting would truncate nested JSON at the first `}`).
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
# Envelope fields that cascade onto every finding unless the finding overrides.
_ENVELOPE_KEYS = ("agent", "job", "cron_job", "timestamp", "occurred_at", "source_agent")


def extract_json(text: str) -> list:
    """Pull JSON objects/arrays out of a Telegram message — fenced blocks first,
    else the whole message if it is itself JSON."""
    blocks: list = []
    for m in _FENCE.finditer(text or ""):
        try:
            blocks.append(json.loads(m.group(1).strip()))
        except ValueError:
            pass
    if not blocks:
        t = (text or "").strip()
        if t[:1] in "{[":
            try:
                blocks.append(json.loads(t))
            except ValueError:
                pass
    return blocks


def expand(payload) -> list[dict]:
    """A `cron_pulse` envelope -> one dict per finding (with envelope defaults
    merged in); a bare event dict -> [itself]; a list -> flattened."""
    if isinstance(payload, list):
        out: list[dict] = []
        for p in payload:
            out.extend(expand(p))
        return out
    if not isinstance(payload, dict):
        return []
    findings = payload.get("findings")
    if findings is None:
        return [payload]
    defaults = {k: payload[k] for k in _ENVELOPE_KEYS if k in payload}
    return [{**defaults, **f} for f in findings if isinstance(f, dict)]


def parse_message(text: str) -> tuple[list, list[str]]:
    """(events, errors) extracted from one Telegram message's JSON."""
    events, errors = [], []
    for block in extract_json(text):
        for finding in expand(block):
            try:
                events.append(events_mod.normalize_event(finding))
            except events_mod.NormalizeError as e:
                errors.append(str(e))
    return events, errors


# ---- network (only the poll loop below hits Telegram) ----

def _api(token: str, method: str, **params) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=65) as r:  # noqa: S310 (fixed host)
        return json.load(r)


def _offset_path(root: Path) -> Path:
    return root / config.BUILD_DIR / "telegram.json"


def _load_offset(root: Path) -> int:
    p = _offset_path(root)
    return json.loads(p.read_text()).get("offset", 0) if p.exists() else 0


def _save_offset(root: Path, offset: int) -> None:
    p = _offset_path(root)
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps({"offset": offset}))


def poll_once(root: Path, token: str, chat_id: str, *, _api=_api) -> tuple[list[int], list[str]]:
    """One getUpdates pass: ingest new messages from `chat_id`, advance the
    offset so nothing is re-read. `_api` is injectable for tests."""
    offset = _load_offset(root)
    resp = _api(token, "getUpdates", offset=offset, timeout=0)
    if not resp.get("ok"):
        raise RuntimeError(f"telegram getUpdates failed: {resp.get('description', resp)}")
    created, errors, max_id = [], [], offset
    for u in resp.get("result", []):
        max_id = max(max_id, u["update_id"] + 1)
        msg = u.get("message") or u.get("channel_post") or {}
        if str((msg.get("chat") or {}).get("id")) != str(chat_id):
            continue
        evs, errs = parse_message(msg.get("text") or msg.get("caption") or "")
        created += [events_mod.add_event(root, e) for e in evs]
        errors += errs
    if max_id != offset:
        _save_offset(root, max_id)
    return created, errors


def poll(root: Path, token: str, chat_id: str, *, once: bool = False,
         interval: int = 15, log=print) -> None:
    while True:
        try:
            created, errors = poll_once(root, token, chat_id)
            if created:
                log(f"ingested {len(created)} event(s)")
            for e in errors:
                log(f"skip: {e}")
        except Exception as ex:  # keep the loop alive across transient failures
            log(f"poll error: {ex}")
        if once:
            return
        time.sleep(interval)
