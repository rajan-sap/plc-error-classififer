"""Derived confidence score.

LLM Models are bad at calibrating their own confidence — "I'm 90% sure" can
mean anything. So instead of trusting the LLM's self-reported number, we
blend three signals:

    structure   (40%)  — did the parser get a precise file:line?
    specificity (30%)  — did we hit a known category, or fall back?
    llm_avg     (30%)  — average of the LLM's per-suggestion raw_confidence

A clean parser hit on a known category lifts the floor even when the LLM
is uncertain; a vague generic error caps the ceiling even if the LLM is
over-eager. Tuneable in one place if calibration drifts.
"""
from __future__ import annotations

from src.llm.provider import LLMClassification
from src.parser.models import ParsedError

# Categories the system has structural recognition for.
# Anything not in here is treated as a generic fallback for the specificity score.
_KNOWN_CATEGORIES: set[str] = {
    "matiec.constant_assignment",
    "matiec.undefined_symbol",
    "matiec.type_mismatch",
    "matiec.syntax_error",
    "python.attribute_error",
    "python.type_error",
    "python.value_error",
    "python.key_error",
    "gcc.implicit_declaration",
    "gcc.undefined_reference",
    "gcc.syntax_error",
    "gcc.missing_include",
    "gcc.redefinition",
    "xsd.missing_child_element",
}


def derive_confidence(err: ParsedError, cls: LLMClassification) -> float:
    """Compute a derived confidence score in ``[0.0, 1.0]``.

    Blends parser-side structure quality, category specificity, and the
    LLM's average raw confidence. See module docstring for the weights.
    """
    sl = err.source_location
    if sl.file and sl.line:
        structure = 1.0
    elif sl.file or sl.line:
        structure = 0.7
    else:
        structure = 0.4

    if err.category in _KNOWN_CATEGORIES:
        specificity = 1.0
    elif err.category.endswith(".error"):
        specificity = 0.6
    else:
        specificity = 0.4

    if cls.suggestions:
        llm_avg = sum(s.raw_confidence for s in cls.suggestions) / len(cls.suggestions)
    else:
        llm_avg = 0.3

    score = 0.4 * structure + 0.3 * specificity + 0.3 * llm_avg
    return round(max(0.0, min(1.0, score)), 3)
