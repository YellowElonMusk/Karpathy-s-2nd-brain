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
