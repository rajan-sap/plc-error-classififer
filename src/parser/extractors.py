"""Per-stage error extractors.

Each function scans the whole log and returns a list of :class:`ParsedError`.
Ids are left blank — :func:`src.parser.parser.parse` renumbers them after a
global sort.

Five extractors:

    extract_xsd_warnings      -> PLCopen XSD complaints (always tagged noise)
    extract_matiec_errors     -> iec2c errors (reads past the lying "Warning:" prefix)
    extract_python_tracebacks -> Beremiz code-gen crashes
    extract_gcc_errors        -> standard gcc "<file>.c:LINE:COL: error:" format
    extract_generic_failures  -> "Cannot build", "PLC code generation failed", etc.
"""
from __future__ import annotations

import os
import re

from src.parser.models import ParsedError, SourceLocation, Stage


def _match_category(msg: str, table: list[tuple[re.Pattern[str], str]], fallback: str) -> str:
    """Scan ``table`` for the first regex matching ``msg``; return ``fallback`` on no match."""
    for pat, cat in table:
        if pat.search(msg):
            return cat
    return fallback


# --- PLCopen XSD warnings ---------------------------------------------------

XSD_HEADER_PAT = re.compile(r"PLC XML file doesn't follow XSD schema at line (?P<line>\d+):")
XSD_ELEMENT_PAT = re.compile(r"Element '(?P<ns>[^']+)':\s*(?P<detail>.+?)(?:\.Start build|$)")


def extract_xsd_warnings(lines: list[str]) -> list[ParsedError]:
    """Extract PLCopen XSD validation warnings as :class:`ParsedError` records.

    Both supplied OTee fixtures contain this warning despite having
    structurally valid XML. We still extract it (the XML line number is
    real) but tag every match as ``is_noise=True`` so the classifier
    renders it as ``severity=info`` rather than reporting a non-issue.
    """
    out: list[ParsedError] = []
    for i, line in enumerate(lines):
        m = XSD_HEADER_PAT.search(line)
        if not m:
            continue
        # The element detail usually lives on the next line.
        detail = ""
        end = i
        if i + 1 < len(lines):
            dm = XSD_ELEMENT_PAT.search(lines[i + 1])
            if dm:
                detail = dm.group("detail").strip()
                end = i + 1
        category = "xsd.missing_child_element" if "Missing child" in detail else "xsd.warning"
        out.append(ParsedError(
            stage=Stage.XML_VALIDATION,
            category=category,
            message=f"PLCopen XSD validation: {detail}" if detail else line.strip(),
            raw_text="\n".join(lines[i : end + 1]),
            source_location=SourceLocation(line=int(m.group("line"))),
            log_line_start=i,
            log_line_end=end,
            is_noise=True,
            context_lines=lines[i : end + 1],
        ))
    return out


# --- matiec (iec2c) ---------------------------------------------------------

MATIEC_ERR_PAT = re.compile(
    r"^(?:Warning:\s*)?"
    r"(?P<file>\S+?):(?P<l1>\d+)-(?P<c1>\d+)\.\.(?P<l2>\d+)-(?P<c2>\d+):"
    r"\s*(?P<verdict>error|warning):\s*(?P<msg>.+?)\s*$"
)
MATIEC_SECTION_PAT = re.compile(r"^(?:Warning:\s*)?In section:\s*(?P<section>.+)$")
MATIEC_SOURCE_LINE_PAT = re.compile(r"^(?:Warning:\s*)?(?P<lineno>\d{3,4}):\s*(?P<src>.+)$")
MATIEC_BAILING_PAT = re.compile(r"^(?:Warning:\s*)?\d+\s+error\(s\) found\.\s*Bailing out")

MATIEC_CATEGORY_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Assignment to CONSTANT", re.I), "matiec.constant_assignment"),
    (re.compile(r"undefined|undeclared", re.I), "matiec.undefined_symbol"),
    (re.compile(r"type mismatch|incompatible type", re.I), "matiec.type_mismatch"),
    (re.compile(r"syntax error", re.I), "matiec.syntax_error"),
]


