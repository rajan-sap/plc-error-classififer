"""Cascade resolution: separate cause from symptoms.

Supports multi-root cases: when the log contains independent failures in
the same earliest stage (e.g. two unrelated matiec errors in different
POUs), all of them are reported as primary roots. Errors in later stages
are treated as downstream of the upstream cause(s).
"""
from __future__ import annotations

from src.parser.models import Cascade, ParsedError, Stage

#: Always SYMPTOMS — never let one of these be the primary root.
GENERIC_DOWNSTREAM_CATEGORIES: set[str] = {
    "build.cannot_build",
    "build.code_generation_failed",
    "build.iec_compiler_returned_nonzero",
}

#: Pipeline stage ordering. Earlier stages can cause later-stage failures.
_STAGE_ORDER: dict[Stage, int] = {
    Stage.XML_VALIDATION: 0,
    Stage.CODE_GENERATION: 1,
    Stage.IEC_COMPILATION: 2,
    Stage.C_COMPILATION: 3,
    Stage.UNKNOWN: 99,
}


def build_cascade(errors: list[ParsedError]) -> Cascade:
    """Pick the primary error(s) and attach the rest as downstream or noise.

    Multi-root rule: every non-noise non-generic error in the earliest
    stage present is a primary root. Anything in a later stage, plus all
    generic "build failed" tails, become downstream of the closest-by-line
    primary. If the only events are noise, we surface a noise event as
    the primary so the response is still coherent.
    """
    if not errors:
        return Cascade()

    candidates = [
        e for e in errors
        if not e.is_noise and e.category not in GENERIC_DOWNSTREAM_CATEGORIES
    ]

    # Fallback: nothing real to surface — prefer noise (has source-loc info)
    # over a generic "build failed" tail that diagnoses nothing.
    if not candidates:
        noise = [e for e in errors if e.is_noise]
        primary = noise[0] if noise else errors[0]
        return Cascade(primary_root_ids=[primary.id], downstream={primary.id: []})

    # All candidates in the EARLIEST stage are independent primary roots.
    earliest = min(_STAGE_ORDER[c.stage] for c in candidates)
    primaries = [c for c in candidates if _STAGE_ORDER[c.stage] == earliest]
    primary_ids = {p.id for p in primaries}
    downstream: dict[str, list[str]] = {p.id: [] for p in primaries}

    # Attach every other non-noise event as downstream of the closest-by-line
    # primary. Generic tails always count as downstream.
    for e in errors:
        if e.id in primary_ids or e.is_noise:
            continue
        owner = _closest_primary(e, primaries)
        downstream[owner].append(e.id)

    return Cascade(primary_root_ids=[p.id for p in primaries], downstream=downstream)


def _closest_primary(err: ParsedError, primaries: list[ParsedError]) -> str:
    """Return the id of the primary nearest to ``err`` by log-line distance."""
    return min(primaries, key=lambda p: abs(p.log_line_start - err.log_line_start)).id
