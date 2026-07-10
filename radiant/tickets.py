"""Ticket store — operational data for the continuous-learning loop.

Interim SQLite (build/tickets.db) mirroring a subset of the PostgreSQL
`tickets` / `ticket_messages` schema in docs/06-operational-data.md; it
graduates to Postgres in Phase 5. Tickets link to the Markdown KB by slug
(robot model, error codes) — the slug is the foreign key across the
Git/SQL boundary.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from radiant import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY,
  external_ref TEXT,
  customer_slug TEXT,
  distributor_slug TEXT,
  robot_slug TEXT,
  channel TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  error_slugs TEXT DEFAULT '[]',
  summary TEXT,
  resolution TEXT,
  kb_page_slug TEXT,
  learn_status TEXT DEFAULT 'pending',
  opened_at TEXT,
  closed_at TEXT
);
CREATE TABLE IF NOT EXISTS ticket_messages (
  id INTEGER PRIMARY KEY,
  ticket_id INTEGER REFERENCES tickets(id),
  author TEXT,
  sent_at TEXT,
  body TEXT
);
"""


@dataclass
class Message:
    author: str
    sent_at: str
    body: str


@dataclass
class Ticket:
    id: int
    external_ref: str | None
    customer_slug: str | None
    distributor_slug: str | None
    robot_slug: str | None
    channel: str | None
    status: str
    error_slugs: list[str]
    summary: str | None
    resolution: str | None
    kb_page_slug: str | None
    learn_status: str
    opened_at: str | None
    closed_at: str | None
    messages: list[Message] = field(default_factory=list)

    def thread_text(self) -> str:
        """Render the ticket as an evidence document for the extractor."""
        head = [
            f"Ticket #{self.id}" + (f" (ref {self.external_ref})" if self.external_ref else ""),
            f"Robot model: {self.robot_slug or 'unknown'}",
            f"Error codes observed: {', '.join(self.error_slugs) or 'none recorded'}",
            f"Status: {self.status}",
        ]
        if self.summary:
            head.append(f"Summary: {self.summary}")
        if self.resolution:
            head.append(f"Resolution (as recorded): {self.resolution}")
        lines = ["\n".join(head), "\n--- Thread ---"]
        for m in self.messages:
            lines.append(f"[{m.sent_at}] {m.author}: {m.body}")
        return "\n".join(lines)


def _connect(root: Path) -> sqlite3.Connection:
    build = root / config.BUILD_DIR
    build.mkdir(exist_ok=True)
    con = sqlite3.connect(build / "tickets.db")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(_SCHEMA)
    # Light migration for stores created before a column existed.
    cols = {r["name"] for r in con.execute("PRAGMA table_info(tickets)")}
    if "distributor_slug" not in cols:
        con.execute("ALTER TABLE tickets ADD COLUMN distributor_slug TEXT")
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_ticket(root: Path, data: dict) -> int:
    """Insert a ticket (and its messages). `data` keys mirror the Ticket
    fields; `messages` is a list of {author, sent_at, body}. The friendly
    import keys `robot` and `customer` alias `robot_slug` / `customer_slug`."""
    data = {**data}
    data.setdefault("robot_slug", data.get("robot"))
    data.setdefault("customer_slug", data.get("customer"))
    data.setdefault("distributor_slug", data.get("distributor"))
    status = data.get("status", "open")
    closed_at = data.get("closed_at") or (_now() if status == "closed" else None)
    with _connect(root) as con:
        cur = con.execute(
            "INSERT INTO tickets (external_ref, customer_slug, distributor_slug, robot_slug, "
            "channel, status, error_slugs, summary, resolution, kb_page_slug, learn_status, "
            "opened_at, closed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                data.get("external_ref"), data.get("customer_slug"), data.get("distributor_slug"),
                data.get("robot_slug"), data.get("channel"), status,
                json.dumps(data.get("error_slugs", [])), data.get("summary"),
                data.get("resolution"), data.get("kb_page_slug"),
                data.get("learn_status", "pending"), data.get("opened_at") or _now(), closed_at,
            ),
        )
        ticket_id = cur.lastrowid
        for m in data.get("messages", []):
            con.execute(
                "INSERT INTO ticket_messages (ticket_id, author, sent_at, body) VALUES (?,?,?,?)",
                (ticket_id, m.get("author"), m.get("sent_at"), m.get("body")),
            )
        return ticket_id


def import_file(root: Path, path: Path) -> list[int]:
    """Import one or more tickets from a YAML file (a mapping or a list)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    tickets = data if isinstance(data, list) else [data]
    return [add_ticket(root, t) for t in tickets]


def get_ticket(root: Path, ticket_id: int) -> Ticket | None:
    with _connect(root) as con:
        row = con.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            return None
        msgs = con.execute(
            "SELECT author, sent_at, body FROM ticket_messages WHERE ticket_id = ? ORDER BY id",
            (ticket_id,),
        ).fetchall()
    return _row_to_ticket(row, msgs)


def set_learn_status(root: Path, ticket_id: int, status: str, kb_page_slug: str | None = None) -> None:
    with _connect(root) as con:
        if kb_page_slug is not None:
            con.execute(
                "UPDATE tickets SET learn_status = ?, kb_page_slug = ? WHERE id = ?",
                (status, kb_page_slug, ticket_id),
            )
        else:
            con.execute("UPDATE tickets SET learn_status = ? WHERE id = ?", (status, ticket_id))


def list_tickets(root: Path, status: str | None = None, learn_status: str | None = None) -> list[Ticket]:
    q = "SELECT * FROM tickets"
    conds, args = [], []
    if status:
        conds.append("status = ?"); args.append(status)
    if learn_status:
        conds.append("learn_status = ?"); args.append(learn_status)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY id"
    with _connect(root) as con:
        return [_row_to_ticket(r, []) for r in con.execute(q, args).fetchall()]


def _row_to_ticket(row: sqlite3.Row, msgs) -> Ticket:
    return Ticket(
        id=row["id"], external_ref=row["external_ref"], customer_slug=row["customer_slug"],
        distributor_slug=row["distributor_slug"], robot_slug=row["robot_slug"],
        channel=row["channel"], status=row["status"],
        error_slugs=json.loads(row["error_slugs"] or "[]"), summary=row["summary"],
        resolution=row["resolution"], kb_page_slug=row["kb_page_slug"],
        learn_status=row["learn_status"], opened_at=row["opened_at"], closed_at=row["closed_at"],
        messages=[Message(m["author"], m["sent_at"], m["body"]) for m in msgs],
    )
