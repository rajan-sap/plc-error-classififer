# Pipeline flow — a real trace through `constant_error.txt`

A step-by-step walk-through of what happens when the 23-line
`samples/constant_error.txt` log enters `POST /classify`. Each step shows
what goes IN and what comes OUT, with actual data captured from the live
pipeline (not invented). Useful as a mental model when reading the code
or debugging a regression.

The relevant files, in the order they're touched:

- `src/api/main.py` — the HTTP entry point
- `src/parser/stages.py` — `stage_at(line_idx, lines)`
- `src/parser/extractors.py` — the five stage-specific extractors
- `src/parser/cascade.py` — primary root vs downstream symptoms
- `src/parser/parser.py` — the parser orchestrator
- `src/classifier/classifier.py` — dispatch + wrap
- `src/classifier/prompts.py` — system + user prompt builders
- `src/llm/google.py` (or `anthropic.py` / `mock.py`) — the LLM call
- `src/classifier/confidence.py` — derived confidence math

---

## Step 0 — The input (23 lines)

```
L00  [17:05:55]: Building project...
L01  [17:05:56]: Cannot build project.            ← shell wrapper banner
L02  [17:05:56]: Cannot build project.            ← (repeated)
L03  stdout: Warning: PLC XML file doesn't follow XSD schema at line 61:
L04  Element '...data': Missing child element(s)... ← noise — fires on every project
L05  Generating SoftPLC IEC-61131 ST/IL/SFC code...
L06-L09  Collecting data types / POUs / Configs
L10  Compiling IEC Program into C code...
L11-L14  iec2c invocation
L15  Warning: /tmp/.../plc.st:30-4..30-12: error: Assignment to CONSTANT...   ← THE REAL FAILURE
L16-L19  matiec context (section / source line / "Bailing out!")
L20  Error: Error : IEC to C compiler returned 1   ← downstream symptom
L21  Error: PLC code generation failed !           ← downstream symptom
```

---

## Step 1 — Stage attribution per line

`stage_at(line_idx, lines)` (in `src/parser/stages.py`) labels each line:

| Lines    | Stage               | Why                                               |
| -------- | ------------------- | ------------------------------------------------- |
| L00–L02 | `unknown`         | Shell-wrapper banners, no stage marker yet        |
| L03–L04 | `xml_validation`  | "PLC XML file doesn't follow XSD" opens the stage |
| L05–L09 | `code_generation` | "Generating SoftPLC..." opens the stage           |
| L10–L21 | `iec_compilation` | "Compiling IEC Program..." + matiec patterns      |

The `c_compilation` stage never appears here — iec_compilation failed
first, so gcc was never invoked.

---

## Step 2 — Five extractors sweep the log

Each extractor (in `src/parser/extractors.py`) scans independently and
pulls what it recognises:

| Extractor                     | Caught                                                                                                                                                                 |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `extract_xsd_warnings`      | 1 event from L03–L04 →`xsd.missing_child_element`, **tagged `is_noise=True`**                                                                              |
| `extract_matiec_errors`     | 1 event from L15–L19 →`matiec.constant_assignment`, source loc `plc.st:30:4..30:12` (the regex reads the **inner** `error:`, not the outer `Warning:`) |
| `extract_python_tracebacks` | none (no Python crash in this log)                                                                                                                                     |
| `extract_gcc_errors`        | none (gcc never ran)                                                                                                                                                   |
| `extract_generic_failures`  | 4 events: 2×`Cannot build` (L01, L02), `IEC to C compiler returned 1` (L20), `PLC code generation failed` (L21)                                                 |

Total: 6 events.

---

## Step 3 — Merge → sort by line → assign stable IDs

The orchestrator (`src/parser/parser.py::parse`) sorts by
`log_line_start`, dedupes, refines the stage assignment, and gives each
event a stable `err_NNN`:

| id                | stage           | category                                 | noise          | source loc            |
| ----------------- | --------------- | ---------------------------------------- | -------------- | --------------------- |
| err_000           | unknown         | `build.cannot_build`                   | false          | —                    |
| err_001           | unknown         | `build.cannot_build`                   | false          | —                    |
| err_002           | xml_validation  | `xsd.missing_child_element`            | **true** | —                    |
| **err_003** | iec_compilation | **`matiec.constant_assignment`** | false          | **plc.st:30:4** |
| err_004           | iec_compilation | `build.iec_compiler_returned_nonzero`  | false          | —                    |
| err_005           | code_generation | `build.code_generation_failed`         | false          | —                    |

This list is the `ParsedLog.errors` field returned by `parse()`.

---

## Step 4 — Cascade resolution

`build_cascade()` in `src/parser/cascade.py` answers two questions:
which event is the *cause*, and which are just symptoms or noise?

```python
primary_root_ids = ['err_003']                              # the ONE thing to fix
downstream[err_003] = ['err_000', 'err_001',                # symptoms
                       'err_004', 'err_005']
noise (separate)   = ['err_002']                            # XSD false-positive
```

How `err_003` wins:

1. Drop noise (`is_noise=True` → err_002 out)
2. Drop generic categories (`build.cannot_build` × 2,
   `build.iec_compiler_returned_nonzero`, `build.code_generation_failed`
   → err_000, 001, 004, 005 all out)
3. First remaining (by line position) = err_003

Everything not chosen as primary AND not noise gets attached as
downstream of the primary.

---

## Step 5 — Classifier dispatching

`classify(log_text, provider)` in `src/classifier/classifier.py` loops
the 6 errors and routes each to one of three handlers:

