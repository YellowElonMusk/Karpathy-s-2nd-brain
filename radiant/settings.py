"""Load radiant.yaml — agent scopes, retrieval budget, merge policy.

Falls back to built-in defaults when the file is absent, so the tooling
works in a fresh checkout before anyone writes config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

_DEFAULTS: dict = {
    "agents": {
        "support": {
            "scope": ["robot", "error_code", "procedure", "firmware", "product",
                      "distributor", "ticket"],
            "deny": ["customer"],
            "write": False,
            "model": "claude-opus-4-8",
        },
        "curator": {"scope": ["all"], "write": "pr-only", "model": "claude-opus-4-8"},
        "chief-of-staff": {"scope": ["all"], "write": "pr-only", "model": "claude-opus-4-8",
                           "max_pages": 16},
    },
    "retrieval": {"max_pages": 8, "max_context_chars": 48000, "score_floor": 40.0},
    "learn": {"merge_policy": "human-review"},
}


@dataclass
class AgentConfig:
    name: str
    scope: list[str]        # page types, or ["all"]
    deny: list[str] = field(default_factory=list)
    write: object = False
    model: str = "claude-opus-4-8"
    max_pages: int | None = None   # per-agent context budget (synthesis needs more)

    def allows(self, page_type: str) -> bool:
        if page_type in self.deny:
            return False
        return "all" in self.scope or page_type in self.scope


@dataclass
class Settings:
    agents: dict[str, AgentConfig]
    max_pages: int
    max_context_chars: int
    score_floor: float
    merge_policy: str

    def agent(self, name: str) -> AgentConfig:
        if name not in self.agents:
            raise SystemExit(f"error: no agent {name!r} in radiant.yaml (have: {', '.join(self.agents)})")
        return self.agents[name]


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_settings(root: Path) -> Settings:
    data = dict(_DEFAULTS)
    cfg = root / "radiant.yaml"
    if cfg.exists():
        loaded = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        data = _merge(_DEFAULTS, loaded)
    agents = {
        name: AgentConfig(
            name=name,
            scope=a.get("scope", ["all"]),
            deny=a.get("deny", []),
            write=a.get("write", False),
            model=a.get("model", "claude-opus-4-8"),
            max_pages=a.get("max_pages"),
        )
        for name, a in data["agents"].items()
    }
    r = data["retrieval"]
    return Settings(
        agents=agents,
        max_pages=r["max_pages"],
        max_context_chars=r["max_context_chars"],
        score_floor=r["score_floor"],
        merge_policy=data["learn"]["merge_policy"],
    )
