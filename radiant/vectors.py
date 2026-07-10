"""Embeddings for the optional vector retrieval tier (docs/04, tier 3).

Vectors are the LAST, optional tier of the cascade — pages + graph answer
most queries explainably; embeddings only catch fuzzy/semantic wording. The
provider sits behind the `Embedder` interface:

- `VoyageEmbedder` — a hosted embedding API (needs VOYAGE_API_KEY); the real
  semantic tier.
- `LocalEmbedder` — deterministic, offline, dependency-free. A hashed
  bag-of-tokens embedding: it proves the plumbing and gives lexical-overlap
  similarity, but it is NOT semantic. Use it for tests and offline indexing;
  swap in a real provider for production semantic search.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Protocol

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    dim: int
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # inputs are L2-normalized


def _normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v] if norm else v


class LocalEmbedder:
    """Deterministic hashed bag-of-tokens embedding — offline, not semantic."""

    name = "local"

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for tok in _TOKEN_RE.findall(text.lower()):
                h = int(hashlib.blake2b(tok.encode(), digest_size=8).hexdigest(), 16)
                vec[h % self.dim] += 1.0
            out.append(_normalize(vec))
        return out


class VoyageEmbedder:
    """Hosted semantic embeddings (voyage-3 family). Needs VOYAGE_API_KEY."""

    name = "voyage"

    def __init__(self, model: str = "voyage-3", dim: int = 1024):
        self.model = os.environ.get("RADIANT_EMBED_MODEL", model)
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        key = os.environ.get("VOYAGE_API_KEY")
        if not key:
            raise RuntimeError(
                "no VOYAGE_API_KEY — set it for semantic embeddings, or use the "
                "local embedder (RADIANT_EMBED_PROVIDER=local) for offline plumbing"
            )
        import httpx

        out: list[list[float]] = []
        with httpx.Client(timeout=60) as client:
            for i in range(0, len(texts), 128):  # API batch limit
                batch = texts[i : i + 128]
                resp = client.post(
                    "https://api.voyageai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"input": batch, "model": self.model},
                )
                resp.raise_for_status()
                out.extend(_normalize(d["embedding"]) for d in resp.json()["data"])
        return out


def get_embedder(provider: str | None = None) -> Embedder:
    provider = provider or os.environ.get("RADIANT_EMBED_PROVIDER")
    if provider is None:
        provider = "voyage" if os.environ.get("VOYAGE_API_KEY") else "local"
    if provider == "voyage":
        return VoyageEmbedder()
    if provider == "local":
        return LocalEmbedder()
    raise SystemExit(f"error: unknown embed provider {provider!r} (voyage | local)")
