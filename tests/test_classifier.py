"""Classifier tests — end-to-end through the offline ``MockProvider``.

The mock returns hand-coded responses for the curated categories, so we
can assert exact severity / complexity / suggestion values.
"""
from __future__ import annotations

from src.classifier import classify
from src.llm.mock import MockProvider
from src.parser.models import Complexity, Severity, Stage


def test_constant_error_classified_blocking_trivial(constant_error_log: str) -> None:
    results, _ = classify(constant_error_log, MockProvider())
    primary = results[0]

    assert primary.parsed.category == "matiec.constant_assignment"
    assert primary.stage == Stage.IEC_COMPILATION
    assert primary.severity == Severity.BLOCKING
    assert primary.fix_complexity == Complexity.TRIVIAL
    # The mock supplies a curated suggestion with both before/after XML snippets.
    assert any(s.before_snippet and s.after_snippet for s in primary.suggestions)
    # Derived confidence blends parser + LLM signals — must NOT just equal the LLM raw max.
    assert primary.classification_confidence != max(s.confidence for s in primary.suggestions)


def test_empty_project_classified_blocking_moderate(empty_project_log: str) -> None:
    results, _ = classify(empty_project_log, MockProvider())
    primary = results[0]

    assert primary.parsed.category == "python.attribute_error"
    assert primary.stage == Stage.CODE_GENERATION
    assert primary.severity == Severity.BLOCKING
    assert primary.fix_complexity == Complexity.MODERATE


def test_primary_root_listed_first_in_response(constant_error_log: str) -> None:
    results, parsed = classify(constant_error_log, MockProvider())
    # Engineer should see the actionable error at index 0; noise / downstream follow.
    assert results[0].parsed.id in parsed.cascade.primary_root_ids
    assert results[0].severity == Severity.BLOCKING
    # Everything after the primary root should be info-level (noise or downstream).
    for r in results[1:]:
        assert r.severity == Severity.INFO
