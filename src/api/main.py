"""FastAPI app.

Two endpoints for classification:
  • POST /classify       — JSON body, the canonical contract for programmatic clients
  • POST /classify-raw   — text/plain body, for paste-and-go testing in Swagger / curl

Plus /health for liveness probes and a / -> /docs redirect so the browser
doesn't 404 on the root URL.
"""
from __future__ import annotations

import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import RedirectResponse

# Load secrets from .env (git-ignored). Existing process env vars take precedence.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_REPO_ROOT / ".env")

from src.api.schemas import ClassifyRequest, ClassifyResponse  # noqa: E402
from src.classifier import classify  # noqa: E402
from src.llm import get_provider  # noqa: E402

app = FastAPI(
    title="PLC Error Classifier",
    description="Classifies multi-stage PLC build errors and suggests fixes.",
    version="0.1.0",
)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Redirect bare ``/`` to the Swagger UI."""
    return RedirectResponse(url="/docs")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/classify", response_model=ClassifyResponse)
def classify_endpoint(req: ClassifyRequest) -> ClassifyResponse:
    """Classify a PLC build log and return structured errors with fix suggestions.

    Canonical JSON contract — production clients should call this endpoint.
    Body must be ``{"log_text": "...", "source_xml": "..."}`` (the latter optional).
    """
    try:
        provider = get_provider()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Provider init failed: {exc}") from exc

    t0 = time.perf_counter()
    try:
        results, parsed = classify(req.log_text, provider)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Classification failed: {exc}") from exc
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    return ClassifyResponse(
        errors=results,
        primary_root_ids=parsed.cascade.primary_root_ids,
        provider=provider.name,
        latency_ms=round(elapsed_ms, 2),
    )


@app.post(
    "/classify-raw",
    response_model=ClassifyResponse,
    summary="Like /classify but accepts plain text — paste raw multi-line logs as the body, no JSON escaping needed.",
)
def classify_raw_endpoint(log_text: str = Body(..., media_type="text/plain")) -> ClassifyResponse:
    """Convenience wrapper for human / Swagger / curl testing.

    Paste the raw multi-line log directly as the request body with
    ``Content-Type: text/plain``. Internally re-uses :func:`classify_endpoint`,
    so the response shape is identical to ``POST /classify``.
    """
    return classify_endpoint(ClassifyRequest(log_text=log_text))
