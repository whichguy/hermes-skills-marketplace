# P12 Live E2E Test Findings — 2026-06-28

Full 5-test live E2E validation of the SDLC pipeline (`sdlc.py`), plus parallel
advisor review (DeepSeek + Kimi). 7 findings (4 fixed, 3 open), 8 advisor
recommendations.

## P12 Test Results

| Test | Scope | Status | Time | Key Result |
|------|-------|--------|------|------------|
| P12-A | plan→tests→implement→run_tests (minimal) | ✅ PASSED | 129s | Cascade qwen→kimi works |
| P12-B | docs+simplify (8 phases) | ✅ PASSED | 324s | All phases produce content |
| P12-C | Full 9-phase + council (3 seats) | ✅ PASSED | 327s | Council produced 7 improvement items |
| P12-D | Debug cascade standalone | ✅ PASSED | 62s | Qwen fixed bug on 1st attempt |
| P12-E | run_pipeline() integration | ❌ TIMEOUT | 600s | Confirms P14-F: SDLC needs 900s+ |

## 7 Findings

### Fixed (4)

| # | Finding | Root Cause | Fix |
|---|---------|------------|-----|
| 1 | `toolsets='web'` + `max_turns=5` in generation phases | Models attempted tool calls instead of outputting code | Removed `toolsets` param entirely from 4 functions; hardcoded `toolsets=''`, `max_turns=1` |
| 2 | `extract_python_code()` too strict | Only matched triple-backtick blocks with language tag | Added `return`/`if __` keyword matching, lenient fallback, pipeline guard |
| 3 | Pipeline silently succeeds with `extracted_code=None` | No guard after extraction failure | Added `pipeline_status='implement_failed'` guard |
| 4 | Extraction takes first block, not largest | `re.search` returns first match | Changed to `re.findall` + `max(blocks, key=len)` |

### Open (3)

| # | Finding | Severity | Description |
|---|---------|----------|-------------|
| 5 | AI-generated test suite has incorrect assertions | HIGH | Generated test asserted `is_palindrome("Was it a car or a cat I saw")` is False, but it IS a palindrome. Pipeline "passed" with wrong tests. Need test validation phase or oracle. |
| 6 | `tech_docs()` fails silently (model non-determinism) | MEDIUM | Second P12-C run: tech_docs pass 1 returned None content. Pipeline continued but test assertion failed. Enhancement phases should be optional — pipeline should handle gracefully, not crash. |
| 7 | Full `run_pipeline()` → SDLC path exceeds 600s | HIGH | 9-phase SDLC via run_pipeline() timed out at 600s in tech_docs dispatch. Pipeline timeout=300s is too short for SDLC mode. Need 900s+ timeout. |

## 8 Advisor Recommendations (DeepSeek + Kimi)

| # | Finding | Priority | Status |
|---|---------|----------|--------|
| A1 | `extract_python_code()` lenient fallback can return prose as code | HIGH | Use `ast.parse()` to verify syntax before returning |
| A2 | No CI-runnable regression tests for P14-A fixes | HIGH | Write P14-C regression tests BEFORE P14-D/E/F/G |
| A3 | API error text in code blocks not guarded | HIGH | Add `is_api_error()` check before lenient extraction |
| A4 | Council quorum model (success/partial/failed) | HIGH | ✅ DONE — Kimi implemented quorum + `is_api_error()` seat filtering |
| A5 | `toolsets` param removed from generation functions | MEDIUM | ✅ DONE — Architecturally cleaner than hardcoding |
| A6 | Debug cascade should pass full test output, not just stderr | HIGH | Include test suite name + full pytest output |
| A7 | Pipeline-level timeout tracking needed | MEDIUM | Check elapsed at start of each phase |
| A8 | Execution order: P14-C before P14-D/E/F/G | MEDIUM | Regression tests before hardening |

## Key Patterns Discovered

### Output-only dispatch phases need `toolsets=''` + `max_turns=1`

When dispatching a model whose job is to *produce* code or text (not to use
tools), strip tool access entirely. Passing `toolsets='web'` or
`toolsets='file'` to a code-generation or review phase causes models to attempt
tool calls instead of outputting the requested content.

**Affected phases:** `tech_docs`, `simplify_code`, `council_review`, `implement`
(code generation), and any other phase where the model's output IS the
deliverable.

**Phases that genuinely need tools:** `plan` (file inspection),
`design_test_suites` (codebase inspection).

### Council quorum model

Instead of binary pass/fail, use a 3-status model:
- `success` — all seats responded
- `partial` — some seats responded (2/3, 1/2)
- `failed` — no seats responded or all API errors

Filter seats with `is_api_error()` before counting. Return `status` and
`total_seats` in the result dict.

### Advisor review pattern for plan validation

When a plan needs review, dispatch DeepSeek + Kimi in parallel as individual
`delegate_task` calls (not batch). DeepSeek catches architectural/design issues;
Kimi catches code-level issues and can auto-implement fixes. Both return
independently — results stream in as each finishes.

### AI-generated test quality problem

AI-generated test suites can have incorrect assertions that still pass. The
pipeline has no way to detect this — it only checks whether tests pass, not
whether assertions are correct. A test oracle or validation phase is needed.

### Model non-determinism in enhancement phases

`tech_docs()` and other enhancement phases can return None content due to model
non-determinism. The pipeline should treat enhancement phases as optional —
log warnings, don't crash. Tests should handle None gracefully.
