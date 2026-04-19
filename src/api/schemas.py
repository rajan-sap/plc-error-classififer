"""HTTP request/response shapes. These are the contract the API exposes."""
from __future__ import annotations

from pydantic import BaseModel, Field

from src.parser.models import Complexity, ParsedError, Severity, Stage


class Suggestion(BaseModel):
    title: str
    rationale: str
    before_snippet: str | None = None
    after_snippet: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ClassifiedError(BaseModel):
    parsed: ParsedError
    severity: Severity
    stage: Stage
    fix_complexity: Complexity
    root_cause: str
    suggestions: list[Suggestion]
    classification_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Derived confidence in the OVERALL classification (severity, "
            "complexity, root cause). Blends parser source-location quality, "
            "category specificity, and LLM raw confidence. NOT the same as "
            "Suggestion.confidence, which is per-suggestion and LLM-self-reported."
        ),
    )


class ClassifyRequest(BaseModel):
    log_text: str = Field(min_length=1, description="Raw multi-stage build log output.")
    source_xml: str | None = Field(
        default=None,
        description="Optional PLCopen XML the build was run against, for richer context.",
    )


class ClassifyResponse(BaseModel):
    errors: list[ClassifiedError]
    primary_root_ids: list[str]
    provider: str
    latency_ms: float