def _matiec_context(lines: list[str], start: int) -> tuple[int, list[str]]:
    """Sweep forward from ``start`` collecting matiec's "In section / source / Bailing out" block.

    Returns ``(end_index, context_lines)``. Stops when a non-context line
    appears or when the "Bailing out" marker is hit.
    """
    context = [lines[start].strip()]
    end = start
    for j in range(start + 1, min(start + 8, len(lines))):
        line = lines[j]
        is_context = bool(
            MATIEC_SECTION_PAT.match(line)
            or MATIEC_SOURCE_LINE_PAT.match(line)
            or MATIEC_BAILING_PAT.match(line)
            or line.strip() in ("", "Warning:")
        )
        if not is_context:
            break
        context.append(line.strip())
        end = j
        if MATIEC_BAILING_PAT.match(line):
            break
    return end, context


def extract_matiec_errors(lines: list[str]) -> list[ParsedError]:
    """Extract matiec/iec2c errors with their context block.

    The wrapper script prefixes EVERY matiec stderr line with ``Warning:``,
    even when the inner verdict from ``iec2c`` is ``error:``. We capture
    the inner verdict because that's the authoritative severity. A parser
    that trusts the outer prefix mis-classifies severity.
    """
    out: list[ParsedError] = []
    i = 0
    while i < len(lines):
        m = MATIEC_ERR_PAT.match(lines[i])
        if not m:
            i += 1
            continue
        end, context = _matiec_context(lines, i)
        msg = m.group("msg").strip()
        out.append(ParsedError(
            stage=Stage.IEC_COMPILATION,
            category=_match_category(msg, MATIEC_CATEGORY_KEYWORDS, "matiec.error"),
            message=msg,
            raw_text="\n".join(lines[i : end + 1]),
            source_location=SourceLocation(
                file=os.path.basename(m.group("file")),
                line=int(m.group("l1")),
                column=int(m.group("c1")),
                end_line=int(m.group("l2")),
                end_column=int(m.group("c2")),
            ),
            log_line_start=i,
            log_line_end=end,
            is_noise=(m.group("verdict") == "warning"),
            context_lines=context,
        ))
        i = end + 1
    return out


# --- Python tracebacks (Beremiz code-gen crashes) --------------------------

TRACEBACK_HEADER = "Traceback (most recent call last):"
TRACEBACK_FRAME_PAT = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)')
EXCEPTION_LINE_PAT = re.compile(r"^(?P<cls>[A-Z]\w*(?:Error|Exception|Warning))(?::\s*(?P<msg>.+))?$")


def _snake(name: str) -> str:
    """Convert ``CamelCase`` to ``camel_case`` (``AttributeError`` -> ``attribute_error``)."""
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def extract_python_tracebacks(lines: list[str]) -> list[ParsedError]:
    """Extract Python tracebacks emitted by Beremiz code-generation.

    The last frame is the SYMPTOM but the root cause is usually upstream
    in the user's XML (e.g. an empty ``<ST>`` body that made ``text`` be
    ``None`` and ``text.upper()`` blow up). The parser captures the
    symptom; the LLM does the upstream-causal reasoning.
    """
    out: list[ParsedError] = []
    i = 0
    while i < len(lines):
        if TRACEBACK_HEADER not in lines[i]:
            i += 1
            continue
        tb_start = i
        # Consume alternating "File ..." / source-line pairs until the pattern breaks.
        frames: list[dict[str, str]] = []
        j = i + 1
        while j < len(lines) and (fm := TRACEBACK_FRAME_PAT.match(lines[j])):
            frame = dict(fm.groupdict())
            frame["src"] = lines[j + 1].strip() if j + 1 < len(lines) else ""
            frames.append(frame)
            j += 2
        # The next non-frame line is the exception itself.
        exc_line = lines[j].strip() if j < len(lines) else ""
        em = EXCEPTION_LINE_PAT.match(exc_line)
        if em:
            exc_cls = em.group("cls")
            exc_msg = em.group("msg") or ""
        else:
            exc_cls = "Exception"
            exc_msg = exc_line

        sl = SourceLocation()
        if frames:
            sl = SourceLocation(file=os.path.basename(frames[-1]["file"]), line=int(frames[-1]["line"]))
        context = [f'  File "{f["file"]}", line {f["line"]}, in {f["func"]}' for f in frames[-5:]]
        context.append(exc_line)
        out.append(ParsedError(
            stage=Stage.CODE_GENERATION,
            category=f"python.{_snake(exc_cls)}",
            message=f"{exc_cls}: {exc_msg}".strip(": "),
            raw_text="\n".join(lines[tb_start : j + 1]),
            source_location=sl,
            log_line_start=tb_start,
            log_line_end=j,
            context_lines=context,
        ))
        i = j + 1
    return out


