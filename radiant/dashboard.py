"""Static, self-contained HTML dashboard (docs/07 Phase 5).

Read-only operator view: browse the KB, see error-frequency and ticket
trends, and read agent-answer quality — without a terminal. Generated from
the index + operational stores; no server, no external assets, works offline.

Charts are single-series magnitude bars (identity on the axis, one hue) with
value labels, plus reserved status colors for feedback — palette validated per
the dataviz method.
"""

from __future__ import annotations

import html
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from radiant import config, opsviews
from radiant.agent import curator

_CSS = """
:root{
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --series:#2a78d6; --track:#eeeeea; --good:#0ca30c; --crit:#d03b3b;
  --border:rgba(11,11,11,0.10);
}
@media (prefers-color-scheme:dark){:root{
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --series:#3987e5; --track:#2c2c2a; --good:#0ca30c; --crit:#d03b3b;
  --border:rgba(255,255,255,0.10);
}}
:root[data-theme=light]{--plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;
  --grid:#e1e0d9;--series:#2a78d6;--track:#eeeeea;--border:rgba(11,11,11,0.10);}
:root[data-theme=dark]{--plane:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;
  --grid:#2c2c2a;--series:#3987e5;--track:#2c2c2a;--border:rgba(255,255,255,0.10);}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5}
.wrap{max-width:1000px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:1.6rem;margin:0 0 4px} h2{font-size:1.05rem;margin:32px 0 12px}
.sub{color:var(--ink2);margin:0 0 24px;font-size:.9rem}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.tile .n{font-size:2rem;font-weight:650} .tile .l{color:var(--ink2);font-size:.82rem}
.tile .good{color:var(--good)} .tile .crit{color:var(--crit)}
.bar{display:grid;grid-template-columns:minmax(90px,180px) 1fr auto;gap:10px;align-items:center;margin:7px 0;font-size:.86rem}
.bar .lab{color:var(--ink2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar .track{display:block;background:var(--track);border-radius:5px;height:16px;overflow:hidden}
.bar .fill{display:block;background:var(--series);height:100%;border-radius:5px;min-width:2px}
.bar .val{font-variant-numeric:tabular-nums;color:var(--ink)}
.browse{columns:2;column-gap:24px} .browse .grp{break-inside:avoid;margin-bottom:14px}
.browse h3{font-size:.78rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:0 0 4px}
.browse a{color:var(--series);text-decoration:none;font-size:.9rem}
.browse .draft{color:var(--muted)} .browse li{margin:2px 0}
ul{margin:6px 0;padding-left:18px} .gaps li{color:var(--ink2)}
.foot{color:var(--muted);font-size:.8rem;margin-top:40px}
@media (max-width:640px){.browse{columns:1}}
"""


def _bars(items: list[tuple[str, int]]) -> str:
    if not items:
        return '<p class="sub">no data yet</p>'
    top = max((n for _, n in items), default=1) or 1
    rows = []
    for label, n in items:
        pct = 100 * n / top
        rows.append(
            f'<div class="bar"><span class="lab" title="{html.escape(label)}">{html.escape(label)}</span>'
            f'<span class="track"><span class="fill" style="width:{pct:.1f}%"></span></span>'
            f'<span class="val">{n}</span></div>'
        )
    return "".join(rows)


def _kb_data(root: Path) -> tuple[dict[str, list[tuple[str, str, str]]], int]:
    db = config.index_path(root)
    if not db.exists():
        raise SystemExit("error: no index found — run `radiant index` first")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        pages = con.execute(
            "SELECT slug, title, type, status FROM pages ORDER BY type, slug"
        ).fetchall()
        edges = con.execute("SELECT count(*) FROM edges").fetchone()[0]
    finally:
        con.close()
    by_type: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for p in pages:
        by_type[p["type"]].append((p["slug"], p["title"], p["status"]))
    return by_type, edges


def generate(root: Path) -> str:
    by_type, edges = _kb_data(root)
    total_pages = sum(len(v) for v in by_type.values())

    freq = opsviews.error_frequency(root)
    volume = opsviews.ticket_volume(root)
    learn = opsviews.learn_status_counts(root)
    quality = opsviews.answer_quality(root)
    gaps = curator.backlog(root)
    total_tickets = sum(volume.values())

    # Stat tiles
    tiles = [
        ("Knowledge pages", str(total_pages), ""),
        ("Graph edges", str(edges), ""),
        ("Tickets", str(total_tickets), ""),
        ("Answered rate", f"{quality.answered_rate * 100:.0f}%" if quality.total else "—", ""),
        ("👍 / 👎", f'<span class="good">{quality.thumbs_up}</span> / <span class="crit">{quality.thumbs_down}</span>', "raw"),
    ]
    tile_html = "".join(
        f'<div class="card tile"><div class="n">{n if raw else html.escape(n)}</div>'
        f'<div class="l">{html.escape(l)}</div></div>'
        for l, n, raw in tiles
    )

    # KB browser
    grp_html = []
    for ptype in sorted(by_type):
        items = "".join(
            f'<li><a class="{"draft" if st == "draft" else ""}" href="#">{html.escape(slug)}</a>'
            f'{" (draft)" if st == "draft" else ""}</li>'
            for slug, title, st in by_type[ptype]
        )
        grp_html.append(
            f'<div class="grp"><h3>{html.escape(ptype)} ({len(by_type[ptype])})</h3><ul>{items}</ul></div>'
        )

    conf_order = ["high", "medium", "low", "none"]
    conf_bars = [(c, quality.by_confidence.get(c, 0)) for c in conf_order if quality.by_confidence.get(c)]
    gap_html = (
        "".join(f"<li>{html.escape(g.question)}</li>" for g in gaps)
        if gaps else "<li>none — every logged question was answerable</li>"
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RadiantBrain dashboard</title><style>{_CSS}</style></head>
<body><div class="wrap">
<h1>RadiantBrain</h1>
<p class="sub">Knowledge &amp; support operations · generated {now}</p>
<div class="tiles">{tile_html}</div>

<h2>Knowledge base</h2>
<div class="card"><div class="browse">{''.join(grp_html)}</div></div>

<h2>Error frequency (across tickets)</h2>
<div class="card">{_bars(list(freq.items()))}</div>

<h2>Tickets by status</h2>
<div class="card">{_bars(sorted(volume.items()))}</div>

<h2>Learning pipeline</h2>
<div class="card">{_bars(sorted(learn.items()))}</div>

<h2>Answer quality</h2>
<div class="card">{_bars(conf_bars) if conf_bars else '<p class="sub">no answers logged yet</p>'}</div>

<h2>Documentation gaps</h2>
<div class="card"><ul class="gaps">{gap_html}</ul></div>

<p class="foot">Read-only view over the knowledge index and operational stores.
Markdown remains the source of truth; every number here is derived and rebuildable.</p>
</div></body></html>
"""


def write(root: Path, out: Path | None = None) -> Path:
    out = out or (root / config.BUILD_DIR / "dashboard.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(generate(root), encoding="utf-8")
    return out
