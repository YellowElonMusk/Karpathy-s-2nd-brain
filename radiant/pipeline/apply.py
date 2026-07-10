"""Apply stage: execute reconciled ops against the Markdown knowledge base.

Deterministic and side-effect-scoped: writes pages, assigns real [Sn]
citation ids from [SRC:n] placeholders, merges relations/aliases/tags.
The caller (runner) is responsible for linting and git.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from radiant import config
from radiant.kb import KB
from radiant.pipeline.ops import PageOp, SourceRef, SRC_PLACEHOLDER_RE
from radiant.schema import MODELS, RELATION_FIELDS, REQUIRED_HEADINGS, SLUG_RE

_SOURCE_ID_NUM_RE = re.compile(r"^S(\d+)$")


def apply_plan(root: Path, kb: KB, ops: list[PageOp]) -> list[Path]:
    """Apply all ops; returns the list of changed files. Validates before
    writing anything so a bad plan doesn't leave a half-applied tree."""
    for op in ops:
        _validate(kb, op)
    changed = []
    for op in ops:
        if op.op == "create":
            changed.append(_create_page(root, op))
        else:
            changed.append(_update_page(root, kb, op))
    return changed


def _validate(kb: KB, op: PageOp) -> None:
    if op.op == "create":
        if not op.page_type or not op.title:
            raise ValueError(f"create {op.slug!r}: type and title are required")
        if op.page_type not in MODELS:
            raise ValueError(f"create {op.slug!r}: unknown type {op.page_type!r}")
        if not SLUG_RE.match(op.slug):
            raise ValueError(f"create: invalid slug {op.slug!r}")
        rels = RELATION_FIELDS[op.page_type]
    else:
        page = kb.by_slug[op.slug]
        if page.fm is None:
            raise ValueError(f"update {op.slug!r}: page has broken frontmatter — fix it first")
        rels = RELATION_FIELDS[page.fm.type]
    for relation in op.add_relations:
        if relation.rel not in rels:
            raise ValueError(f"{op.slug!r}: relation {relation.rel!r} not valid for this type")
    n_sources = len(op.add_sources)
    for section in op.sections:
        for m in SRC_PLACEHOLDER_RE.finditer(section.content):
            if not (1 <= int(m.group(1)) <= n_sources):
                raise ValueError(
                    f"{op.slug!r}: [{m.group(0)[1:-1]}] has no matching add_sources entry"
                )


def _assign_sources(
    existing: list[dict], additions: list[SourceRef]
) -> tuple[list[dict], dict[int, str]]:
    """Merge additions into the page's source list. Ids are append-only —
    existing ids never change. Returns (final list, placeholder-index -> Sn)."""
    final = [dict(s) for s in existing]
    next_n = 1 + max(
        (int(m.group(1)) for s in final if (m := _SOURCE_ID_NUM_RE.match(str(s.get("id", ""))))),
        default=0,
    )
    mapping: dict[int, str] = {}
    for i, src in enumerate(additions, start=1):
        match = next(
            (s for s in final if s.get("doc") == src.doc and s.get("locator", "") == src.locator),
            None,
        )
        if match is None:
            match = {"id": f"S{next_n}", "doc": src.doc, "locator": src.locator}
            final.append(match)
            next_n += 1
        mapping[i] = match["id"]
    return final, mapping


def _rewrite_markers(text: str, mapping: dict[int, str]) -> str:
    return SRC_PLACEHOLDER_RE.sub(lambda m: f"[{mapping[int(m.group(1))]}]", text)


def _create_page(root: Path, op: PageOp) -> Path:
    today = date.today().isoformat()
    sources, mapping = _assign_sources([], op.add_sources)
    fm: dict = {
        "id": op.slug,
        "type": op.page_type,
        "title": op.title,
        "aliases": list(op.add_aliases),
        "tags": list(op.add_tags),
        "status": "draft",
    }
    relations = {r.rel: sorted(set(r.targets)) for r in op.add_relations}
    for rel in RELATION_FIELDS[op.page_type]:
        fm[rel] = relations.get(rel, [])
    fm["sources"] = sources
    fm["created"] = today
    fm["updated"] = today

    body_parts = [f"# {op.title}"]
    for heading, content in _ordered_sections(op):
        content = _rewrite_markers(content.strip(), mapping)
        if heading == "_intro":
            body_parts.append(content)
        else:
            body_parts.append(f"## {heading}\n\n{content}")

    dest = root / config.TYPE_FOLDERS[op.page_type] / f"{op.slug}.md"
    if dest.exists():
        raise ValueError(f"create {op.slug!r}: file already exists (reconcile should have caught this)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_render(fm, "\n" + "\n\n".join(body_parts) + "\n"), encoding="utf-8")
    return dest


def _ordered_sections(op: PageOp) -> list[tuple[str, str]]:
    """_intro first, then template-heading order, then extras as proposed."""
    template_order = REQUIRED_HEADINGS.get(op.page_type or "", [])
    rank = {"_intro": -1, **{h: i for i, h in enumerate(template_order)}}
    return sorted(
        ((s.heading, s.content) for s in op.sections),
        key=lambda hc: rank.get(hc[0], len(template_order)),
    )


def _update_page(root: Path, kb: KB, op: PageOp) -> Path:
    page = kb.by_slug[op.slug]
    raw = dict(page.raw)
    sources, mapping = _assign_sources(raw.get("sources") or [], op.add_sources)
    raw["sources"] = sources

    for relation in op.add_relations:
        current = [str(t) for t in (raw.get(relation.rel) or [])]
        raw[relation.rel] = current + sorted(set(relation.targets) - set(current))
    raw["aliases"] = list(raw.get("aliases") or []) + [
        a for a in op.add_aliases if a not in (raw.get("aliases") or [])
    ]
    raw["tags"] = list(raw.get("tags") or []) + [
        t for t in op.add_tags if t not in (raw.get("tags") or [])
    ]
    raw["updated"] = date.today().isoformat()

    body = page.body
    for section in op.sections:
        content = _rewrite_markers(section.content.strip(), mapping)
        if section.heading == "_intro":
            body = _set_intro(body, content)
        else:
            body = _set_section(body, section.heading, content)

    page.path.write_text(_render(raw, body), encoding="utf-8")
    return page.path


def _set_section(body: str, heading: str, content: str) -> str:
    pattern = re.compile(
        rf"(^##\s+{re.escape(heading)}\s*$\n)(.*?)(?=^##\s|\Z)", re.MULTILINE | re.DOTALL
    )
    if pattern.search(body):
        return pattern.sub(lambda m: f"{m.group(1)}\n{content}\n\n", body, count=1).rstrip() + "\n"
    return body.rstrip() + f"\n\n## {heading}\n\n{content}\n"


def _set_intro(body: str, content: str) -> str:
    """Replace the prose between the H1 line and the first ## heading,
    preserving any blockquote callout directly under the H1."""
    pattern = re.compile(r"(\A.*?^#\s.*?$\n(?:\s*(?:^>.*$\n)+)?)(.*?)(?=^##\s|\Z)",
                         re.MULTILINE | re.DOTALL)
    m = pattern.match(body)
    if not m:
        return body.rstrip() + "\n\n" + content + "\n"
    return (m.group(1).rstrip() + "\n\n" + content + "\n\n" + body[m.end():]).rstrip() + "\n"


def _render(fm: dict, body: str) -> str:
    from radiant.frontmatter import dump_page

    return dump_page(fm, body)
