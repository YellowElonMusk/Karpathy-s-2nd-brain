"""Split Markdown pages into (frontmatter dict, body)."""

from __future__ import annotations

import re

import yaml

_FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)


class FrontmatterError(ValueError):
    pass


def split_page(text: str) -> tuple[dict, str]:
    m = _FM_RE.match(text)
    if not m:
        raise FrontmatterError("missing frontmatter block (--- ... ---)")
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        raise FrontmatterError(f"invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise FrontmatterError("frontmatter is not a YAML mapping")
    return data, m.group(2)


def dump_page(fm: dict, body: str) -> str:
    """Serialize (frontmatter, body) back to a page, normalizing spacing."""
    dumped = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=100)
    if not body.startswith("\n"):
        body = "\n" + body
    if not body.endswith("\n"):
        body += "\n"
    return f"---\n{dumped}---\n{body}"
