"""Anthropic Claude provider — second live LLM option.

Set ``LLM_PROVIDER=anthropic`` and put ``ANTHROPIC_API_KEY`` in
``.env``. Defaults to Claude Haiku 4.5 for the latency budget.

Structured output is enforced via forced tool-use: declare a
``submit_classifications`` tool whose ``input_schema`` mirrors
:class:`LLMResponse`, force the model to call it, parse
``tool_use.input`` straight into Pydantic. More robust than asking for
JSON in prose.

The brief explicitly lists Anthropic as one of the allowed providers,
alongside OpenAI and open-source models. Pick this provider over
Google if you'd rather not depend on Gemini for the live path.
"""
from __future__ import annotations

import os

from src.classifier.prompts import build_system_prompt, build_user_prompt
from src.llm.provider import LLMResponse
from src.parser.models import ParsedError, ParsedLog

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _tool_schema(targets: list[ParsedError]) -> dict:
    """Build the tool-use schema that constrains Claude's output."""
    return {
        "name": "submit_classifications",
        "description": "Submit one classification per primary-root error.",
        "input_schema": {
            "type": "object",
            "required": ["classifications"],
            "properties": {
                "classifications": {
                    "type": "array",
                    "minItems": len(targets),
                    "maxItems": len(targets),
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
                                "minItems": 1,
                                "maxItems": 3,
                                "items": {
                                    "type": "object",
                                    "required": ["title", "rationale", "raw_confidence"],
                                    "properties": {
                                        "title":           {"type": "string"},
                                        "rationale":       {"type": "string"},
                                        "before_snippet":  {"type": "string"},
                                        "after_snippet":   {"type": "string"},
                                        "raw_confidence":  {"type": "number", "minimum": 0.0, "maximum": 1.0},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    }


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str | None = None) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Either export it or use "
                "LLM_PROVIDER=mock (the default) to run offline."
            )
        # Lazy import — only pull in the SDK if this provider is selected.
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

    def classify(self, parsed: ParsedLog, targets: list[ParsedError]) -> LLMResponse:
        """Send ``targets`` to Claude and return the structured response."""
        message = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=build_system_prompt(),
            tools=[_tool_schema(targets)],
            tool_choice={"type": "tool", "name": "submit_classifications"},
            messages=[{"role": "user", "content": build_user_prompt(parsed, targets)}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "submit_classifications":
                payload = dict(block.input)
                payload["provider_name"] = self.name
                return LLMResponse.model_validate(payload)
        raise RuntimeError("Anthropic response did not contain the expected tool_use block.")
