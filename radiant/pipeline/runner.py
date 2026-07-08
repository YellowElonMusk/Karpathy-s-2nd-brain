"""Runner: orchestrates acquire -> parse -> extract -> reconcile -> apply -> lint.

Git branch/commit handling is optional (--branch); the default applies to the
working tree so the diff is reviewable with plain `git diff`.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from radiant import config, lint as lint_mod
from radiant.kb import load_kb
from radiant.pipeline import jobs
from radiant.pipeline.apply import apply_plan
from radiant.pipeline.extractor import ClaudeExtractor, Extractor
from radiant.pipeline.ops import load_plan, plan_to_yaml
from radiant.pipeline.parsers import parse_source
from radiant.pipeline.reconcile import reconcile


@dataclass
class IngestResult:
    status: str  # done | skipped | dry-run | empty | lint_failed
    source: str = ""
    pages: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    plan_yaml: str = ""
    lint_errors: list[str] = field(default_factory=list)


def ingest(
    root: Path,
    source: str,
    *,
    plan_file: Path | None = None,
    type_hint: str | None = None,
    dry_run: bool = False,
    branch: bool = False,
    force: bool = False,
    extractor: Extractor | None = None,
) -> IngestResult:
    if source.startswith(("http://", "https://")):
        raise SystemExit("error: URL ingestion is not implemented yet — download the file first")
    src = Path(source).resolve()
    if not src.exists():
        raise SystemExit(f"error: no such file: {source}")

    content = src.read_bytes()
    content_hash = hashlib.sha256(content).hexdigest()
    if not force and jobs.find_done(root, content_hash):
        return IngestResult(status="skipped", source=str(src),
                            notes=["already ingested (same content hash); use --force to redo"])

    archived = _archive(root, src, content_hash)
    kb = load_kb(root)

    if plan_file is not None:
        plan = load_plan(plan_file)
    else:
        doc = parse_source(archived, type_hint)
        plan = (extractor or ClaudeExtractor()).extract(doc, kb)

    ops, notes = reconcile(kb, plan.ops)
    if not ops:
        return IngestResult(status="empty", source=str(archived), notes=notes)
    plan.ops = ops

    if dry_run:
        return IngestResult(status="dry-run", source=str(archived), notes=notes,
                            plan_yaml=plan_to_yaml(plan))

    job_id = jobs.start(root, str(archived.relative_to(root)), content_hash)
    if branch:
        _git(root, "checkout", "-b", f"ingest/{src.stem}")

    changed = apply_plan(root, kb, ops)
    rel_changed = [str(p.relative_to(root)) for p in changed]

    lint_errors = _lint_errors_for(root, rel_changed)
    if lint_errors:
        jobs.finish(root, job_id, "lint_failed", rel_changed, error="; ".join(lint_errors))
        return IngestResult(status="lint_failed", source=str(archived), pages=rel_changed,
                            notes=notes, lint_errors=lint_errors)

    if branch:
        _git(root, "add", *rel_changed, str(archived.relative_to(root)))
        _git(root, "commit", "-m", f"ingest: {src.name}")
        notes.append(f"committed on branch ingest/{src.stem} — push and open a PR to review")
    else:
        notes.append("applied to working tree — review with `git diff`, then commit")

    jobs.finish(root, job_id, "done", rel_changed)
    return IngestResult(status="done", source=str(archived), pages=rel_changed, notes=notes)


def _archive(root: Path, src: Path, content_hash: str) -> Path:
    """Copy the original under sources/ (idempotent)."""
    try:
        src.relative_to(root / "sources")
        return src  # already archived
    except ValueError:
        pass
    dest = root / "sources" / "exports" / src.name
    if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() != content_hash:
        dest = dest.with_name(f"{content_hash[:8]}-{src.name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(src, dest)
    return dest


def _lint_errors_for(root: Path, changed: list[str]) -> list[str]:
    """Lint errors attributable to the files this run touched."""
    changed_set = set(changed)
    return [
        str(issue)
        for issue in lint_mod.run(root)
        if issue.severity == "error" and any(path in changed_set for path in issue.path.split(", "))
    ]


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"error: git {' '.join(args)} failed:\n{result.stderr.strip()}")
