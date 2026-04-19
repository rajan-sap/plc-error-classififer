"""Eval runner.

Executes every case through the classifier (with ``MockProvider`` for
reproducibility), computes metrics, writes ``eval/report.md`` and
``eval/fixtures.json``.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from src.classifier import classify
from src.eval.fixtures import all_cases
from src.eval.generator import GeneratedCase
from src.eval.metrics import Aggregate, CaseResult
from src.eval.report import render_report
from src.llm.mock import MockProvider
from src.parser.models import ParsedLog

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "eval"
QUALITY_FILE = EVAL_DIR / "suggestion_quality.json"


def _load_quality_labels() -> dict[str, list[int]]:
    """Load hand-rated suggestion quality labels; missing file is fine (no labels)."""
    if not QUALITY_FILE.exists():
        return {}
    raw = json.loads(QUALITY_FILE.read_text())
    # Drop the "_comment_*" keys; only keep "<stage>/<category>" -> list[int].
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, list)}


def _primary_category(parsed: ParsedLog) -> str | None:
    """Return the category of the primary root, or ``None`` if there isn't one."""
    if not parsed.cascade.primary_root_ids:
        return None
    primary_id = parsed.cascade.primary_root_ids[0]
    primary = next((e for e in parsed.errors if e.id == primary_id), None)
    return primary.category if primary else None


def _run_one(case: GeneratedCase, quality_labels: dict[str, list[int]]) -> CaseResult:
    """Run one case through the classifier and compare to ground truth."""
    t0 = time.perf_counter()
    results, parsed = classify(case.log_text, MockProvider())
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    primary = results[0] if results else None
    noise_count = sum(1 for e in parsed.errors if e.is_noise)
    quality_key = f"{case.expected_primary_stage.value}/{case.expected_primary_category}"

    return CaseResult(
        name=case.name,
        expected_category=case.expected_primary_category,
        expected_stage=case.expected_primary_stage,
        expected_severity=case.expected_primary_severity.value,
        expected_complexity=case.expected_primary_complexity.value,
        actual_category=primary.parsed.category if primary else None,
        actual_stage=primary.stage.value if primary else None,
        actual_severity=primary.severity.value if primary else None,
        actual_complexity=primary.fix_complexity.value if primary else None,
        actual_confidence=primary.classification_confidence if primary else None,
        noise_ok=(noise_count == case.expected_noise_count),
        cascade_ok=(_primary_category(parsed) == case.expected_primary_category),
        latency_ms=elapsed_ms,
        suggestion_quality_scores=quality_labels.get(quality_key),
    )


def _write_fixtures_json(cases: list[GeneratedCase]) -> None:
    """Dump the ground-truth labels to ``eval/fixtures.json``."""
    payload = [
        {
            "name": c.name,
            "expected_primary_category": c.expected_primary_category,
            "expected_primary_stage": c.expected_primary_stage.value,
            "expected_primary_severity": c.expected_primary_severity.value,
            "expected_primary_complexity": c.expected_primary_complexity.value,
            "expected_noise_count": c.expected_noise_count,
        }
        for c in cases
    ]
    EVAL_DIR.mkdir(exist_ok=True)
    (EVAL_DIR / "fixtures.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run() -> Aggregate:
    """Run every case, write the report + fixtures, return the aggregate."""
    cases = all_cases()
    quality_labels = _load_quality_labels()
    _write_fixtures_json(cases)
    agg = Aggregate(results=[_run_one(c, quality_labels) for c in cases])
    EVAL_DIR.mkdir(exist_ok=True)
    (EVAL_DIR / "report.md").write_text(render_report(agg), encoding="utf-8")
    return agg


if __name__ == "__main__":
    agg = run()
    n = len(agg.results)
    pct = lambda x: f"{x * 100:.1f}%"  # noqa: E731
    print(f"Ran {n} cases")
    print(f"  Stage accuracy:      {pct(agg.accuracy('stage'))}")
    print(f"  Category accuracy:   {pct(agg.accuracy('category'))}")
    print(f"  Severity accuracy:   {pct(agg.accuracy('severity'))}")
    print(f"  Complexity accuracy: {pct(agg.accuracy('complexity'))}")
    print(f"  Cascade accuracy:    {pct(agg.cascade_accuracy())}")
    print(f"  Noise demotion:      {pct(agg.noise_demotion_rate())}")
    print(f"  Latency p50 / p95:   {agg.latency_p50():.2f} / {agg.latency_p95():.2f} ms")
    print(f"Wrote {EVAL_DIR / 'report.md'}")
