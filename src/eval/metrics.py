"""Per-case eval results and aggregate metrics.

One :class:`CaseResult` per case (with ``*_match`` properties for the
four classification fields), one :class:`Aggregate` that holds the lot
and computes accuracy, latency percentiles, and per-stage groupings.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from src.parser.models import Stage


@dataclass
class CaseResult:
    name: str
    expected_category: str
    expected_stage: Stage
    expected_severity: str
    expected_complexity: str
    actual_category: str | None
    actual_stage: str | None
    actual_severity: str | None
    actual_complexity: str | None
    actual_confidence: float | None
    noise_ok: bool
    cascade_ok: bool
    latency_ms: float
    # Manual quality labels for the curated suggestions (see eval/suggestion_quality.json).
    # ``None`` for cases that don't have a labelled curated entry (i.e. the fallback cohort).
    suggestion_quality_scores: list[int] | None = None

    @property
    def category_match(self) -> bool:
        """``True`` if the predicted category matches ground truth."""
        return self.actual_category == self.expected_category

    @property
    def stage_match(self) -> bool:
        """``True`` if the predicted stage matches ground truth."""
        return self.actual_stage == self.expected_stage.value

    @property
    def severity_match(self) -> bool:
        """``True`` if the predicted severity matches ground truth."""
        return self.actual_severity == self.expected_severity

    @property
    def complexity_match(self) -> bool:
        """``True`` if the predicted fix complexity matches ground truth."""
        return self.actual_complexity == self.expected_complexity


@dataclass
class Aggregate:
    """Aggregate metrics over a list of :class:`CaseResult`."""

    results: list[CaseResult] = field(default_factory=list)

    def accuracy(self, key: str) -> float:
        """Fraction matching on ``key`` (one of ``category | stage | severity | complexity``)."""
        if not self.results:
            return 0.0
        attr = f"{key}_match"
        return sum(getattr(r, attr) for r in self.results) / len(self.results)

    def noise_demotion_rate(self) -> float:
        """Fraction of cases where the parser's noise count matched ground truth."""
        if not self.results:
            return 0.0
        return sum(r.noise_ok for r in self.results) / len(self.results)

    def cascade_accuracy(self) -> float:
        """Fraction of cases where the cascade picked the correct primary root."""
        if not self.results:
            return 0.0
        return sum(r.cascade_ok for r in self.results) / len(self.results)

    def latency_p50(self) -> float:
        """Median per-case latency in milliseconds."""
        return statistics.median(r.latency_ms for r in self.results) if self.results else 0.0

    def latency_p95(self) -> float:
        """95th-percentile per-case latency in milliseconds."""
        if not self.results:
            return 0.0
        sorted_ms = sorted(r.latency_ms for r in self.results)
        return sorted_ms[max(0, int(0.95 * (len(sorted_ms) - 1)))]

    def by_stage(self) -> dict[str, list[CaseResult]]:
        """Group results by expected stage."""
        out: dict[str, list[CaseResult]] = {}
        for r in self.results:
            out.setdefault(r.expected_stage.value, []).append(r)
        return out

    def avg_suggestion_quality(self) -> float | None:
        """Average of all individual suggestion quality scores; ``None`` if no labels exist."""
        scores = [
            s
            for r in self.results
            if r.suggestion_quality_scores
            for s in r.suggestion_quality_scores
        ]
        return sum(scores) / len(scores) if scores else None
