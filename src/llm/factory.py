"""Provider selection factory.

Resolution order:
    1. explicit `name` argument, if given
    2. LLM_PROVIDER env var, if set
    3. auto-detect from API keys present in env (.env)
    4. fall back to mock (offline, deterministic — test fixture only)
"""
from __future__ import annotations

import os

from src.llm.provider import LLMProvider


def get_provider(name: str | None = None) -> LLMProvider:
    """Return an :class:`LLMProvider` instance, chosen by the rules above."""
    explicit = name or os.environ.get("LLM_PROVIDER")
    if explicit:
        chosen = explicit.lower()
    elif os.environ.get("GOOGLE_API_KEY"):
        chosen = "google"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        chosen = "anthropic"
    else:
        chosen = "mock"

    # Lazy imports — only pull in SDKs for the provider we actually selected.
    if chosen == "mock":
        from src.llm.mock import MockProvider
        return MockProvider()
    if chosen == "anthropic":
        from src.llm.anthropic import AnthropicProvider
        return AnthropicProvider()
    if chosen in {"google", "gemini"}:
        from src.llm.google import GoogleProvider
        return GoogleProvider()

    raise ValueError(
        f"Unknown LLM_PROVIDER={chosen!r}. Supported: 'mock', 'google', 'anthropic'."
    )
