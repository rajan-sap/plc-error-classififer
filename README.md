# PLC Error Classifier

Submission for OTee's AI engineering task.

A small Python service that reads a PLC build log, figures out which of
the four pipeline stages actually broke (PLCopen XML → Beremiz code-gen
→ matiec → gcc), and suggests a fix. Single endpoint, `POST /classify`,
response under 3 seconds.

## Reviewing this?

Around a minute, start to finish.

```bash
git clone <repo-url> ai-task-bundle
cd ai-task-bundle/solution
py -3.11 -m venv .venv && .venv/Scripts/activate    # Windows
# python3 -m venv .venv && source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
python scripts/verify.py
```

To exercise the live LLM path, drop **one** of these into `.env`
before running `verify.py`:

```
ANTHROPIC_API_KEY=<your key>     # Claude (brief-recommended)
GOOGLE_API_KEY=<your key>        # Gemini (alternative)
```

Without a key the smoke step still passes — it just skips the live
provider and notes it as skipped.

`scripts/verify.py` runs three stages and prints `VERIFY PASS` /
`VERIFY FAIL`:

1. **`pytest`** — 14 tests across parser, classifier, eval framework, API
2. **`scripts/smoke.py`** — end-to-end against both real OTee fixtures,
   plus negative-path checks; calls live LLM if a key is set
3. **`src/eval/runner.py`** — 22 cases (2 real + 20 synthetic),
   regenerates [`eval/report.md`](eval/report.md)

### Want to test the API yourself?

`verify.py` proves the API works (the smoke step uses FastAPI's in-process
`TestClient`). To poke at it interactively over real HTTP — Swagger UI,
curl, your own client — start the dev server in a separate terminal:

```bash
make run    # uvicorn on http://127.0.0.1:8000
```

Then either:

- **Browser** — open http://127.0.0.1:8000/docs (Swagger UI).
  - `POST /classify-raw` lets you paste a multi-line log straight into
    the body field with `Content-Type: text/plain` (no JSON escaping
    needed). Click **Execute**, scroll down to "Server response".
  - `POST /classify` is the canonical JSON contract for production
    clients.
- **CLI** — `python scripts/classify.py samples/constant_error.txt`
  (no server needed) or `python scripts/classify.py /any/log/you/have.txt`.
- **curl** —
  `curl -X POST http://127.0.0.1:8000/classify-raw -H 'Content-Type: text/plain' --data-binary @samples/constant_error.txt`

All three paths hit the same pipeline and use whichever live LLM
provider is configured in `.env` (or the mock if no key is set).

## What it does

The two real OTee fixtures in `samples/` shaped the design:

- **`constant_error.txt`** — a program that writes to a
  `<localVars constant="true">` variable. matiec rejects it. The
  interesting twist: the matiec wrapper prefixes *every* stderr line
  with `Warning:` even when the inner verdict is `error:`. A naive
  parser mis-classifies severity.
- **`empty_project.txt`** — a program with an empty `<ST>` body.
  Beremiz's PLCGenerator hits `text.upper()` on `None` and crashes
  with an `AttributeError` deep in the Python stack. The traceback is
  the *symptom*; the root cause is the empty XML body upstream.

Both logs also contain a recurring PLCopen XSD warning that is *not* a
real problem — both XMLs are structurally valid PLCopen, the warning
fires anyway. The parser tags it as noise.

These three behaviours (prefix lying, traceback ≠ root cause, persistent
false-positive) are what separate "regex over `error:`" from a system
that actually helps.

---

## Architecture

```
HTTP client  →  POST /classify  →  FastAPI (src/api/main.py)
                                        │
                                        ▼
                            Deterministic parser (src/parser/)
                            • stage detection
                            • matiec / python / gcc / XSD extractors
                            • cascade DAG resolver (multi-root capable)
                                        │
                                        ▼  ParsedLog
                            Classifier (src/classifier/)
                            • primary roots → LLM
                            • noise / downstream → synthesised locally
                            • derived confidence (parser × specificity × LLM raw)
                                        │
                                        ▼
                            LLMProvider (src/llm/)
                            • AnthropicProvider — live (Claude Haiku 4.5)
                            • GoogleProvider    — live (Gemini 3.1 Flash Lite)
                            • MockProvider      — test fixture (no API key)
```

