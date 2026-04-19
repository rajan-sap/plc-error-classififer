"""Google Gemini provider — the live LLM I built and tested against.

Set LLM_PROVIDER=google (or just put GOOGLE_API_KEY in .env — the
factory auto-detects). Defaults to Gemini 3.1 Flash Lite for the latency
budget; override with GOOGLE_MODEL.

Structured output is enforced with an INLINE OpenAPI schema. Gemini's
validator rejects $ref, which Pydantic's auto-generated schema uses for
nested models, so we hand-roll the dict instead. Annoying but reliable.
"""
from __future__ import annotations

import json
import os

from src.classifier.prompts import build_system_prompt, build_user_prompt
from src.llm.provider import LLMResponse
from src.parser.models import ParsedError, ParsedLog

DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"


def _response_schema(targets: list[ParsedError]) -> dict:
    """Build the inline OpenAPI schema constraining Gemini's output."""
    # Mirrors the LLM-facing fields of LLMResponse; provider_name is set on our side.
    return {
        "type": "object",
        "required": ["classifications"],
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["error_id", "severity", "fix_complexity", "root_cause", "suggestions"],
                    "properties": {
                        "error_id":       {"type": "string", "enum": [t.id for t in targets]},
                        "severity":       {"type": "string", "enum": ["blocking", "warning", "info"]},
                        "fix_complexity": {"type": "string", "enum": ["trivial", "moderate", "complex"]},
                        "root_cause":     {"type": "string"},
                        "suggestions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["title", "rationale", "raw_confidence"],
                                "properties": {
                                    "title":           {"type": "string"},
                                    "rationale":       {"type": "string"},
                                    "before_snippet":  {"type": "string"},
                                    "after_snippet":   {"type": "string"},
                                    "raw_confidence":  {"type": "number"},
                                },
                            },
                        },
                    },
                },
            },
        },
    }


class GoogleProvider:
    name = "google"

    def __init__(self, model: str | None = None) -> None:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set. Put it in .env "
                "(loaded automatically) or export it. Or use LLM_PROVIDER=mock "
                "for offline runs."
            )
        # Lazy import — only pull in google-genai if this provider is selected.
        from google import genai
        self._client = genai.Client(api_key=api_key)
        self._model = model or os.environ.get("GOOGLE_MODEL", DEFAULT_MODEL)

    def classify(self, parsed: ParsedLog, targets: list[ParsedError]) -> LLMResponse:
        """Send ``targets`` to Gemini and return the structured response."""
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=build_system_prompt(),
            response_mime_type="application/json",
            response_schema=_response_schema(targets),
            temperature=0.0,
        )
        response = self._client.models.generate_content(
            model=self._model,
            contents=build_user_prompt(parsed, targets),
            config=config,
        )
        payload = json.loads(response.text)
        payload["provider_name"] = self.name
        return LLMResponse.model_validate(payload)
