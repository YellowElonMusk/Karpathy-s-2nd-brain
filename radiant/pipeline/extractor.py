"""Extraction stage: turn a parsed document into an IngestPlan.

`ClaudeExtractor` is the real implementation (needs Anthropic API credentials
at runtime — set ANTHROPIC_API_KEY, or `ant auth login`). Until credentials
are configured, use `radiant ingest --plan plan.yaml` to apply a hand- or
externally-written plan through the same reconcile/apply stages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from radiant.kb import KB
from radiant.pipeline.ops import IngestPlan
from radiant.pipeline.parsers import ParsedDoc, doc_as_prompt_text
from radiant.schema import RELATION_FIELDS, REQUIRED_HEADINGS

PROMPT_PATH = Path(__file__).parent / "prompts" / "extract.md"
DEFAULT_MODEL = "claude-opus-4-8"


class Extractor(Protocol):
    def extract(self, doc: ParsedDoc, kb: KB) -> IngestPlan: ...


def build_context_pack(kb: KB) -> str:
    """Everything the extractor needs to know about the current KB."""
    lines = ["## Existing pages (slug (type): title — aliases)"]
    for page in kb.pages:
        if page.fm is None:
            continue
        aliases = ", ".join(str(a) for a in page.fm.aliases) or "-"
        lines.append(f"- {page.slug} ({page.fm.type}): {page.fm.title} — {aliases}")

    lines.append("\n## Relation vocabulary per page type")
    for ptype, rels in RELATION_FIELDS.items():
        lines.append(f"- {ptype}: {', '.join(rels)}")

    lines.append("\n## Template headings per page type")
    for ptype, headings in REQUIRED_HEADINGS.items():
        if headings:
            lines.append(f"- {ptype}: {', '.join(headings)}")
    return "\n".join(lines)


class ClaudeExtractor:
    """Claude-powered extraction via structured outputs."""

    def __init__(self, model: str | None = None):
        import os

        self.model = model or os.environ.get("RADIANT_EXTRACT_MODEL", DEFAULT_MODEL)

    def extract(self, doc: ParsedDoc, kb: KB) -> IngestPlan:
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError(
                "the anthropic package is required for extraction — pip install -e ."
            ) from e

        client = anthropic.Anthropic()
        system = [
            {
                "type": "text",
                "text": PROMPT_PATH.read_text(encoding="utf-8")
                + "\n\n# Knowledge-base context\n\n"
                + build_context_pack(kb),
                # KB context is identical across chunks of one run — cache it.
                "cache_control": {"type": "ephemeral"},
            }
        ]

        ops = []
        for chunk in doc_as_prompt_text(doc):
            try:
                response = client.messages.parse(
                    model=self.model,
                    max_tokens=16000,
                    thinking={"type": "adaptive"},
                    system=system,
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                f"Source document: {doc.path.name} (kind: {doc.kind})\n"
                                f"Cite sources with doc: {_doc_ref(doc.path)!r}\n\n{chunk}"
                            ),
                        }
                    ],
                    output_format=IngestPlan,
                )
            except anthropic.AuthenticationError as e:
                raise RuntimeError(
                    "no Anthropic API credentials — set ANTHROPIC_API_KEY (or run "
                    "`ant auth login`), or use `radiant ingest --plan plan.yaml` "
                    "to apply a pre-written plan instead"
                ) from e
            if response.stop_reason == "refusal":
                raise RuntimeError("extraction request was refused by the model")
            ops.extend(response.parsed_output.ops)
        return IngestPlan(ops=ops)


def _doc_ref(path: Path) -> str:
    """The doc string pages should cite: repo-relative when under sources/."""
    parts = path.parts
    if "sources" in parts:
        return str(Path(*parts[parts.index("sources"):]))
    return path.name
