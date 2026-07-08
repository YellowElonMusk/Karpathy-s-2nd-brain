"""Ingest job log — idempotency by content hash.

Interim implementation in build/jobs.db (SQLite); replaced by the PostgreSQL
ingest_jobs table in Phase 5 (docs/06-operational-data.md). Losing this file
is harmless: re-ingesting just re-proposes the same changes.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from radiant import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_jobs (
  id INTEGER PRIMARY KEY,
  source_uri TEXT NOT NULL,
  content_hash TEXT UNIQUE,
  status TEXT NOT NULL DEFAULT 'running',
  pages_touched TEXT DEFAULT '[]',
  error TEXT,
  created_at TEXT,
  finished_at TEXT
);
"""


def _connect(root: Path) -> sqlite3.Connection:
    build = root / config.BUILD_DIR
    build.mkdir(exist_ok=True)
    con = sqlite3.connect(build / "jobs.db")
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def find_done(root: Path, content_hash: str) -> sqlite3.Row | None:
    with _connect(root) as con:
        return con.execute(
            "SELECT * FROM ingest_jobs WHERE content_hash = ? AND status = 'done'",
            (content_hash,),
        ).fetchone()


def start(root: Path, source_uri: str, content_hash: str) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect(root) as con:
        con.execute("DELETE FROM ingest_jobs WHERE content_hash = ?", (content_hash,))
        cur = con.execute(
            "INSERT INTO ingest_jobs (source_uri, content_hash, created_at) VALUES (?,?,?)",
            (source_uri, content_hash, now),
        )
        return cur.lastrowid


def finish(root: Path, job_id: int, status: str, pages: list[str], error: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect(root) as con:
        con.execute(
            "UPDATE ingest_jobs SET status=?, pages_touched=?, error=?, finished_at=? WHERE id=?",
            (status, json.dumps(pages), error, now, job_id),
        )
