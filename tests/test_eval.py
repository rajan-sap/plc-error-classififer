"""Sanity tests for the evaluation framework.

The brief's Deliverables section explicitly lists "test suite for parser,
classifier, and evaluation framework" — these three tests cover the
framework's surface area without burning time on its internals.
"""
from __future__ import annotations

from pathlib import Path

from src.eval.generator import generate_cases
from src.eval.runner import run


def test_generator_produces_at_least_20_cases() -> None:
    assert len(generate_cases()) >= 20


def test_generator_covers_all_four_pipeline_stages() -> None:
    stages = {c.expected_primary_stage.value for c in generate_cases()}
    assert {"xml_validation", "code_generation", "iec_compilation", "c_compilation"}.issubset(stages)


def test_runner_writes_report_and_fixtures(tmp_path: Path, monkeypatch) -> None:
    # Redirect EVAL_DIR so the test doesn't stomp on the committed report.
    import src.eval.runner as runner_mod

    monkeypatch.setattr(runner_mod, "EVAL_DIR", tmp_path)
    monkeypatch.setattr(runner_mod, "QUALITY_FILE", tmp_path / "quality.json")
    agg = runner_mod.run()
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "fixtures.json").exists()
    assert agg.results
    # Generator output should always parse cleanly — no detected noise mismatches.
    assert agg.noise_demotion_rate() == 1.0