# --- gcc (c_compilation) ---------------------------------------------------

GCC_ERR_PAT = re.compile(
    r"^(?P<file>\S+\.c):(?P<line>\d+):(?P<col>\d+):\s*(?P<verdict>error|warning|fatal error):\s*(?P<msg>.+?)\s*$"
)

GCC_CATEGORY_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"undefined reference to", re.I), "gcc.undefined_reference"),
    (re.compile(r"implicit declaration", re.I), "gcc.implicit_declaration"),
    (re.compile(r"expected .* before", re.I), "gcc.syntax_error"),
    (re.compile(r"no such file or directory", re.I), "gcc.missing_include"),
    (re.compile(r"redefinition of", re.I), "gcc.redefinition"),
]


def extract_gcc_errors(lines: list[str]) -> list[ParsedError]:
    """Extract gcc errors in standard ``<file>.c:LINE:COL: error:`` format.

    No real OTee fixture exercises this stage today — the synthetic
    generator (:mod:`src.eval.generator`) emits gcc cases for eval coverage.
    """
    out: list[ParsedError] = []
    for i, line in enumerate(lines):
        m = GCC_ERR_PAT.match(line)
        if not m:
            continue
        msg = m.group("msg").strip()
        out.append(ParsedError(
            stage=Stage.C_COMPILATION,
            category=_match_category(msg, GCC_CATEGORY_KEYWORDS, "gcc.error"),
            message=msg,
            raw_text=line,
            source_location=SourceLocation(
                file=os.path.basename(m.group("file")),
                line=int(m.group("line")),
                column=int(m.group("col")),
            ),
            log_line_start=i,
            log_line_end=i,
            is_noise=(m.group("verdict") == "warning"),
            context_lines=[line.strip()],
        ))
    return out


# --- Generic "the build failed" tail messages ------------------------------

#: ``(pattern, stage, category, canonical_message)``. First match per line wins.
GENERIC_PATTERNS: list[tuple[re.Pattern[str], Stage, str, str]] = [
    (re.compile(r"Cannot build project"),
        Stage.UNKNOWN, "build.cannot_build", "Cannot build project."),
    (re.compile(r"IEC to C compiler returned\s+\d+"),
        Stage.IEC_COMPILATION, "build.iec_compiler_returned_nonzero",
        "IEC to C compiler returned a non-zero status."),
    (re.compile(r"PLC code generation failed"),
        Stage.CODE_GENERATION, "build.code_generation_failed", "PLC code generation failed."),
]


def extract_generic_failures(lines: list[str]) -> list[ParsedError]:
    """Extract generic "the build failed" tail messages.

    These diagnose nothing on their own — they're symptoms of whatever
    failed upstream. The cascade resolver attaches them downstream of the
    real root.
    """
    out: list[ParsedError] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        for pat, stage, category, message in GENERIC_PATTERNS:
            if pat.search(stripped):
                out.append(ParsedError(
                    stage=stage,
                    category=category,
                    message=message,
                    raw_text=stripped,
                    log_line_start=i,
                    log_line_end=i,
                ))
                break  # first matching pattern wins; don't double-count
    return out
