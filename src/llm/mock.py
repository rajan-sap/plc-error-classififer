"""Test fixture standing in for a live LLM. NOT a production mode.

Lookup is keyed by (stage, category). Hand-coded responses for the 5
categories we exercise in tests. Anything else falls through to a
low-confidence generic so the eval still gets honest signal about where
curated coverage is missing.

Production must use a real provider (google / anthropic). The mock is
here so pytest is deterministic, free, and runs without an API key.
"""
from __future__ import annotations

from src.llm.provider import LLMClassification, LLMResponse, LLMSuggestion
from src.parser.models import Complexity, ParsedError, ParsedLog, Severity, Stage

_CURATED: dict[tuple[Stage, str], dict] = {
    (Stage.IEC_COMPILATION, "matiec.constant_assignment"): {
        "severity": Severity.BLOCKING,
        "fix_complexity": Complexity.TRIVIAL,
        "root_cause": (
            "The target variable is declared inside a `<localVars constant=\"true\">` "
            "block, which makes it read-only under IEC 61131-3. Any assignment to it "
            "is rejected by matiec. Either the variable was misplaced into the "
            "constant block by mistake, or the assignment statement should not be there."
        ),
        "suggestions": [
            {
                "title": "Make the variable non-constant in the XML interface",
                "rationale": (
                    "If the program needs to write to this variable, it must not be "
                    "declared constant. Move it out of the `constant=\"true\"` "
                    "`<localVars>` block, or set the attribute to `\"false\"`."
                ),
                "before": '<localVars constant="true">\n  <variable name="LocalVar1">...</variable>\n</localVars>',
                "after": '<localVars constant="false">\n  <variable name="LocalVar1">...</variable>\n</localVars>',
                "raw_confidence": 0.9,
            },
            {
                "title": "Remove the assignment from the ST body",
                "rationale": (
                    "If the variable is genuinely a constant, the program should "
                    "only read it. Delete the assignment statement."
                ),
                "before": "LocalVar1 := LocalVar0;",
                "after": "(* assignment removed; LocalVar1 is constant *)",
                "raw_confidence": 0.7,
            },
        ],
    },
    (Stage.CODE_GENERATION, "python.attribute_error"): {
        "severity": Severity.BLOCKING,
        "fix_complexity": Complexity.MODERATE,
        "root_cause": (
            "The PLC program has an empty Structured Text body. Beremiz's "
            "PLCGenerator expects at least one statement; the empty `<xhtml:p/>` "
            "element produces a `None` text value, which crashes when `.upper()` "
            "is called at PLCGenerator.py:959. The Python `AttributeError` is the "
            "symptom — the root cause is the empty program body."
        ),
        "suggestions": [
            {
                "title": "Add at least one statement to the program body",
                "rationale": (
                    "The simplest fix: place any valid ST statement (even a no-op "
                    "comment with a semicolon-terminated assignment) inside the "
                    "`<ST>` element so the generator has something to emit."
                ),
                "before": "<ST>\n  <xhtml:p xmlns:xhtml=\"http://www.w3.org/1999/xhtml\"/>\n</ST>",
                "after": "<ST>\n  <xhtml:p xmlns:xhtml=\"http://www.w3.org/1999/xhtml\">(* placeholder *);</xhtml:p>\n</ST>",
                "raw_confidence": 0.85,
            },
            {
                "title": "Validate program bodies before submitting the build",
                "rationale": (
                    "Catch this at edit-time rather than build-time: enforce that "
                    "every POU has a non-empty body in the editor or a pre-build hook."
                ),
                "raw_confidence": 0.6,
            },
        ],
    },
    (Stage.C_COMPILATION, "gcc.implicit_declaration"): {
        "severity": Severity.BLOCKING,
        "fix_complexity": Complexity.TRIVIAL,
        "root_cause": (
            "The C compiler encountered a function call with no prior prototype. "
            "Either a header `#include` is missing, or the function is referenced "
            "before it is declared in the translation unit."
        ),
        "suggestions": [
            {
                "title": "Add the missing #include for the function's header",
                "rationale": "Resolves the implicit declaration by exposing the prototype to the call site.",
                "before": "/* call site */\nfoo(x);",
                "after": "#include \"foo.h\"\n/* call site */\nfoo(x);",
                "raw_confidence": 0.85,
            },
        ],
    },
    (Stage.C_COMPILATION, "gcc.undefined_reference"): {
        "severity": Severity.BLOCKING,
        "fix_complexity": Complexity.MODERATE,
        "root_cause": (
            "The linker cannot find the symbol's definition. Either the source "
            "file defining it is not part of the link, or the library providing "
            "it is missing from the link command."
        ),
        "suggestions": [
            {
                "title": "Ensure the defining .c file is in the build sources",
                "rationale": "If the symbol is defined locally, the .c file must be in the link.",
                "raw_confidence": 0.7,
            },
            {
                "title": "Add the missing -l<library> to the link flags",
                "rationale": "If the symbol comes from an external library, link against it.",
                "raw_confidence": 0.7,
            },
        ],
    },
    (Stage.XML_VALIDATION, "xsd.missing_child_element"): {
        "severity": Severity.INFO,
        "fix_complexity": Complexity.TRIVIAL,
        "root_cause": (
            "The PLCopen XSD validator complains about an empty `<data>` element "
            "in the project XML. In the OTee build pipeline this is a recurring "
            "false-positive: the XML is structurally valid PLCopen but the schema "
            "check is overly strict. It does not block the build."
        ),
        "suggestions": [
            {
                "title": "Ignore — recurring pipeline noise",
                "rationale": (
                    "This warning fires for every project regardless of true "
                    "validity. Suppress it in your dashboard or filter it client-side."
                ),
                "raw_confidence": 0.95,
            },
        ],
    },
}

# Fallback for unknown (stage, category) combinations.
_FALLBACK = {
    "severity": Severity.WARNING,
    "fix_complexity": Complexity.MODERATE,
    "root_cause": (
        "No curated mock response is registered for this error category. The "
        "live LLM provider would inspect the message, source location, and "
        "context to derive a root cause."
    ),
    "suggestions": [
        {
            "title": "Inspect the error context manually",
            "rationale": (
                "Without a curated handler, the mock cannot offer a specific fix. "
                "Configure LLM_PROVIDER=anthropic for live judgment."
            ),
            "raw_confidence": 0.3,
        },
    ],
}


class MockProvider:
    name = "mock"

    def classify(self, parsed: ParsedLog, targets: list[ParsedError]) -> LLMResponse:
        """Look up a curated response per target by ``(stage, category)``."""
        classifications: list[LLMClassification] = []
        for err in targets:
            template = _CURATED.get((err.stage, err.category), _FALLBACK)
            classifications.append(
                LLMClassification(
                    error_id=err.id,
                    severity=template["severity"],
                    fix_complexity=template["fix_complexity"],
                    root_cause=template["root_cause"],
                    suggestions=[
                        LLMSuggestion(
                            title=s["title"],
                            rationale=s["rationale"],
                            before_snippet=s.get("before"),
                            after_snippet=s.get("after"),
                            raw_confidence=s["raw_confidence"],
                        )
                        for s in template["suggestions"]
                    ],
                )
            )
        return LLMResponse(classifications=classifications, provider_name=self.name)
