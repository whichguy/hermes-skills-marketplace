# E2E Test Validation — 2026-06-28

## Context

After applying A1 (word-boundary GAPS) and A2 (_save_checkpoint helper) fixes
to `sdlc_state.py`, we ran two E2E tests to validate the v6 iterative state
machine end-to-end.

## Test 1: Dry Run (state machine wiring)

**Command:** `run_iterative_state_machine(..., dry_run=True, max_iterations=2)`

**Result: ✅ PASS**

- All 6 expected states visited: INIT → PLAN → IMPLEMENT → LINT_FIX → RUN_TESTS → VERIFYING
- PROJECT.md copied to worktree ✓
- ITERATION_STATE.json checkpoint saved ✓
- No model dispatches (dry_run skips them)
- Completed in <1s

**Value:** Validates state machine wiring without model dependency. Fast,
deterministic, good for CI.

## Test 2: Real Dispatch (live model integration)

**Command:** `run_iterative_state_machine(..., dry_run=False, max_iterations=2, wall_clock_budget=300)`

**Result: ✅ COMPLETED (with findings)**

| Phase | Model | Time | Result |
|---|---|---|---|
| PLAN | glm-5.2:cloud | 62.3s | Plan generated (2,014 chars) |
| IMPLEMENT | qwen3-coder-next | 36.0s | Code generated (3,676 chars) |
| LINT_FIX | (script) | <1s | ✅ lint clean |
| RUN_TESTS | (script) | <1s | 0/0 passed |
| DEBUG | kimi cascade | 45.8s | Fix attempted |
| RUN_TESTS | (script) | <1s | 0/0 passed |
| DEBUG | qwen coder | 20.8s | Fix attempted |
| RUN_TESTS | (script) | <1s | 0/0 passed → stagnation (3/3) |

**Stagnation detection:** Correctly fired at 3/3 — the loop terminated instead
of looping forever. This validates the design.

## Findings

### F1: `git add -A` fails with exit 128 in non-git worktree

The temp worktree created by the E2E test wasn't a git repo. The orchestrator's
`git add -A` call in the debug phase failed with exit 128. The exception was
caught and logged but didn't crash the loop.

**Fix needed:** The orchestrator should `git init` in the worktree before
dispatch, or the E2E test should use a proper git worktree.

### F2: Coder model returns code as text, doesn't write files

The coder model (qwen3-coder-next) generated 3,676 chars of code but returned
it as text output — it didn't write files to the worktree. This caused 0/0
tests (no test files found) and eventual stagnation.

**Fix needed:** The dispatch prompt for the IMPLEMENT phase should instruct
the model to write files to the worktree, not just return code as text.
Alternatively, the orchestrator should extract code from the model's response
and write it to the worktree itself.

### F3: Stagnation detection works correctly

0/0 tests 3 iterations in a row → stagnation detected → loop terminated.
This is the design working as intended. The stagnation counter correctly
identified that no progress was being made.

### F4: `run.tests_passing` field name mismatch

The E2E test script referenced `run.tests_passing` but the actual field name
in `SDLCRun` is different. Minor test bug, not an orchestrator bug.

## E2E Test Pattern

The dry-run + real-dispatch pattern is recommended for all future SDLC
pipeline changes:

1. **Dry run first** — validates state machine wiring, fast (<1s), no model cost
2. **Real dispatch second** — validates model integration, ~2-5 min, uses real models
3. **Check both** — dry run catches wiring bugs; real dispatch catches prompt/model issues

## Test Files

- `/tmp/sdlc-e2e-test/PROJECT.md` — test project spec (is_palindrome)
- `/tmp/sdlc-e2e-test/test_e2e.py` — dry run test
- `/tmp/sdlc-e2e-test/test_e2e_real.py` — real dispatch test
