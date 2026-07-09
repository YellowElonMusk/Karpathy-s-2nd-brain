"""Shared Anthropic client construction with a friendly no-credentials error.

The SDK raises at construction time (a TypeError) when no API key / auth token
/ profile resolves, so credential problems surface here as a clear message
rather than a raw traceback deep in a pipeline stage.
"""

from __future__ import annotations


_NO_CREDS = (
    "no Anthropic API credentials configured — set ANTHROPIC_API_KEY (or run "
    "`ant auth login`). Until then, use `radiant ingest --plan plan.yaml` for "
    "ingestion; answering requires credentials."
)


def make_client():
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("the anthropic package is required — pip install -e .") from e
    try:
        return anthropic.Anthropic()
    except Exception as e:
        raise RuntimeError(_NO_CREDS) from e


def parse_structured(client, **kwargs):
    """client.messages.parse(**kwargs), translating the SDK's lazy
    no-credentials TypeError (raised at request time) into a clear error."""
    import anthropic

    try:
        return client.messages.parse(**kwargs)
    except anthropic.AuthenticationError as e:
        raise RuntimeError(_NO_CREDS) from e
    except TypeError as e:
        if "authentication" in str(e).lower():
            raise RuntimeError(_NO_CREDS) from e
        raise
