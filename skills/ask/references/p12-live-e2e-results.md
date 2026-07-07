# P12 Live E2E Test Results — SDLC Multi-Phase Pipeline

**Date:** 2026-06-28
**Context:** P12 of the SDLC improvement plan — first live E2E tests for the
multi-phase SDLC pipeline (plan→design_tests→implement→run_tests→debug_cascade
→tech_docs→simplify→tech_docs→council_review).

## Test Results

| Test | Scope | Status | Time | Key Finding |
|------|-------|--------|------|--------------|
| P12-A `test_sdlc_build_minimal` | plan→tests→implement→run_tests | ✅ PASSED | 129s | Cascade qwen→kimi works; palindrome output `True\nFalse` correct |
| P12-B `test_sdlc_build_with_docs` | +tech_docs→simplify→tech_docs | ✅ PASSED | 324s | All 8 phases work; docs 1456 chars, simplify 1487 chars |
| P12-C `test_sdlc_build_full_pipeline` | +council_review (all 9 phases) | 🔄 RE-RUN NEEDED | 125s→fail | `extracted_code=None` despite content present — extraction too strict |
| P12-D `test_sdlc_debug_cascade_standalone` | debug_cascade() directly | ✅ Written, not yet run | — | Tests cascade independently (qwen→kimi) |
| P12-E `test_sdlc_via_run_pipeline` | triage→routing→SDLC integration | ✅ Written, not yet run | — | Tests full run_pipeline() → SDLC routing |

## Bugs Found & Fixed

### Bug 1: `toolsets='web'` + `max_turns=5` causes models to attempt tool calls

Models with tool access (toolsets='web', max_turns=5) attempted `execute_code`
tool calls instead of generating output text. Affected 4 functions:

| Function | File:line | Fix |
|----------|----------|-----|
| `implement()` | sdlc.py:307 | `toolsets=''`, `max_turns=1` |
| `tech_docs()` | sdlc.py:706 | `toolsets=''`, `max_turns=1` |
| `simplify_code()` | sdlc.py:779 | `toolsets=''`, `max_turns=1` |
| `council_review()._dispatch_seat()` | sdlc.py:878 | `toolsets=''`, `max_turns=1` |

**Root cause:** The pipeline passes `toolsets` from routing into SDLC phase
functions. When routing assigns `toolsets='web'` (for build_code), the generation
phases inherit it — but these phases should output code/text directly, not call
tools. The prompt already says "Do not use file tools" but models with tool
access ignore that and call tools anyway.

**Lesson:** Generation phases (implement, tech_docs, simplify, council) must
always use `toolsets=''` and `max_turns=1`. Only routing/inspection phases
(plan, design_test_suites) may use tools.

### Bug 2: `extract_python_code()` too strict — fails on valid code blocks

The extraction function's Strategy 2 (generic ``` blocks) required Python
keywords (`def`, `import`, `class`, `print(`) to return code. If a model outputs
a code block without these keywords (e.g. a script starting with `if __name__`),
extraction returned None → pipeline silently "succeeded" with no code.

**Fix:** Added `return` and `if __` to the keyword list (Strategy 2), and added
a fallback that returns the block even without keywords. Also added a pipeline
guard: if `extracted_code` is None but `code_result['content']` has content,
try lenient extraction (any ``` block), then raw content if >50 chars with
Python keywords.

### Bug 3: Pipeline silently succeeds with `extracted_code=None`

When `extract_python_code()` returned None, the pipeline continued to
`run_test_suites` with None code, or reported success with no code. Now the
pipeline returns `pipeline_status='implement_failed'` if no code can be
extracted after all fallback strategies.

### Bug 4: `extract_python_code()` takes first block, not largest

Strategy 1 used `re.search` (first match only). Models may emit multiple
```python blocks (plan in one, code in another). Changed to `re.findall` +
return largest block.

## Hardening Gaps Confirmed (P14-D through P14-G)

### P14-D: simplify_code() never re-tests simplified code

P12-B showed simplify produced 1487 chars of code that was never verified.
Fix: re-execute test suites against simplified code; revert on failure.

### P14-E: council_review() partial failure handling

3-model parallel dispatch — if one fails silently, result is incomplete.
Fix: track per-seat status; mark as 'partial' if some fail.

### P14-F: pipeline timeout too short for SDLC mode

P12-B took 324s for a simple palindrome checker. `run_pipeline()` timeout=300s
is too short. Fix: separate `pipeline_timeout` param (default 900s).

### P14-G: debug_cascade() doesn't pass original code to attempt 2

Kimi gets error feedback but not the original failed code. Fix: include both
in attempt 2 prompt.