### Key decisions

1. **Hybrid, not pure-LLM.** Structural questions (which stage, file,
   line, exception class) are one regex away. The LLM only sees
   primary-root errors and only does what LLMs are good at:
   root-cause narrative + fix snippets with before/after code. The
   Python pipeline adds ~0.3 ms; production wall-clock is dominated
   by the ~2 s LLM call. Fits comfortably under the 3 s budget.

   The contract between layers is the **`ParsedLog`** Pydantic model — a list of
   `ParsedError` with stage / category / source location / cascade DAG. Every
   downstream consumer (classifier, eval framework, future UIs) talks to that
   model, not to raw text.
2. **Cascade-aware, multi-root capable.** A real build log is one (or
   more) cause and N symptoms. The resolver picks every non-noise
   non-generic error in the *earliest* stage as a primary root, and
   attaches later-stage events + generic "build failed" tails as
   downstream of the closest primary by line.
3. **Confidence is derived, not LLM-self-reported.** The final
   `confidence` field blends parser source-location quality (40 %),
   category specificity (30 %), and the LLM's raw confidence (30 %).
   The cohort spread (curated 0.92 vs fallback 0.77) shows the
   blending discriminates.
4. **Mock provider is a test fixture, not a production mode.** It
   exists so `pytest` and CI run free and offline, and so a reviewer
   can clone-and-run without an API key. Production needs a real LLM.
5. **One LLM round-trip per request.** Both live providers use
   structured output (Anthropic via forced tool-use, Google via inline
   `response_schema`). One call returns the full classification.

## Brief requirement → file map

| Brief § | Requirement                                  | File                                                                                                                                                               |
| -------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| §1      | Parse multi-line, multi-stage error output   | `src/parser/parser.py`                                                                                                                                           |
| §1      | Extract type / stage / line / context        | `src/parser/extractors.py`, `ParsedError.source_location`                                                                                                      |
| §1      | Cascading errors                             | `src/parser/cascade.py` (multi-root)                                                                                                                             |
| §2      | Severity / Stage / Complexity enums          | `src/parser/models.py`                                                                                                                                           |
| §2      | LLM with appropriate prompting               | `src/classifier/prompts.py`, structured output in `src/llm/{anthropic,google}.py`                                                                              |
| §3      | 1–3 suggestions w/ before/after snippets    | `LLMSuggestion` in `src/llm/provider.py`                                                                                                                       |
| §3      | Root cause                                   | `LLMClassification.root_cause`                                                                                                                                   |
| §3      | Confidence 0.0–1.0 per suggestion           | `Suggestion.confidence` (per-suggestion, LLM raw) + `ClassifiedError.classification_confidence` (per-error, derived blend in `src/classifier/confidence.py`) |
| §3      | Graceful with missing context                | `_synth_unknown` in `classifier.py`, FastAPI 422 on empty body                                                                                                 |
| §4      | `POST /classify`, <3 s                     | `src/api/main.py` (verified ~2 s with live LLM by `scripts/smoke.py`)                                                                                          |
| §5      | Synthetic generator                          | `src/eval/generator.py` (20 cases, all 4 stages)                                                                                                                 |
| §5      | 20–30 ground-truth cases                    | `src/eval/fixtures.py` (2 real + 20 synthetic = 22)                                                                                                              |
| §5      | Classification accuracy + suggestion quality | `src/eval/metrics.py` + `eval/suggestion_quality.json` (hand labels)                                                                                           |
| §5      | Evaluation report                            | [`eval/report.md`](eval/report.md)                                                                                                                                  |

---

## API

`POST /classify`

Request:

```json
{
  "log_text": "...the raw build log, JSON-escaped...",
  "source_xml": "<project>...</project>"
}
```

`source_xml` is optional. Response (abbreviated):

