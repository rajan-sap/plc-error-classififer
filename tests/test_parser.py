"""Parser tests — covering the three behaviours that separate a real parser
from "regex over `error:`": reading past the lying ``Warning:`` prefix,
recognising tracebacks, and demoting the recurring XSD false-positive.
"""
from __future__ import annotations

from src.parser import parse
from src.parser.models import Stage


def test_parses_matiec_constant_error_with_correct_source_location(constant_error_log: str) -> None:
    parsed = parse(constant_error_log)
    matiec = next(e for e in parsed.errors if e.category == "matiec.constant_assignment")

    assert matiec.stage == Stage.IEC_COMPILATION
    # The wrapper script adds an outer "Warning:" prefix; the regex must read
    # the INNER verdict ("error:") so this is recognised as blocking.
    assert matiec.message.startswith("Assignment to CONSTANT")
    assert matiec.is_noise is False
    assert matiec.source_location.file == "plc.st"
    assert matiec.source_location.line == 30
    assert matiec.source_location.column == 4
    assert matiec.source_location.end_column == 12


def test_parses_python_traceback_into_attribute_error(empty_project_log: str) -> None:
    parsed = parse(empty_project_log)
    py = next(e for e in parsed.errors if e.category == "python.attribute_error")

    assert py.stage == Stage.CODE_GENERATION
    assert "AttributeError" in py.message
    assert "NoneType" in py.message
    # Source location comes from the LAST frame — the one that actually crashed.
    assert py.source_location.file == "PLCGenerator.py"
    assert py.source_location.line == 959


def test_demotes_recurring_xsd_warning_as_noise(constant_error_log: str, empty_project_log: str) -> None:
    # Both supplied OTee fixtures contain this warning despite valid XML.
    for log in (constant_error_log, empty_project_log):
        xsd = [e for e in parse(log).errors if e.category.startswith("xsd.")]
        assert len(xsd) == 1
        assert xsd[0].is_noise is True


def test_cascade_picks_real_failure_over_noise_and_symptoms(constant_error_log: str) -> None:
    parsed = parse(constant_error_log)
    primary_id = parsed.cascade.primary_root_ids[0]
    primary = next(e for e in parsed.errors if e.id == primary_id)

    # The primary should be the actual matiec failure, NOT the XSD noise or
    # the generic "Cannot build" / "PLC code generation failed" tail messages.
    assert primary.category == "matiec.constant_assignment"
    downstream_cats = {e.category for e in parsed.errors if e.id in parsed.cascade.downstream[primary_id]}
    assert "build.cannot_build" in downstream_cats
    assert "build.code_generation_failed" in downstream_cats


def test_cascade_supports_multiple_independent_primary_roots() -> None:
    # Two independent matiec failures in the same iec_compilation stage
    # should both surface as primaries (not one squashed under the other).
    log = (
        "[17:05:55]: Building project...\n"
        "Compiling IEC Program into C code...\n"
        '"/root/beremiz/matiec/iec2c" -f -l -p\n'
        "Warning: /tmp/build/plc.st:30-4..30-12: error: Assignment to CONSTANT variables is not allowed.\n"
        "Warning: In section: PROGRAM program0\n"
        "Warning: 1 error(s) found. Bailing out!\n"
        "Warning: /tmp/build/plc.st:88-2..88-14: error: type mismatch: expected BOOL, got INT\n"
        "Warning: In section: PROGRAM program1\n"
        "Warning: 1 error(s) found. Bailing out!\n"
        "Error: PLC code generation failed !\n"
    )
    parsed = parse(log)
    primaries = parsed.cascade.primary_root_ids

    assert len(primaries) == 2
    primary_cats = {next(e for e in parsed.errors if e.id == pid).category for pid in primaries}
    assert primary_cats == {"matiec.constant_assignment", "matiec.type_mismatch"}


def test_handles_malformed_input_without_crashing() -> None:
    # The brief calls out "Basic error handling for malformed logs" — make
    # sure parse() never raises, even on garbage input.
    for log in ("", "no errors here\n", "blah\n\x00\x01garbage\n  Traceback (most recent call last):\n  no frames\n"):
        parsed = parse(log)
        assert isinstance(parsed.errors, list)
