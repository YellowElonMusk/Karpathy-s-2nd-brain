"""Lint the knowledge base — the rule table from docs/02-knowledge-spec.md.

Severity policy: draft pages get warnings for body-link and source rules
(they're unreviewed WIP by definition); active/deprecated pages get errors.
Machine-written things (frontmatter relations, citation markers) are errors
at any status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from radiant import config
from radiant.kb import KB, Page, load_kb
from radiant.schema import REQUIRED_HEADINGS, TECHNICAL_TYPES

MEETING_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9_-]+$")


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.severity}: {self.message}"


def run(root: Path) -> list[Issue]:
    kb = load_kb(root)
    issues: list[Issue] = []

    _check_slug_uniqueness(kb, issues)
    _check_alias_collisions(kb, issues)

    for page in kb.pages:
        for msg in page.load_errors:
            issues.append(Issue("error", page.rel_path, msg))
        if page.fm is None:
            continue
        _check_identity(page, issues)
        _check_folder(page, issues)
        _check_sources(page, issues)
        _check_links(kb, page, issues)
        _check_markers(page, issues)
        _check_headings(page, issues)
        _check_deprecated_pointer(page, issues)

    return issues


def _sev_for_body(page: Page) -> str:
    return "warning" if page.fm and page.fm.status == "draft" else "error"


def _check_slug_uniqueness(kb: KB, issues: list[Issue]) -> None:
    seen: dict[str, str] = {}
    for page in kb.pages:
        if page.slug in seen:
            issues.append(
                Issue("error", page.rel_path, f"duplicate slug {page.slug!r} (also {seen[page.slug]})")
            )
        else:
            seen[page.slug] = page.rel_path


def _check_alias_collisions(kb: KB, issues: list[Issue]) -> None:
    claims: dict[str, list[Page]] = {}
    for page in kb.pages:
        if page.fm is None:
            continue
        for alias in page.fm.aliases:
            claims.setdefault(str(alias).lower(), []).append(page)
    for alias, claimants in claims.items():
        if len(claimants) > 1:
            paths = ", ".join(p.rel_path for p in claimants)
            issues.append(Issue("error", paths, f"ambiguous alias {alias!r} claimed by multiple pages"))
        owner = claimants[0]
        other = kb.by_slug.get(alias)
        if other is not None and other.slug != owner.slug:
            issues.append(
                Issue("error", owner.rel_path, f"alias {alias!r} collides with slug of {other.rel_path}")
            )


def _check_identity(page: Page, issues: list[Issue]) -> None:
    if page.fm.id != page.slug:
        issues.append(
            Issue("error", page.rel_path, f"frontmatter id {page.fm.id!r} != filename slug {page.slug!r}")
        )


def _check_folder(page: Page, issues: list[Issue]) -> None:
    expected = config.TYPE_FOLDERS.get(page.fm.type)
    actual = str(Path(page.rel_path).parent).replace("\\", "/")
    if expected and actual != expected:
        issues.append(
            Issue("error", page.rel_path, f"type {page.fm.type!r} belongs in {expected}/, found in {actual}/")
        )
    if page.fm.type == "meeting" and not MEETING_FILENAME_RE.match(page.slug):
        issues.append(
            Issue("warning", page.rel_path, "meeting filenames should be YYYY-MM-DD-slug.md")
        )


def _check_sources(page: Page, issues: list[Issue]) -> None:
    if page.fm.type in TECHNICAL_TYPES and not page.fm.sources:
        sev = _sev_for_body(page)
        issues.append(Issue(sev, page.rel_path, "technical page has no sources"))


def _check_links(kb: KB, page: Page, issues: list[Issue]) -> None:
    sev = _sev_for_body(page)
    for target, section in page.wiki_links:
        resolved = kb.resolve(target)
        if resolved is None:
            issues.append(Issue(sev, page.rel_path, f"unresolved wiki link [[{target}]]"))
            continue
        if section is not None:
            target_page = kb.by_slug[resolved]
            headings = {h.casefold() for h in target_page.headings}
            if section.strip().casefold() not in headings:
                issues.append(
                    Issue(
                        "warning",
                        page.rel_path,
                        f"section link [[{target}#{section}]] — no such heading on {resolved}",
                    )
                )
    # Frontmatter relations are machine-written: always errors.
    for rel, targets in page.fm.relation_targets().items():
        for target in targets:
            if kb.resolve(str(target)) is None:
                issues.append(
                    Issue("error", page.rel_path, f"relation {rel}: unresolved slug {target!r}")
                )


def _check_markers(page: Page, issues: list[Issue]) -> None:
    declared = {s.id for s in page.fm.sources}
    used = set(page.markers)
    for marker in sorted(used - declared):
        issues.append(
            Issue("error", page.rel_path, f"citation marker [{marker}] has no source in frontmatter")
        )
    for unused in sorted(declared - used):
        issues.append(Issue("warning", page.rel_path, f"declared source {unused} is never cited"))


def _check_headings(page: Page, issues: list[Issue]) -> None:
    required = REQUIRED_HEADINGS.get(page.fm.type, [])
    have = {h.casefold() for h in page.headings}
    missing = [h for h in required if h.casefold() not in have]
    if missing:
        issues.append(
            Issue("warning", page.rel_path, f"missing template headings: {', '.join(missing)}")
        )


def _check_deprecated_pointer(page: Page, issues: list[Issue]) -> None:
    if page.fm.status == "deprecated" and "supersede" not in page.body.lower():
        issues.append(
            Issue("warning", page.rel_path, "deprecated page should point to its replacement (\"Superseded by [[...]]\")")
        )


def print_report(issues: list[Issue], page_count: int) -> tuple[int, int]:
    errors = sorted((i for i in issues if i.severity == "error"), key=lambda i: i.path)
    warnings = sorted((i for i in issues if i.severity == "warning"), key=lambda i: i.path)
    for issue in errors + warnings:
        print(issue)
    print(f"{page_count} pages: {len(errors)} errors, {len(warnings)} warnings")
    return len(errors), len(warnings)
