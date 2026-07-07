"""Frontmatter schemas: one pydantic model per page type.

The relation vocabulary here IS the knowledge graph's edge vocabulary
(docs/02-knowledge-spec.md). Extend it here first; lint and the indexer
both read from these tables.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

SLUG_RE = re.compile(r"^[a-z0-9_-]+$")
SOURCE_ID_RE = re.compile(r"^S\d+$")

# Types whose pages must cite sources (once past draft status).
TECHNICAL_TYPES = {"robot", "error_code", "procedure", "firmware", "product"}

# Typed relation fields per page type; every value is a list of page slugs.
RELATION_FIELDS: dict[str, list[str]] = {
    "robot": ["components", "firmware_history", "known_errors", "procedures"],
    "error_code": ["affects_robots", "caused_by", "introduced_in", "fixed_in", "resolved_by"],
    "procedure": ["applies_to", "resolves", "requires"],
    "firmware": ["applies_to", "fixes", "introduces", "supersedes"],
    "product": ["used_in", "related_procedures"],
    "customer": ["robots_deployed", "distributor"],
    "distributor": ["customers", "certified_on"],
    "ticket": ["customer", "robot", "error_codes", "resolved_by"],
    "meeting": ["relates_to"],
    "idea": ["relates_to"],
    "investor": ["relates_to"],
    "competitor": ["relates_to"],
    "research": ["relates_to"],
}

# Non-slug extra fields per type: name -> (annotation, default factory sentinel)
_EXTRA_FIELDS: dict[str, dict[str, tuple]] = {
    "distributor": {"regions": (list[str], Field(default_factory=list))},
    "meeting": {"attendees": (list[str], Field(default_factory=list))},
    "ticket": {"postgres_id": (int, 0)},
}

# Template-defined section headings (missing ones are lint warnings).
REQUIRED_HEADINGS: dict[str, list[str]] = {
    "robot": ["Specifications", "Components", "Firmware", "Known issues", "Maintenance"],
    "error_code": ["Symptoms", "Root causes", "Diagnosis", "Resolution", "History"],
    "procedure": ["Prerequisites", "Steps", "Verification", "Troubleshooting"],
    "firmware": ["Fixes", "Known regressions", "Upgrade notes"],
    "product": ["Specifications", "Failure modes", "Replacement & sourcing"],
    "customer": ["Environment", "Support notes", "History"],
    "distributor": ["Technical capability", "Support patterns", "Working notes"],
    "ticket": ["Situation", "Diagnosis", "Resolution", "Lessons"],
    "meeting": ["Notes", "Decisions", "Action items", "Concerns raised"],
    "idea": ["Problem", "Approach", "Evidence for / against", "Status & next step"],
    "investor": ["Thesis fit", "Interaction history", "Concerns raised", "Next step"],
    "competitor": ["Product & positioning", "Strengths / weaknesses", "Where we win", "Intel log"],
    "research": [],
}


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    doc: str
    locator: str = ""

    @field_validator("id")
    @classmethod
    def _valid_source_id(cls, v: str) -> str:
        if not SOURCE_ID_RE.match(v):
            raise ValueError(f"source id {v!r} must match S<number> (S1, S2, ...)")
        return v


class BaseFrontmatter(BaseModel):
    """Fields every page carries. extra='forbid' catches unknown relation keys."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    title: str
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: Literal["draft", "active", "deprecated"]
    sources: list[Source] = Field(default_factory=list)
    created: date | str
    updated: date | str

    @field_validator("id")
    @classmethod
    def _valid_slug(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError(f"slug {v!r} must match [a-z0-9_-]+")
        return v

    def relation_targets(self) -> dict[str, list[str]]:
        """rel name -> slug list, for this page's type."""
        return {rel: getattr(self, rel) for rel in RELATION_FIELDS.get(self.type, [])}


def _build_models() -> dict[str, type[BaseFrontmatter]]:
    models: dict[str, type[BaseFrontmatter]] = {}
    for ptype, rels in RELATION_FIELDS.items():
        fields: dict[str, tuple] = {
            rel: (list[str], Field(default_factory=list)) for rel in rels
        }
        fields.update(_EXTRA_FIELDS.get(ptype, {}))
        models[ptype] = create_model(
            f"{ptype.title().replace('_', '')}Page", __base__=BaseFrontmatter, **fields
        )
    return models


MODELS: dict[str, type[BaseFrontmatter]] = _build_models()


def validate_frontmatter(data: dict) -> BaseFrontmatter:
    """Validate a raw frontmatter dict against its type's model.

    Raises ValueError (unknown type) or pydantic.ValidationError.
    """
    ptype = data.get("type")
    if ptype not in MODELS:
        known = ", ".join(sorted(MODELS))
        raise ValueError(f"unknown page type {ptype!r} (known: {known})")
    return MODELS[ptype].model_validate(data)
