"""Classifier orchestrator.

Pipeline shape:

    parse(log) -> ParsedLog
        |
        +-- primary roots          -> ONE call to the LLM
        +-- noise / downstream     -> synthesised locally (no LLM call)

Why split it: the LLM only adds value on root errors. Noise (the recurring
XSD warning) and downstream symptoms ("Cannot build", "PLC code generation
failed!") have obvious classifications — sending them through the LLM
would burn tokens and add latency for no quality gain.
"""
from __future__ import annotations

from src.api.schemas import ClassifiedError, Suggestion
from src.classifier.confidence import derive_confidence
from src.llm.provider import LLMClassification, LLMProvider, LLMSuggestion
from src.parser import parse
from src.parser.cascade import GENERIC_DOWNSTREAM_CATEGORIES
from src.parser.models import Complexity, ParsedError, ParsedLog, Severity


def classify(log_text: str, provider: LLMProvider) -> tuple[list[ClassifiedError], ParsedLog]:
    """Parse, classify and return ``(classified_errors, parsed_log)``.

    Sends only primary roots to the LLM provider. Noise and downstream
    symptoms are synthesised locally with no LLM call.
    """
    parsed = parse(log_text)
    primary_roots = parsed.primary_errors()

    # One LLM call per request, only for the primary roots.
    if primary_roots:
        llm_response = provider.classify(parsed, primary_roots)
        cls_by_id = {c.error_id: c for c in llm_response.classifications}
    else:
        cls_by_id = {}

    primary_ids = set(parsed.cascade.primary_root_ids)
    out: list[ClassifiedError] = []

    # Primary roots first — engineer should see the actionable error at the top.
    for err in parsed.errors:
        if err.id not in primary_ids:
            continue
        cls = cls_by_id.get(err.id)
        out.append(_wrap(err, cls) if cls else _synth_unknown(err))

    # Then everything else, in log order, synthesised without the LLM.
    for err in parsed.errors:
        if err.id in primary_ids:
            continue
        if err.is_noise:
            out.append(_synth_noise(err))
        elif err.category in GENERIC_DOWNSTREAM_CATEGORIES:
            out.append(_synth_downstream(err, primary_ids))
        else:
            out.append(_synth_unknown(err))

    return out, parsed


def _wrap(err: ParsedError, cls: LLMClassification) -> ClassifiedError:
    """Wrap a real LLM classification with derived confidence."""
    return ClassifiedError(
        parsed=err,
        severity=cls.severity,
        stage=err.stage,
        fix_complexity=cls.fix_complexity,
        root_cause=cls.root_cause,
        suggestions=[_to_suggestion(s) for s in cls.suggestions],
        classification_confidence=derive_confidence(err, cls),
    )


def _to_suggestion(s: LLMSuggestion) -> Suggestion:
    """Convert an :class:`LLMSuggestion` into the API-facing :class:`Suggestion`."""
    return Suggestion(
        title=s.title,
        rationale=s.rationale,
        before_snippet=s.before_snippet,
        after_snippet=s.after_snippet,
        confidence=s.raw_confidence,
    )


def _synth_noise(err: ParsedError) -> ClassifiedError:
    """Build a canned info-level response for a noise event (no LLM call)."""
    return ClassifiedError(
        parsed=err,
        severity=Severity.INFO,
        stage=err.stage,
        fix_complexity=Complexity.TRIVIAL,
        root_cause=(
            "Recurring pipeline noise. Both supplied OTee fixtures reproduce this "
            "warning despite having structurally valid XML, so it's a false-positive."
        ),
        suggestions=[Suggestion(
            title="Ignore — recurring pipeline noise",
            rationale="Suppress at the dashboard or filter client-side.",
            confidence=0.95,
        )],
        classification_confidence=0.95,
    )


def _synth_downstream(err: ParsedError, primary_ids: set[str]) -> ClassifiedError:
    """Build a canned info-level response for a downstream symptom (no LLM call)."""
    primary_ref = next(iter(primary_ids), "the primary error")
    return ClassifiedError(
        parsed=err,
        severity=Severity.INFO,
        stage=err.stage,
        fix_complexity=Complexity.TRIVIAL,
        root_cause=(
            f"Downstream symptom of {primary_ref}. The build-failed tail messages "
            "don't diagnose anything on their own; fixing the primary clears them."
        ),
        suggestions=[Suggestion(
            title=f"Fix the primary root cause ({primary_ref})",
            rationale="Resolving the upstream error eliminates this symptom.",
            confidence=0.9,
        )],
        classification_confidence=0.9,
    )


def _synth_unknown(err: ParsedError) -> ClassifiedError:
    """Build a low-confidence fallback when no classification is available."""
    # Rare in practice — usually only happens on a provider error.
    return ClassifiedError(
        parsed=err,
        severity=Severity.WARNING,
        stage=err.stage,
        fix_complexity=Complexity.MODERATE,
        root_cause="No structured handler matched. Inspect the raw error context manually.",
        suggestions=[Suggestion(
            title="Inspect the raw error",
            rationale=(
                "Set LLM_PROVIDER=google (or anthropic) for live judgment on unknown "
                "categories, or extend the parser/mock with a curated handler."
            ),
            confidence=0.3,
        )],
        classification_confidence=0.3,
    )
