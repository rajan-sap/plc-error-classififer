"""One-command reviewer verification.

Runs: pytest → smoke → eval. Exits non-zero if any step fails.
Cross-platform replacement for `make verify` so Windows reviewers don't
need GNU Make installed.

Usage:  python scripts/verify.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable  # reuse whatever interpreter invoked us

STEPS: list[tuple[str, list[str]]] = [
    ("pytest          (14 parser + classifier + eval + API tests, ~1.1 s)", [PY, "-m", "pytest", "-q"]),
    ("smoke           (end-to-end, mock + live LLM if a key is set)", [PY, "scripts/smoke.py"]),
    ("eval            (regenerates eval/report.md with headline metrics)", [PY, "-m", "src.eval.runner"]),
]


def main() -> int:
    """Run each step in sequence; return 0 if all pass, otherwise the failing exit code."""
    rc = 0
    for label, cmd in STEPS:
        print(f"\n{'=' * 90}")
        print(f" make verify › {label}")
        print(f"{'=' * 90}")
        result = subprocess.run(cmd, cwd=REPO_ROOT)
        if result.returncode != 0:
            print(f"\n ✗ step failed: {' '.join(cmd)} (exit {result.returncode})")
            rc = result.returncode
            break
    print(f"\n{'=' * 90}")
    print(" VERIFY PASS — system works end-to-end" if rc == 0 else " VERIFY FAIL")
    print(f"{'=' * 90}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
