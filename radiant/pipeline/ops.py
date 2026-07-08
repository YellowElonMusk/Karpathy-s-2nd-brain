"""The ops format: what an extractor proposes and the apply stage executes.

Uses lists rather than dicts throughout so the same models double as the
structured-output schema for the Claude extractor (structured outputs
require additionalProperties: false — no free-form dict keys).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

# Placeholder citation marker in proposed section content: [SRC:1] refers to
# add_sources[0]. The apply stage assigns real [Sn] ids per page.
SRC_PLACEHOLDER_RE = re.compile(r"\[SRC:(\d+)\]")


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc: str
    locator: str = ""


class Relation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rel: str
    targets: list[str]


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str  # template heading, or "_intro" for pre-heading content
    content: str  # markdown; cite with [SRC:n] placeholders


class PageOp(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    op: Literal["create", "update"]
    slug: str
    page_type: str | None = Field(default=None, alias="type")  # required for create
    title: str | None = None  # required for create
    reason: str = ""
    sections: list[Section] = Field(default_factory=list)
    add_sources: list[SourceRef] = Field(default_factory=list)
    add_relations: list[Relation] = Field(default_factory=list)
    add_aliases: list[str] = Field(default_factory=list)
    add_tags: list[str] = Field(default_factory=list)


class IngestPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ops: list[PageOp] = Field(default_factory=list)


def load_plan(path: Path) -> IngestPlan:
    """Load a plan from YAML — either a bare list of ops or {ops: [...]}."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"ops": data}
    return IngestPlan.model_validate(data)


def plan_to_yaml(plan: IngestPlan) -> str:
    return yaml.safe_dump(
        plan.model_dump(by_alias=True), sort_keys=False, allow_unicode=True, width=100
    )
