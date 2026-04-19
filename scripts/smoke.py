"""End-to-end smoke test.

Exercises the full pipeline (parse → cascade → classifier → provider →
HTTP-shaped response) for every available provider against both real OTee
fixtures. 

Run:  .venv/Scripts/python.exe scripts/smoke.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Force UTF-8 on stdout so the ✓ / ✗ marks render on Windows cp1252 consoles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from fastapi.testclient import TestClient  # noqa: E402

from src.api.main import app  # noqa: E402

SAMPLES = REPO_ROOT / "samples"
EXPECTED = {
    "constant_error.txt": {
        "category": "matiec.constant_assignment",
        "stage": "iec_compilation",
        "severity": "blocking",
    },
    "empty_project.txt": {
        "category": "python.attribute_error",
        "stage": "code_generation",
        "severity": "blocking",
    },
}


def _run(provider_name: str, sample_path: Path, expected: dict) -> tuple[bool, str]:
    """Hit ``/classify`` with one sample under ``provider_name``; return (ok, summary)."""
    os.environ["LLM_PROVIDER"] = provider_name
    log_text = sample_path.read_text()

    started = time.perf_counter()
    with TestClient(app) as client:
        try:
            r = client.post("/classify", json={"log_text": log_text})
        except Exception as exc:
            return False, f"request failed: {exc}"
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:200]}"

    body = r.json()
    if not body["errors"]:
        return False, "response had no errors"

    primary = body["errors"][0]
    actual = {
        "category": primary["parsed"]["category"],
        "stage": primary["stage"],
        "severity": primary["severity"],
    }
    mismatches = [k for k in expected if actual[k] != expected[k]]

    summary = (
        f"provider={body['provider']:<10} "
        f"latency={body['latency_ms']:>8.2f} ms (round-trip {elapsed_ms:>7.2f} ms) "
        f"category={actual['category']:<32} "
        f"severity={actual['severity']:<8} "
        f"complexity={primary['fix_complexity']:<8} "
        f"confidence={primary['classification_confidence']:.2f} "
        f"suggestions={len(primary['suggestions'])}"
    )
    if mismatches:
        return False, f"{summary}  ✗ mismatched fields: {mismatches} expected={expected}"
    return True, summary


def _section(title: str) -> None:
    """Print a banner row that visually separates sections in the output."""
    print(f"\n{'=' * 90}\n {title}\n{'=' * 90}")


def main() -> int:
    """Run mock + (optionally live) providers across both real samples; return 0 on PASS."""
    providers: list[str] = ["mock"]
    if os.environ.get("GOOGLE_API_KEY"):
        providers.append("google")
    else:
        print("• Skipping google provider (GOOGLE_API_KEY not set in env or .env)")
    if os.environ.get("ANTHROPIC_API_KEY"):
        providers.append("anthropic")
    else:
        print("• Skipping anthropic provider (ANTHROPIC_API_KEY not set)")

    rc = 0
    for provider in providers:
        _section(f"Provider: {provider}")
        for sample_name, expected in EXPECTED.items():
            ok, summary = _run(provider, SAMPLES / sample_name, expected)
            mark = "✓" if ok else "✗"
            print(f" {mark} {sample_name:<22} {summary}")
            if not ok:
                rc = 1

    _section("Negative-path checks (mock provider)")
    os.environ["LLM_PROVIDER"] = "mock"
    with TestClient(app) as client:
        # 1. Empty body → 422
        r = client.post("/classify", json={"log_text": ""})
        ok = r.status_code == 422
        print(f" {'✓' if ok else '✗'} empty log returns 422 (got {r.status_code})")
        if not ok:
            rc = 1
        # 2. Garbage log → 200, empty errors
        r = client.post("/classify", json={"log_text": "no errors here\n"})
        ok = r.status_code == 200 and r.json()["errors"] == []
        print(f" {'✓' if ok else '✗'} garbage log returns 200 with errors=[] (got {r.status_code})")
        if not ok:
            rc = 1
        # 3. /health
        r = client.get("/health")
        ok = r.status_code == 200 and r.json() == {"status": "ok"}
        print(f" {'✓' if ok else '✗'} /health returns 200 ok")
        if not ok:
            rc = 1

    _section("Result")
    print(" PASS" if rc == 0 else " FAIL")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
