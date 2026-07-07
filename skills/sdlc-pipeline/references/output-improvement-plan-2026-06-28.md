# SDLC Orchestrator Output Improvement Plan (2026-06-28)

## Context

After 7 E2E tests (81 total tests passing) validated the v6 iterative state machine, the orchestrator output was inspected for quality. The state machine works functionally but the progress reporting and final summary are minimal — users monitoring long-running projects can't see what's happening without inspecting worktree files.

## 10 Improvements (Prioritized)

### P0 — Transform Output From Minimal to Informative

| # | Issue | Current | Desired | Lines |
|---|---|---|---|---|
| **O1** | No per-iteration summary | Raw state transitions only | Structured "Iteration N Summary" block: states visited, test delta, files, learnings, git hash, elapsed, next step | ~25 |
| **O2** | Empty learning field | `learning: ` (blank) | Fallback chain: explicit "learning:" → root_cause → first content line | ~8 |
| **O3** | No model output preview | `✅ code generated (468 chars)` | Add 150-char preview of model response after each dispatch | ~8 |

### P1 — Make Final Summary Actionable

| # | Issue | Current | Desired | Lines |
|---|---|---|---|---|
| **O4** | No state history in final summary | `Iterations: 2` | `Path: INIT→PLAN→IMPLEMENT→LINT→TEST→VERIFY→COMPLETE` + `Iterations: 2/3` | ~10 |
| **O5** | No files listed | Missing | `Files: operations.py, calculator.py, test_calculator.py` | ~3 |
| **O7** | No git commit in progress | Only in LEARNINGS.jsonl | `git: commit 98f1ac8` after each commit | ~1 |
| **O9** | Plan not shown | `✅ plan generated (2736 chars)` | First 10 lines of plan content emitted inline | ~5 |

### P2 — Polish

| # | Issue | Current | Desired | Lines |
|---|---|---|---|---|
| **O6** | Garbage in LEARNINGS failures | `["====..."]` separator lines | Filter: skip names with `==` or `__`, require `::` separator | ~5 |
| **O8** | GAPS content not structured | Single truncated line | Emit each gap line indented | ~5 |
| **O10** | No wall-clock progress | No time remaining shown | `[231s/300s remaining]` in state headers | ~5 |

## Sample Improved Output

### During iteration:
```
━━━ Iteration 2/4 — PLANNING ━━━ [231s/360s remaining]
  ✅ plan generated (2782 chars, 20.1s)
  plan:
    ## Iteration Plan — Iteration 1/4
    1. Write binary_search.py with iterative two-pointer approach
    2. Write test_binary_search.py with 7 test cases
    3. Handle edge cases: empty array, single element, duplicates
━━━ Iteration 2 — IMPLEMENTING ━━━ [211s/360s remaining]
  ✅ code generated (1481 chars, 58.0s)
  preview: def binary_search(arr, target): """Return the index of target...
━━━ Iteration 2 — LINT_FIX ━━━ [153s/360s remaining]
  ✅ lint clean
━━━ Iteration 2 — TESTING ━━━ [153s/360s remaining]
  tests: 0/2 passed (Δ +0, regressions: 0)
━━━ Iteration 2 — DEBUGGING ━━━ [153s/360s remaining]
  📝 wrote fix to binary_search.py (1145 chars)
  ✅ debug fix (kimi, 32.4s)
  learning: Missing module file — coder didn't create binary_search.py
  git: commit 98f1ac8
  → tight loop → TESTING (re-run tests)
━━━ Iteration 2 — TESTING ━━━ [121s/360s remaining]
  tests: 13/13 passed (Δ +13, regressions: 0)

━━━ Iteration 2 Summary ━━━
  States:      IMPLEMENT → LINT_FIX → TEST → DEBUG → TEST → VERIFY
  Tests:       13/13 passed (was 0/2, Δ +13)
  Files:       binary_search.py, test_binary_search.py
  Learnings:   1 entry — "missing module file"
  Git:         98f1ac8
  Elapsed:     133s (iteration), 133s (total)
  Verdict:     SATISFIED
  Next:        COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Final summary:
```
━━━ ✅ COMPLETE ━━━
  Iterations:   2/4
  Tests:        13/13 passed
  Elapsed:      133s
  Learnings:    1 entry
  Files:        binary_search.py, test_binary_search.py
  Path:         INIT→PLAN→IMPLEMENT→LINT_FIX→TEST→DEBUG→TEST→VERIFY→COMPLETE
  Verdict:      SATISFIED
━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Implementation Notes

- All changes in `sdlc_state.py` (~75 lines total)
- O1 needs: per-iteration state tracking list, test delta calculation, worktree file listing
- O2 needs: fallback chain in `extract_debug_info()` — explicit "learning:" → root_cause → first content line
- O3 needs: 150-char preview after each of 4 dispatch results (PLANNING, IMPLEMENTING, DEBUGGING, VERIFYING)
- O6 needs: regex filter in `run_tests_in_worktree()` — skip names with `==` or `__`, require `::` separator
- O10 needs: wall-clock remaining calculation before each state header emit

## Validation

After implementing, re-run 2 E2E tests (calculator + binary search) to validate output format. Verify per-iteration summary, model preview, learning fallback, file listing, and state history all appear correctly.