```jsonc
{
  "errors": [
    {
      "parsed": {
        "id": "err_003",
        "stage": "iec_compilation",
        "category": "matiec.constant_assignment",
        "source_location": {"file": "plc.st", "line": 30, "column": 4},
        "is_noise": false
      },
      "severity": "blocking",
      "fix_complexity": "trivial",
      "root_cause": "The target variable is declared inside a `<localVars constant=\"true\">` block...",
      "suggestions": [
        {
          "title": "Make the variable non-constant in the XML interface",
          "before_snippet": "<localVars constant=\"true\"> ...",
          "after_snippet":  "<localVars constant=\"false\"> ...",
          "confidence": 0.9                      // per-suggestion (LLM raw)
        }
      ],
      "classification_confidence": 0.94          // per-error (derived blend)
    }
  ],
  "primary_root_ids": ["err_003"],
  "provider": "anthropic",
  "latency_ms": 1858.4
}
```

`GET /` redirects to `/docs` (Swagger UI). `GET /health` returns
`{"status": "ok"}`.

---

## Configuration

Drop **one** key into `.env` (git-ignored). The factory
auto-detects which provider to use:

```
ANTHROPIC_API_KEY=<your key>     # Claude — recommended (brief-listed)
GOOGLE_API_KEY=<your key>        # Gemini — alternative
```

| Var                   | Default                           | Notes                                                   |
| --------------------- | --------------------------------- | ------------------------------------------------------- |
| `ANTHROPIC_API_KEY` | —                                | Selects Claude.                                         |
| `ANTHROPIC_MODEL`   | `claude-haiku-4-5-20251001`     | Override for a different Claude variant.                |
| `GOOGLE_API_KEY`    | —                                | Selects Gemini.                                         |
| `GOOGLE_MODEL`      | `gemini-3.1-flash-lite-preview` | Override for a different Gemini variant.                |
| `LLM_PROVIDER`      | _(auto)_                        | Force the choice:`mock` / `anthropic` / `google`. |

If no key is set the factory falls back to the `MockProvider` — a
test/dev convenience, not a production mode (only ~5 hand-coded
categories).

`tests/conftest.py` forces `LLM_PROVIDER=mock` so a stray key in
`.env` never accidentally calls a live API during `pytest`.

---

### Common commands

```bash
make verify     # full reviewer flow: install → test → smoke → eval
make test       # pytest only
make smoke      # end-to-end against real fixtures, calls live LLM if a key is set
make eval       # regenerates eval/report.md
make run        # uvicorn dev server on http://127.0.0.1:8000
```

(One-to-one `python scripts/...` mappings in the Makefile if you don't
have GNU Make.)

## Tests

`pytest` runs 14 tests in ~1 s, mock-only, deterministic:

- **`test_parser.py`** (6) — matiec extraction with the right source
  location (proves the regex reads past the lying `Warning:` prefix),
  Python traceback → `python.attribute_error`, XSD demoted as noise on
  both real fixtures, cascade picks the real failure over noise/symptoms,
  cascade reports multiple primaries when independent failures exist,
  malformed input doesn't crash.
- **`test_classifier.py`** (3) — both real fixtures classified correctly
  end-to-end, derived confidence ≠ raw LLM confidence, primary listed
  first.
- **`test_eval.py`** (3) — generator emits ≥20 cases, all four stages
  covered, runner writes valid report + fixtures.
- **`test_api.py`** (2) — `TestClient` round-trip, 422 on empty body.

Live-provider testing happens via `scripts/smoke.py` (which calls the
real LLM when a key is set).

---

## Eval

`python -m src.eval.runner` regenerates [`eval/report.md`](eval/report.md).

22 cases (2 real OTee fixtures + 20 synthetic) through the full
pipeline. The runner uses `MockProvider` so numbers are reproducible
across runs without burning tokens.

| Metric                                      | Value                       |
| ------------------------------------------- | --------------------------- |
| Stage detection accuracy                    | **100 %**             |
| Category extraction accuracy                | **95.5 %**            |
| Severity accuracy                           | **77.3 %**            |
| Complexity accuracy                         | **81.8 %**            |
| Cascade primary-root accuracy               | **95.5 %**            |
| Noise-demotion accuracy                     | **100 %**             |
| Avg suggestion quality (manual labels, 1-3) | **2.48 / 3**          |
| Pipeline overhead p50 / p95*(LLM excluded)* | **~0.2 ms / ~0.3 ms** |

Curated cohort: 100 % severity & complexity. Fallback cohort (5 cases
with no curated handler): 0 % severity, 20 % complexity — exactly as
designed; that's the gap a real LLM closes. The point of the eval isn't
to claim "perfect", it's to show exactly which categories need a
curated handler or live-LLM judgment next.

For real production latency you'd add the LLM round-trip — typically
~2 s with Claude Haiku 4.5 or Gemini 3.1 Flash Lite, well under the 3 s
SLA. `scripts/smoke.py` reports those live numbers.

---

## Project layout

```
solution/
├─ src/
│  ├─ api/          FastAPI + schemas
│  ├─ parser/       stages, extractors, cascade (multi-root), parse()
│  ├─ classifier/   orchestrator, prompts, derived confidence
│  ├─ llm/          provider Protocol, mock, anthropic, google, factory
│  └─ eval/         generator, fixtures, runner, metrics, report
├─ tests/           14 tests (parser, classifier, eval, API)
├─ scripts/         classify.py · smoke.py · verify.py
├─ samples/         the two real OTee fixtures (.txt + .xml)
└─ eval/            report.md · fixtures.json · suggestion_quality.json
```

---

## Limitations

- **No real `c_compilation` fixture.** The OTee samples don't include
  one. The parser handles the standard gcc shape and the synthetic
  generator emits 8 gcc cases, but a real failure may surface formats
  the synthetic doesn't exercise.
- **Mock coverage is partial.** Curated responses exist for 5
  categories. Anything else falls through to a low-confidence generic
  — see the eval report's "Fallback" cohort.
- **Eval doesn't drive the live LLM today.** The 100 % numbers measure
  the deterministic pipeline + mock. Live LLM quality is verified by
  `scripts/smoke.py` against the 2 real fixtures only.
- **No persistence, auth, or rate-limiting.** Single-process FastAPI
  dev server. Wrap in a usual production setup before exposing
  externally.

---

## Future direction

The pipeline today is stateless — log in, classification out, nothing
remembered. To turn this into a product that genuinely saves engineers
time day after day, we need to start collecting data from real use.
Four things, in this order:

### 1. Capture feedback (~2-3 weeks)

For every classification, store:

- the log (or just the parser output, if storing raw customer XML
  feels risky)
- the suggestions we returned (with their `confidence` values)
- whether the engineer accepted, rejected, or applied each one
- if applied: did the next build pass?

That gives us `(log → suggestion → outcome)` records. After a quarter
of real customer use we have a corpus no generic LLM provider can
match. Concretely: add `POST /suggestions/{id}/vote` and
`/suggestions/{id}/applied`, write to Postgres (or similar), and put
a small thumbs-up/down UI wherever the engineer already works —
Slack notification, OTee dashboard, an IDE plugin, whichever surface
sees the most use.

### 2. RAG against past fixes (~2 weeks, after we have the data)

Once the corpus hits ≥100 validated cases, embed each parsed error
and look up the closest matches that worked. Inject those past cases
into the LLM prompt as concrete examples — "last time we saw this
same matiec error, flipping `constant=\"true\"` to `\"false\"` fixed
it; the same change should work here".

