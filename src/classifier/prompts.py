"""System and user prompts for the live LLM.

The mock provider doesn't use these — it's a dictionary lookup, no prompt
involved. Only the live providers (google, anthropic) read this file.
"""
from __future__ import annotations

from src.parser.models import ParsedError, ParsedLog


SYSTEM_PROMPT = """You are an expert PLC engineer specialising in the Beremiz toolchain (PLCopen XML → IEC 61131-3 ST → C compilation via matiec). Your job is to classify build errors and propose actionable fixes for the engineer who hit them.

Three pipeline-specific things to keep in mind:

1. The PLCopen XSD validator emits a recurring false-positive warning ("Element '...data': Missing child element(s)") for projects whose XML is structurally valid. Treat it as info-level noise unless the log shows it's the actual cause.

2. The matiec wrapper prefixes every stderr line with "Warning:" even when the inner verdict is "error:". The inner verdict is authoritative — don't downgrade severity because of the outer prefix.

3. When you see a Python traceback rooted in Beremiz code (PLCGenerator.py, PLCControler.py, ProjectController.py, Beremiz_cli.py), it's almost always a code-gen crash triggered by the user's XML shape. Frame the root cause in user-actionable terms (the XML problem), not the internal Python frame.

For each primary-root error, return one classification via the structured-output schema:
- severity: blocking | warning | info
- fix_complexity: trivial | moderate | complex
- root_cause: 1-3 sentences in user-actionable terms
- 1-3 suggestions, each with title, rationale, and (where applicable) before/after code snippets
- raw_confidence per suggestion in [0.0, 1.0]

Be concise. Engineers are time-pressed. Prefer concrete code snippets over prose."""


def build_system_prompt() -> str:
    """Return the system prompt sent to the live LLM."""
    return SYSTEM_PROMPT


def build_user_prompt(parsed: ParsedLog, targets: list[ParsedError]) -> str:
    """Render the user prompt: parsed primary errors + a slice of the raw log."""
    parts: list[str] = ["# Primary errors to classify\n"]

    for err in targets:
        loc = err.source_location
        loc_str = ""
        if loc.file:
            loc_str = f" ({loc.file}"
            if loc.line:
                loc_str += f":{loc.line}"
                if loc.column:
                    loc_str += f":{loc.column}"
            loc_str += ")"
        parts.append(
            f"- error_id={err.id} | stage={err.stage.value} | category={err.category}{loc_str}\n"
            f"  message: {err.message}\n"
        )
        if err.context_lines:
            ctx = "\n    ".join(err.context_lines[:6])
            parts.append(f"  context:\n    {ctx}\n")

    parts.append("\n# Raw build log (for cross-reference)\n```\n")
    # Truncate long logs to stay within the token / latency budget.
    raw_lines = parsed.raw_log.splitlines()
    if len(raw_lines) > 200:
        head = "\n".join(raw_lines[:120])
        tail = "\n".join(raw_lines[-60:])
        parts.append(f"{head}\n... [truncated {len(raw_lines) - 180} lines] ...\n{tail}")
    else:
        parts.append(parsed.raw_log)
    parts.append("\n```\n")
    return "".join(parts)
