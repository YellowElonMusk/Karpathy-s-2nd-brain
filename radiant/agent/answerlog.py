"""Answer log — every agent answer with its citations and confidence.

Interim SQLite (build/answers.db) until the PostgreSQL agent_answers table
in Phase 5 (docs/06-operational-data.md). Feeds the eval loop and the
curator's unanswered-question backlog.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from radiant import config
from radiant.agent.contract import Answer

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_answers (
  id INTEGER PRIMARY KEY,
  asked_at TEXT,
  agent TEXT,
  channel TEXT,
  question TEXT NOT NULL,
  answer_md TEXT,
  citations TEXT,
  confidence TEXT,
  feedback INTEGER
);
"""


def _connect(root: Path) -> sqlite3.Connection:
    build = root / config.BUILD_DIR
    build.mkdir(exist_ok=True)
    con = sqlite3.connect(build / "answers.db")
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def record(root: Path, agent: str, question: str, answer: Answer, channel: str = "cli") -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    citations = json.dumps([c.model_dump() for c in answer.citations])
    with _connect(root) as con:
        cur = con.execute(
            "INSERT INTO agent_answers (asked_at, agent, channel, question, answer_md, "
            "citations, confidence) VALUES (?,?,?,?,?,?,?)",
            (now, agent, channel, question, answer.answer_md, citations, answer.confidence),
        )
        return cur.lastrowid


def unanswered(root: Path) -> list[sqlite3.Row]:
    """Curator backlog: questions the agent couldn't answer (docs/05)."""
    with _connect(root) as con:
        return con.execute(
            "SELECT question, asked_at FROM agent_answers WHERE confidence = 'none' "
            "ORDER BY asked_at DESC"
        ).fetchall()
