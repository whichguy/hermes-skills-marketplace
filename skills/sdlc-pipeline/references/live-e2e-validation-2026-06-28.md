# Live E2E Validation — 2026-06-28

Validated the `sdlc.py` multi-phase pipeline (`run_test_first_pipeline`) against
live Ollama models. Tests live in `tests/test_pipeline_e2e.py::TestPipelineSDLCE2E`.

## P12-A: Minimal Build (4 phases) — ✅ PASSED (129s)

**Path:** plan → design_tests → implement → run_tests (no docs, no council)
**Prompt:** "Write is_palindrome(s) function with main block testing 'racecar' and 'hello'"

| Phase | Result | Notes |
|-------|--------|-------|
| 1. Plan | ✅ 3730 chars | GLM produced structured plan |
| 2. Design tests | ✅ 12643 chars, 3 suites | Multi-suite parsing works |
| 3. Implement | ✅ Code extracted | |
| 4. Run tests | ❌ 1 failure → debug cascade | Cascade qwen→kimi triggered |
| 4b. Debug (qwen) | ❌ Still failing | |
| 4c. Debug (kimi) | ✅ Fixed | Kimi resolved the issue |
| Final execution | ✅ returncode=0, `True\nFalse` | Correct output |

**Key learning:** Debug cascade (qwen→kimi) works correctly. Multi-suite test
parsing handles 3 suites from one model output.

## P12-B: Docs + Simplify (8 phases) — ❌→✅ (324s after fix)

**Path:** plan → design_tests → implement → run_tests → debug_cascade → tech_docs → simplify → tech_docs
**Initial result:** ❌ FAILED — `tech_docs` phase produced no content

### Root Cause

`tech_docs()`, `simplify_code()`, `council_review()`, and `implement()` all had
`toolsets='web'` and `max_turns=5`. These are **output-only phases** — the model's
job is to produce text/code, not to use tools. With tool access, models attempt
tool calls instead of outputting content:

```
Model generated invalid tool call: execute_code
```

### Fix Applied

Changed all four functions to `toolsets=''` and `max_turns=1`:

```python
# Before (broken):
prompt_model(message, model=model, toolsets='web', max_turns=5, ...)

# After (fixed):
prompt_model(message, model=model, toolsets='', max_turns=1, ...)
```

**Affected functions in `scripts/sdlc.py`:**
- `tech_docs()` — lines ~420-440
- `simplify_code()` — lines ~460-480
- `council_review()` — lines ~500-530
- `implement()` — line ~314

**Phases that genuinely need tools** (not changed):
- `plan()` — needs file inspection to read codebase
- `design_test_suites()` — needs codebase inspection

### Re-run Result (after fix)

| Phase | Result | Time |
|-------|--------|------|
| 1-4: Core pipeline | ✅ complete (incl. debug cascade) | ~129s |
| 6: tech_docs pass 1 | ✅ 1456 chars | ~30s |
| 7: simplify_code | ✅ 1487 chars | ~80s |
| 8: tech_docs pass 2 | ✅ 1500 chars | ~30s |
| Final execution | ✅ returncode=0, `True\nFalse` | |

**88/88 mock tests (`test_sdlc.py`) passed** after the fix — no regressions.

## P12-C: Full 9-Phase Pipeline — 🔄 Running

**Path:** All 9 phases including council_review
**Expected:** 8-12 minutes (council adds 3 parallel model dispatches)

## Verified Pitfalls

1. **`toolsets=''` + `max_turns=1` for output-only phases** — confirmed fix works.
   The error is `Model generated invalid tool call: execute_code`. Affects any
   phase where the model's output IS the deliverable (not tool calls).

2. **`os.rmdir` fails on non-empty dirs** — P12-B log showed:
   `Warning: Could not remove /opt/data/sdlc-test-run-unit: [Errno 39] Directory not empty`
   Use `shutil.rmtree` instead.

3. **Verification discipline** — the system flags files as "unverified" after
   commit even when tests were run pre-commit. Pattern: verify → commit →
   re-verify (compile + targeted tests) → clean up temp scripts.
