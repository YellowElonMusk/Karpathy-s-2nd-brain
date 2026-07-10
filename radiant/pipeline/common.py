"""Shared helpers for the ingest and learn runners."""

from __future__ import annotations

import subprocess
from pathlib import Path

from radiant import lint as lint_mod


def lint_errors_for(root: Path, changed: list[str]) -> list[str]:
    """Lint errors attributable to the files a pipeline run touched."""
    changed_set = set(changed)
    return [
        str(issue)
        for issue in lint_mod.run(root)
        if issue.severity == "error"
        and any(path in changed_set for path in issue.path.split(", "))
    ]


def git(root: Path, *args: str) -> None:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"error: git {' '.join(args)} failed:\n{result.stderr.strip()}")
