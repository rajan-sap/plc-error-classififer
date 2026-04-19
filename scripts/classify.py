"""Ad-hoc classifier — point it at any log file and see what comes back.

Whatever LLM provider is configured (Anthropic key in .env, Google
key in .env, or fall back to mock) is what drives the call. So the
examiner can feed in arbitrary error logs and watch the real LLM
classify them.

Usage:

    python scripts/classify.py samples/constant_error.txt
    python scripts/classify.py /path/to/any/log.txt
    cat some_log.txt | python scripts/classify.py -

    # Force a particular provider:
    LLM_PROVIDER=anthropic python scripts/classify.py samples/empty_project.txt

    # Plain JSON output (machine-readable):
    python scripts/classify.py samples/constant_error.txt --json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from src.classifier import classify  # noqa: E402
from src.llm import get_provider  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", help="Path to a log file. Use '-' for stdin.")
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of human-readable summary.")
    args = ap.parse_args()

    log_text = sys.stdin.read() if args.path == "-" else Path(args.path).read_text()
    if not log_text.strip():
        print("ERROR: log is empty.", file=sys.stderr)
        return 2

    provider = get_provider()
    t0 = time.perf_counter()
    results, parsed = classify(log_text, provider)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    if args.json:
        payload = {
            "errors": [r.model_dump(mode="json") for r in results],
            "primary_root_ids": parsed.cascade.primary_root_ids,
            "provider": provider.name,
            "latency_ms": round(elapsed_ms, 2),
        }
        print(json.dumps(payload, indent=2))
        return 0

    _print_human(results, parsed, provider.name, elapsed_ms)
    return 0


def _print_human(results, parsed, provider_name: str, elapsed_ms: float) -> None:
    print(f"\n{'=' * 80}")
    print(f" provider={provider_name}   latency={elapsed_ms:.1f} ms   total errors={len(results)}")
    print(f" primary roots: {parsed.cascade.primary_root_ids}")
    print(f"{'=' * 80}")

    primary_ids = set(parsed.cascade.primary_root_ids)
    for r in results:
        is_primary = r.parsed.id in primary_ids
        marker = "▼ PRIMARY" if is_primary else ("· noise" if r.parsed.is_noise else "· downstream")
        print(f"\n[{r.parsed.id}] {marker}")
        print(f"  stage      : {r.stage.value}")
        print(f"  category   : {r.parsed.category}")
        print(f"  severity   : {r.severity.value}")
        print(f"  complexity : {r.fix_complexity.value}")
        print(f"  classification_confidence : {r.classification_confidence}  (overall, derived blend)")
        loc = r.parsed.source_location
        if loc.file:
            loc_str = loc.file
            if loc.line:
                loc_str += f":{loc.line}"
                if loc.column:
                    loc_str += f":{loc.column}"
            print(f"  location   : {loc_str}")
        print(f"  message    : {r.parsed.message[:120]}")
        print(f"  root cause : {r.root_cause[:300]}{'...' if len(r.root_cause) > 300 else ''}")
        for i, s in enumerate(r.suggestions):
            print(f"  suggestion[{i}] (conf={s.confidence}): {s.title}")
            print(f"    rationale: {s.rationale[:200]}{'...' if len(s.rationale) > 200 else ''}")
            if s.before_snippet:
                print(f"    before: {s.before_snippet[:120]}{'...' if len(s.before_snippet) > 120 else ''}")
            if s.after_snippet:
                print(f"    after : {s.after_snippet[:120]}{'...' if len(s.after_snippet) > 120 else ''}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
