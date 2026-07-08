"""Reconcile stage: deterministic dedup between a plan and the existing KB.

"Update, don't duplicate" enforced in code, not LLM judgment
(docs/03-pipelines.md stage 4). No API calls — fully testable.
"""

from __future__ import annotations

import difflib

from radiant.kb import KB
from radiant.pipeline.ops import PageOp

TITLE_SIMILARITY_THRESHOLD = 0.85


def reconcile(kb: KB, ops: list[PageOp]) -> tuple[list[PageOp], list[str]]:
    """Return (final ops, human-readable notes about what was rewritten)."""
    notes: list[str] = []
    merged = _merge_by_slug(ops, notes)
    final: list[PageOp] = []
    for op in merged:
        if op.op == "create":
            final.append(_reconcile_create(kb, op, notes))
        else:
            final.append(_reconcile_update(kb, op, notes))
    return final, notes


def _merge_by_slug(ops: list[PageOp], notes: list[str]) -> list[PageOp]:
    """Chunked extraction can emit several ops for one page — merge them."""
    by_slug: dict[str, PageOp] = {}
    for op in ops:
        existing = by_slug.get(op.slug)
        if existing is None:
            by_slug[op.slug] = op.model_copy(deep=True)
            continue
        notes.append(f"merged duplicate op for {op.slug!r}")
        if existing.op == "update" and op.op == "create":
            existing.op = "create"
            existing.page_type = existing.page_type or op.page_type
            existing.title = existing.title or op.title
        # later sections win on heading collision; sources/relations union
        headings = {s.heading: i for i, s in enumerate(existing.sections)}
        offset = len(existing.add_sources)
        for src in op.add_sources:
            if not any(s.doc == src.doc and s.locator == src.locator for s in existing.add_sources):
                existing.add_sources.append(src)
        for section in op.sections:
            section = section.model_copy()
            section.content = _shift_placeholders(section.content, offset, op, existing)
            if section.heading in headings:
                existing.sections[headings[section.heading]] = section
            else:
                existing.sections.append(section)
        _union_relations(existing, op)
        existing.add_aliases += [a for a in op.add_aliases if a not in existing.add_aliases]
        existing.add_tags += [t for t in op.add_tags if t not in existing.add_tags]
    return list(by_slug.values())


def _shift_placeholders(content: str, offset: int, src_op: PageOp, dst_op: PageOp) -> str:
    """Remap [SRC:n] indices when one op's sources are appended after another's."""
    from radiant.pipeline.ops import SRC_PLACEHOLDER_RE

    def remap(m):
        n = int(m.group(1))
        if 1 <= n <= len(src_op.add_sources):
            src = src_op.add_sources[n - 1]
            for i, existing in enumerate(dst_op.add_sources, start=1):
                if existing.doc == src.doc and existing.locator == src.locator:
                    return f"[SRC:{i}]"
        return m.group(0)

    return SRC_PLACEHOLDER_RE.sub(remap, content)


def _union_relations(dst: PageOp, src: PageOp) -> None:
    by_rel = {r.rel: r for r in dst.add_relations}
    for rel in src.add_relations:
        if rel.rel in by_rel:
            existing = by_rel[rel.rel]
            existing.targets += [t for t in rel.targets if t not in existing.targets]
        else:
            dst.add_relations.append(rel.model_copy(deep=True))


def _reconcile_create(kb: KB, op: PageOp, notes: list[str]) -> PageOp:
    # exact: proposed slug or any proposed alias already names a page
    resolved = kb.resolve(op.slug)
    if resolved is None:
        for alias in op.add_aliases:
            resolved = kb.resolve(str(alias))
            if resolved:
                break
    # fuzzy: near-identical title on a page of the same type
    if resolved is None and op.title:
        resolved = _fuzzy_title_match(kb, op)
    if resolved is not None:
        notes.append(f"create {op.slug!r} -> update {resolved!r} (already exists)")
        op = op.model_copy(deep=True)
        op.op = "update"
        op.slug = resolved
        op.page_type = None
        op.title = None
    return op


def _fuzzy_title_match(kb: KB, op: PageOp) -> str | None:
    wanted = op.title.strip().lower()
    best_slug, best_score = None, 0.0
    for page in kb.pages:
        if page.fm is None or (op.page_type and page.fm.type != op.page_type):
            continue
        score = difflib.SequenceMatcher(None, wanted, page.fm.title.strip().lower()).ratio()
        if score > best_score:
            best_slug, best_score = page.slug, score
    return best_slug if best_score >= TITLE_SIMILARITY_THRESHOLD else None


def _reconcile_update(kb: KB, op: PageOp, notes: list[str]) -> PageOp:
    resolved = kb.resolve(op.slug)
    if resolved is None:
        raise ValueError(
            f"update op targets unknown page {op.slug!r} — "
            "use op: create (with type and title) for new pages"
        )
    if resolved != op.slug:
        notes.append(f"update {op.slug!r} resolved via alias -> {resolved!r}")
        op = op.model_copy(deep=True)
        op.slug = resolved
    return op
