"""Stage detection.

Map any line in the build log to the stage that produced it. Stages run
in order:

    xml_validation -> code_generation -> iec_compilation -> c_compilation
"""
from __future__ import annotations

import re

from src.parser.models import Stage

#: Lines that mark the START of a stage. Used by the backward-walk in :func:`stage_at`.
STAGE_OPEN_MARKERS: list[tuple[Stage, re.Pattern[str]]] = [
    (Stage.XML_VALIDATION, re.compile(r"PLC XML file doesn't follow XSD schema")),
    (Stage.CODE_GENERATION, re.compile(r"Generating SoftPLC IEC-61131")),
    (Stage.IEC_COMPILATION, re.compile(r"Compiling IEC Program into C code|/iec2c\b")),
    (Stage.C_COMPILATION, re.compile(r"Compiling .* into native code|\b(?:gcc|clang)\s")),
]

#: Lines whose shape unambiguously belongs to one stage; always wins over backward-walk.
STAGE_HINT_MARKERS: list[tuple[Stage, re.Pattern[str]]] = [
    (Stage.IEC_COMPILATION, re.compile(r"plc\.st:\d+-\d+\.\.\d+-\d+:\s*(?:error|warning):")),
    (Stage.IEC_COMPILATION, re.compile(r"IEC to C compiler returned")),
    (Stage.CODE_GENERATION, re.compile(r"Beremiz_cli\.py|PLCGenerator\.py|PLCControler\.py|ProjectController\.py")),
    (Stage.C_COMPILATION, re.compile(r"\.c:\d+:\d+:\s*error:")),
    (Stage.XML_VALIDATION, re.compile(r"PLC XML file doesn't follow XSD")),
]


def stage_at(line_idx: int, lines: list[str]) -> Stage:
    """Return the build stage active at ``line_idx``.

    Hint markers on the line itself win; otherwise walk backwards until the
    nearest open marker. Falls back to :attr:`Stage.UNKNOWN`.
    """
    if 0 <= line_idx < len(lines):
        for stage, pat in STAGE_HINT_MARKERS:
            if pat.search(lines[line_idx]):
                return stage
    for i in range(min(line_idx, len(lines) - 1), -1, -1):
        for stage, pat in STAGE_OPEN_MARKERS:
            if pat.search(lines[i]):
                return stage
    return Stage.UNKNOWN