This is the cheapest quality lift available before we touch
fine-tuning. pgvector, Qdrant, whatever — the choice doesn't matter
much. Just don't build it before we have the data: under 100 cases
the retrieval is noise.

### 3. Fine-tune our own domain specific model (Long term strategy)

When the corpus reaches ~1000-5000 validated triples, we can fine-tune
a smaller model — open-source (Llama, Mistral) or a commercial one
that supports tuning (Gemini Flash, Claude Haiku). What we get:

- cheaper per call (smaller model)
- faster per call (smaller, and we can self-host if we want)
- better on PLC-specific errors, because it's actually seen thousands
- no more prompt-engineering tricks — the domain knowledge sits in
  the weights, not in the system prompt

A generic LLM is a commodity that any competitor can rent. A model
fine-tuned on OTee's own validated dataset is something only OTee
has. Worth investing in for the long run.

### 4. Wire it into the build pipeline

Right now an engineer hits an error, copies the log, pastes it into a
tool. That copy-paste step is what kills adoption — once the novelty
wears off, nobody remembers to do it. Better:

- every failed build is auto-classified
- the result shows up in the build log itself, or as a PR comment
- for high-confidence suggestions (>0.9) that are trivially
  applicable, offer a one-click apply

That changes the system from "a tool engineers occasionally use" to
"something that just shows up when something breaks". Very different
engagement profile.

If anything is unclear, Happy to talk through any decision.
