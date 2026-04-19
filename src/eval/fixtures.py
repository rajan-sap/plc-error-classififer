"""Hand-curated ground truth for the two real OTee fixtures.

Plus a top-level helper that combines them with the synthetic generator
output for the runner.
"""
from __future__ import annotations

from pathlib import Path

from src.eval.generator import GeneratedCase, generate_cases
from src.parser.models import Complexity, Severity, Stage

SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


def real_fixtures() -> list[GeneratedCase]:
    """Return ``GeneratedCase`` entries for the two real OTee samples."""
    return [
        GeneratedCase(
            name="real_constant_error",
            log_text=(SAMPLES_DIR / "constant_error.txt").read_text(),
            expected_primary_category="matiec.constant_assignment",
            expected_primary_stage=Stage.IEC_COMPILATION,
            expected_primary_severity=Severity.BLOCKING,
            expected_primary_complexity=Complexity.TRIVIAL,
            expected_noise_count=1,
        ),
        GeneratedCase(
            name="real_empty_project",
            log_text=(SAMPLES_DIR / "empty_project.txt").read_text(),
            expected_primary_category="python.attribute_error",
            expected_primary_stage=Stage.CODE_GENERATION,
            expected_primary_severity=Severity.BLOCKING,
            expected_primary_complexity=Complexity.MODERATE,
            expected_noise_count=1,
        ),
    ]


def all_cases() -> list[GeneratedCase]:
    """Return real + synthetic cases for the eval runner."""
    return real_fixtures() + generate_cases()
