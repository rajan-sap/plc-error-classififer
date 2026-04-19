"""LLMProvider Protocol + the structured-response types every provider returns.

Keeping the LLM contract separate from the API schemas means we can change
either independently. The classifier talks to LLMResponse; the API surface
talks to ClassifyResponse (in src/api/schemas.py).
"""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from src.parser.models import Complexity, ParsedError, ParsedLog, Severity


class LLMSuggestion(BaseModel):
    title: str
    rationale: str
    before_snippet: str | None = None
    after_snippet: str | None = None
    # Provider's raw self-reported confidence; blended later by derive_confidence().
    raw_confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class LLMClassification(BaseModel):
    error_id: str
    severity: Severity
    fix_complexity: Complexity
    root_cause: str
    suggestions: list[LLMSuggestion]


class LLMResponse(BaseModel):
    classifications: list[LLMClassification]
    provider_name: str


class LLMProvider(Protocol):
    name: str

    def classify(self, parsed: ParsedLog, targets: list[ParsedError]) -> LLMResponse: ...
