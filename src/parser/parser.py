"""Top-level parser orchestrator."""
from __future__ import annotations

from src.parser.cascade import build_cascade
from src.parser.extractors import (
    extract_gcc_errors,
    extract_generic_failures,
    extract_matiec_errors,
    extract_python_tracebacks,
    extract_xsd_warnings,
)
from src.parser.models import ParsedError, ParsedLog, Stage
from src.parser.stages import stage_at

EXTRACTORS = (
    extract_xsd_warnings,
    extract_matiec_errors,
    extract_python_tracebacks,
    extract_gcc_errors,
    extract_generic_failures,
)


def parse(log_text: str) -> ParsedLog:
    """Parse a raw build log into a :class:`ParsedLog`.

    Runs every extractor against ``log_text``, refines stage assignments
    by log position, sorts events by line, assigns stable ids
    (``err_000``, ``err_001``, ...) and resolves the cascade.
    """
    lines = log_text.splitlines()

    errors: list[ParsedError] = []
    for fn in EXTRACTORS:
        errors.extend(fn(lines))

    # Some extractors leave stage=UNKNOWN; use log position to fill them in.
    for e in errors:
        if e.stage == Stage.UNKNOWN:
            e.stage = stage_at(e.log_line_start, lines)

    errors.sort(key=lambda e: (e.log_line_start, e.log_line_end))
    for i, e in enumerate(errors):
        e.id = f"err_{i:03d}"

    return ParsedLog(errors=errors, cascade=build_cascade(errors), raw_log=log_text)
