"""Synthetic error generator.

Produces realistic-looking build logs with ground-truth labels for the
eval framework. The shape of each generated log mirrors the real OTee
fixtures: build header, optional XSD noise, stage transition, error
block, optional generic failure tail.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.parser.models import Complexity, Severity, Stage


@dataclass
class GeneratedCase:
    name: str
    log_text: str
    expected_primary_category: str
    expected_primary_stage: Stage
    expected_primary_severity: Severity
    expected_primary_complexity: Complexity
    expected_noise_count: int = 1


# --- Log-fragment builders --------------------------------------------------

def _prefix(timestamp: str = "17:05:55") -> str:
    """Build the shell-wrapper banner that opens every real OTee log."""
    return (
        f"[{timestamp}]: Building project...\n"
        f"[{timestamp}]: Cannot build project.\n"
        f"[{timestamp}]: Cannot build project."
    )


def _xsd_noise(xml_line: int = 43) -> str:
    """Build the recurring PLCopen XSD false-positive warning."""
    return (
        f"stdout: Warning: PLC XML file doesn't follow XSD schema at line {xml_line}:\n"
        f"Element '{{http://www.plcopen.org/xml/tc6_0201}}data': "
        f"Missing child element(s). Expected is one of ( {{*}}*, * )."
        f"Start build in /tmp/.tmpSyn/build"
    )


def _code_gen_header() -> str:
    """Build the Beremiz code-generation banner."""
    return (
        "Generating SoftPLC IEC-61131 ST/IL/SFC code...\n"
        "Collecting data types\n"
        "Collecting POUs\n"
        "Generate POU program0\n"
        "Generate Config(s)"
    )


def _iec_header() -> str:
    """Build the matiec/iec2c invocation banner."""
    return (
        "Compiling IEC Program into C code...\n"
        "0.000s 0.101s 0.201s 0.301s\n"
        '"/root/beremiz/matiec/iec2c" -f -l -p -I "/root/beremiz/matiec/lib" '
        '-T "/tmp/.tmpSyn/build" "/tmp/.tmpSyn/build/plc.st"\n'
        "Warning: exited with status 1 (pid 187)\n"
        "0.342s"
    )


def _matiec_error(line: int, col_s: int, col_e: int, msg: str) -> str:
    """Build a matiec error block (error line + section / source / bailing-out)."""
    return (
        f"Warning: /tmp/.tmpSyn/build/plc.st:{line}-{col_s}..{line}-{col_e}: error: {msg}\n"
        f"Warning: In section: PROGRAM program0\n"
        f"Warning: 1 error(s) found. Bailing out!\n"
        f"Warning:"
    )


def _matiec_tail() -> str:
    """Build the generic failure tail emitted after a matiec failure."""
    return "Error: Error : IEC to C compiler returned 1\nError: PLC code generation failed !"


def _python_traceback(
    last_file: str, last_line: int, last_func: str, exc_cls: str, exc_msg: str
) -> str:
    """Build a Beremiz Python traceback ending with ``exc_cls: exc_msg``."""
    return (
        "stderr: Traceback (most recent call last):\n"
        '  File "/root/beremiz/Beremiz_cli.py", line 130, in <module>\n'
        "    cli()\n"
        f'  File "/root/beremiz/{last_file}", line {last_line}, in {last_func}\n'
        "    do_something()\n"
        f"{exc_cls}: {exc_msg}"
    )


def _gcc_error(file: str, line: int, col: int, msg: str) -> str:
    """Build a gcc error in standard ``<file>.c:LINE:COL: error:`` format."""
    return (
        "Compiling generated code into native code...\n"
        f"gcc -c {file} -o {file.replace('.c', '.o')}\n"
        f"{file}:{line}:{col}: error: {msg}"
    )


# --- Full-log builders (one per error pattern) -----------------------------

def _wrap(*sections: str, with_xsd: bool = True, xml_line: int = 43) -> str:
    """Concatenate the prefix, optional XSD noise, and supplied sections."""
    parts = [_prefix()]
    if with_xsd:
        parts.append(_xsd_noise(xml_line))
    parts.extend(sections)
    return "\n".join(parts)


def _iec_log(error_block: str) -> str:
    """Full log for an iec_compilation failure."""
    return _wrap(_code_gen_header(), _iec_header(), error_block, _matiec_tail())


def _gcc_log(error_block: str) -> str:
    """Full log for a c_compilation failure."""
    return _wrap(_code_gen_header(), _iec_header(), error_block)


def _codegen_log(traceback: str) -> str:
    """Full log for a code_generation failure (Python traceback)."""
    return _wrap(_code_gen_header(), traceback)


def _case(
    name: str,
    log_text: str,
    category: str,
    stage: Stage,
    severity: Severity,
    complexity: Complexity,
) -> GeneratedCase:
    """Construct a :class:`GeneratedCase` with the standard noise count of 1."""
    return GeneratedCase(
        name=name,
        log_text=log_text,
        expected_primary_category=category,
        expected_primary_stage=stage,
        expected_primary_severity=severity,
        expected_primary_complexity=complexity,
    )


# --- The case generator itself ---------------------------------------------

def generate_cases() -> list[GeneratedCase]:
    """Generate ~20 synthetic cases spanning all four pipeline stages."""
    cases: list[GeneratedCase] = []

    # matiec.constant_assignment — covered by the mock provider.
    constant_specs = [
        (30, 4, 12, "Assignment to CONSTANT variables is not allowed."),
        (42, 6, 22, "Assignment to CONSTANT variables is not allowed."),
        (18, 4, 15, "Assignment to CONSTANT variables is not allowed."),
        (101, 8, 20, "Assignment to CONSTANT variables is not allowed."),
    ]
    for i, (line, c1, c2, msg) in enumerate(constant_specs):
        cases.append(_case(
            name=f"syn_matiec_constant_{i}",
            log_text=_iec_log(_matiec_error(line, c1, c2, msg)),
            category="matiec.constant_assignment",
            stage=Stage.IEC_COMPILATION,
            severity=Severity.BLOCKING,
            complexity=Complexity.TRIVIAL,
        ))

    # python.attribute_error — covered by the mock provider.
    py_attr_specs = [
        ("PLCGenerator.py", 959, "ComputeProgram", "AttributeError", "'NoneType' object has no attribute 'upper'"),
        ("PLCGenerator.py", 482, "GenerateProgram", "AttributeError", "'NoneType' object has no attribute 'split'"),
        ("PLCControler.py", 453, "GenerateProgram", "AttributeError", "'list' object has no attribute 'name'"),
    ]
    for i, (f, ln, fn, ec, em) in enumerate(py_attr_specs):
        cases.append(_case(
            name=f"syn_python_attribute_{i}",
            log_text=_codegen_log(_python_traceback(f, ln, fn, ec, em)),
            category="python.attribute_error",
            stage=Stage.CODE_GENERATION,
            severity=Severity.BLOCKING,
            complexity=Complexity.MODERATE,
        ))

    # gcc.implicit_declaration — covered by the mock provider.
    impl_decl_specs = [
        ("plc_main.c", 87, 5, "init_modbus"),
        ("plc_main.c", 142, 9, "register_callback"),
        ("output.c", 23, 12, "compute_crc"),
    ]
    for i, (file, line, col, fn) in enumerate(impl_decl_specs):
        msg = f"implicit declaration of function '{fn}'; did you mean '{fn}_v2'?"
        cases.append(_case(
            name=f"syn_gcc_implicit_decl_{i}",
            log_text=_gcc_log(_gcc_error(file, line, col, msg)),
            category="gcc.implicit_declaration",
            stage=Stage.C_COMPILATION,
            severity=Severity.BLOCKING,
            complexity=Complexity.TRIVIAL,
        ))

    # gcc.undefined_reference — covered by the mock provider.
    undef_ref_specs = [
        ("plc_main.c", 200, 5, "modbus_send"),
        ("output.c", 55, 9, "log_event"),
        ("plc_main.c", 310, 1, "task_dispatch"),
    ]
    for i, (file, line, col, sym) in enumerate(undef_ref_specs):
        cases.append(_case(
            name=f"syn_gcc_undefined_ref_{i}",
            log_text=_gcc_log(_gcc_error(file, line, col, f"undefined reference to '{sym}'")),
            category="gcc.undefined_reference",
            stage=Stage.C_COMPILATION,
            severity=Severity.BLOCKING,
            complexity=Complexity.MODERATE,
        ))

    # XSD-only logs (no real failure) — should classify as info-level noise.
    for i, xml_line in enumerate([43, 7]):
        cases.append(_case(
            name=f"syn_xsd_only_noise_{i}",
            log_text="\n".join([_prefix(), _xsd_noise(xml_line), _code_gen_header()]),
            category="xsd.missing_child_element",
            stage=Stage.XML_VALIDATION,
            severity=Severity.INFO,
            complexity=Complexity.TRIVIAL,
        ))

    # Uncovered categories — mock falls back; ground truth is the IDEAL label,
    # so the eval reveals where the live LLM (or a new curated handler) would help.
    uncovered = [
        ("syn_matiec_undefined_a",   _iec_log(_matiec_error(45, 6, 18, "undefined identifier 'TempSensor'")),
         "matiec.undefined_symbol",  Stage.IEC_COMPILATION, Severity.BLOCKING, Complexity.TRIVIAL),
        ("syn_matiec_undefined_b",   _iec_log(_matiec_error(12, 4, 14, "identifier 'PumpStart' not declared")),
         "matiec.undefined_symbol",  Stage.IEC_COMPILATION, Severity.BLOCKING, Complexity.TRIVIAL),
        ("syn_matiec_type_mismatch", _iec_log(_matiec_error(60, 8, 24, "type mismatch: expected BOOL, got INT")),
         "matiec.type_mismatch",     Stage.IEC_COMPILATION, Severity.BLOCKING, Complexity.MODERATE),
        ("syn_gcc_syntax",           _gcc_log(_gcc_error("plc_main.c", 73, 5, "expected ';' before 'return'")),
         "gcc.syntax_error",         Stage.C_COMPILATION,   Severity.BLOCKING, Complexity.TRIVIAL),
        ("syn_gcc_missing_include",  _gcc_log(_gcc_error("plc_main.c", 1, 10, "modbus.h: No such file or directory")),
         "gcc.missing_include",      Stage.C_COMPILATION,   Severity.BLOCKING, Complexity.TRIVIAL),
    ]
    for name, log_text, category, stage, severity, complexity in uncovered:
        cases.append(_case(name, log_text, category, stage, severity, complexity))

    return cases