| Error                         | Handler                        | Cost                |
| ----------------------------- | ------------------------------ | ------------------- |
| **err_003 (PRIMARY)**   | → LLM provider                | 1 LLM call          |
| err_002 (noise)               | →`_synthesise_noise()`      | free, deterministic |
| err_000, err_001 (downstream) | →`_synthesise_downstream()` | free, deterministic |
| err_004, err_005 (downstream) | →`_synthesise_downstream()` | free, deterministic |

**Only one LLM call per request.** That's the design constraint that
keeps p95 latency under the 3 s budget.

---

## Step 6 — The LLM call

`provider.classify(parsed_log, [err_003])` does:

1. Builds a **system prompt** (`src/classifier/prompts.py::SYSTEM_PROMPT`)
   that teaches the LLM about: PLC pipeline stages, the XSD false-positive,
   the lying `Warning:` prefix, traceback ≠ root cause.
2. Builds a **user prompt** (`build_user_prompt`) containing the parsed
   primary error (id, stage, category, source location, message, context
   lines) plus a truncated slice of the raw log for cross-reference.
3. Calls Gemini with **structured output enforced**
   (`response_schema=<inline OpenAPI dict>`, no `$ref` because Gemini
   rejects refs). One round-trip.
4. Receives an `LLMClassification` back, parsed straight into Pydantic.

For err_003, the live Gemini response returns:

```
severity:        blocking
fix_complexity:  trivial
root_cause:      "The target variable is declared inside a <localVars constant=\"true\">
                 block, which makes it read-only under IEC 61131-3. Any assignment
                 to it is rejected by matiec..."
suggestions:
  [0] title:          Make the variable non-constant in the XML interface
      raw_confidence: 0.9
      before_snippet: <localVars constant="true">  <variable name="LocalVar1">...
      after_snippet:  <localVars constant="false"> <variable name="LocalVar1">...
  [1] title:          Remove the assignment from the ST body
      raw_confidence: 0.7
      before_snippet: LocalVar1 := LocalVar0;
      after_snippet:  (* assignment removed; LocalVar1 is constant *)
```

(When `LLM_PROVIDER=mock`, the same shape comes back from the
hand-coded dictionary in `src/llm/mock.py::_CURATED` instead — useful
for tests where we want determinism.)

---

## Step 7 — Derived confidence

`derive_confidence(err, cls)` in `src/classifier/confidence.py` doesn't
trust the LLM's raw self-report. It blends three signals:

```
structure_score    = 1.0        # parser resolved BOTH file=plc.st AND line=30
specificity_score  = 1.0        # matiec.constant_assignment is in _KNOWN_CATEGORIES
llm_score          = 0.8        # avg of (0.9, 0.7) raw confidences

confidence = 0.4 × 1.0 + 0.3 × 1.0 + 0.3 × 0.8
           = 0.4   + 0.3   + 0.24
           = 0.94
```

That `0.94` is what ships in the response.

For `err_002` (noise) and `err_000/001/004/005` (downstream), the
synthesisers set fixed confidence values (0.95 for noise, 0.9 for
downstream) — they don't go through the derived blend.

---

## Step 8 — Final HTTP response

```jsonc
{
  "errors": [
    {
      "parsed": {
        "id": "err_003",
        "stage": "iec_compilation",
        "category": "matiec.constant_assignment",
        "message": "Assignment to CONSTANT variables is not allowed.",
        "source_location": {"file": "plc.st", "line": 30, "column": 4, "end_line": 30, "end_column": 12},
        "is_noise": false
      },
      "severity": "blocking",
      "stage": "iec_compilation",
      "fix_complexity": "trivial",
      "root_cause": "The target variable is declared inside a <localVars constant=\"true\">...",
      "suggestions": [
        {"title": "Make the variable non-constant in the XML interface", "before_snippet": "...", "after_snippet": "...", "confidence": 0.9},
        {"title": "Remove the assignment from the ST body",              "before_snippet": "...", "after_snippet": "...", "confidence": 0.7}
      ],
      "confidence": 0.94                    // ← derived, not LLM-self-reported
    },
    /* err_000, err_001 — synthesised: severity=info, "Fix the primary root cause (err_003)" */
    /* err_002          — synthesised: severity=info, "Ignore — recurring pipeline noise" */
    /* err_004, err_005 — synthesised: severity=info, "Downstream symptom"               */
  ],
  "primary_root_ids": ["err_003"],
  "provider": "google",
  "latency_ms": 1858.4
}
```

The engineer reads `err_003` (top of the array, severity=blocking) and
acts on it. Everything else is shown but clearly marked as `info`.

---

## High level view:

```
23 lines of raw error text
        │
        ▼   parser  (Python, deterministic, ~0.5 ms)
6 ParsedError + cascade DAG
        │
        ▼   classifier dispatching
1 primary → LLM      |       5 others → synthesised locally (free)
        │
        ▼   Gemini call  (network, ~2 s)
LLMClassification {severity, complexity, root_cause, suggestions[]}
        │
        ▼   derived confidence  (parser × specificity × LLM raw)
ClassifiedError {confidence=0.94}
        │
        ▼
JSON response — engineer reads err_003 and acts on it
```

Total latency ~2 s, dominated entirely by the LLM call. Everything
before and after is essentially free.

Two recurring patterns at every step:

- **Narrow from breadth to depth** — text → structure → judgment → action
- **Deterministic where possible, LLM only where judgment is genuinely needed** — saves tokens, latency, and accuracy on the parts where regex wins

---

## Where to look next

- For the *why* behind each design choice, see [`parser.md`](parser.md).
- For the actual extractor regex patterns and their edge cases, read
  `src/parser/extractors.py` directly — it's ~250 lines.
- For how the prompts are built, see `src/classifier/prompts.py`.
- For the live LLM smoke output (which produced the Gemini snippet above),
  run `python scripts/smoke.py`.
