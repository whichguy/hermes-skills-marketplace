# E2E Round 3 Results + DeepSeek Diagnosis (2026-06-29)

## Test Results

**Total: 1266s (21 min), 5 tests, 2 PASS + 3 WARN**

| # | Test | Status | Time | Iters | Tests | Events | STATUS.json |
|---|------|--------|------|-------|-------|--------|-------------|
| 1 | Calculator | ✅ PASS | 135s | 3 | 11 | 12 | COMPLETE |
| 2 | Binary Search | ✅ PASS | 148s | 4 | 8 | 15 | COMPLETE |
| 3 | Stack | ⚠️ WARN | 360s | 8 | 0 | 28 | VERIFYING (timeout) |
| 4 | JSON Parser | ⚠️ WARN | 303s | 6 | 0 | 22 | HUMAN_REVIEW |
| 5 | Stagnation | ⚠️ WARN | 320s | 5 | 0 | 18 | FAILED (wall-clock) |

## DeepSeek Diagnosis — 3 Root Causes

| # | Issue | Root Cause |
|---|-------|------------|
| 1 | Stack stuck in VERIFYING | 300s dispatch timeout killed verifier with 148s remaining in wall-clock budget |
| 2 | JSON Parser → HUMAN_REVIEW | LINT_FIX exhausted retries, fell back to HUMAN_REVIEW even though no test files existed (coder didn't create tests) |
| 3 | Stagnation wall-clock timeout | 300s wall-clock budget too tight for 5-iteration project; no 25% remaining warning |

## 8 Fixes Applied (of 11 Proposed)

| Fix | Before | After | Commit |
|-----|--------|-------|--------|
| TIMEOUT_DISPATCH_V6 | 300s | 3600s (effectively no per-dispatch limit) | `78707a2` |
| TIMEOUT_DEBUG_V6 | 120s | 3600s | `78707a2` |
| Impasse diagnosis timeout | 300s | TIMEOUT_DISPATCH_V6 | `78707a2` |
| Wall-clock warning | None | 25% remaining alert at loop top | `78707a2` |
| LINT_FIX → HUMAN_REVIEW | Always on max retries | Check test files exist first; no test files → FAILED | `78707a2` |
| run_tests_in_worktree | Unhandled crash | try/except for TimeoutExpired, FileNotFoundError, OSError | `78707a2` |
| HUMAN_REVIEW summary | "Tests: N" (no total) | "Tests: N passed (total: M)" — shows total test count from last_test_result | `6233e05` |
| Stagnation E2E test budget | 180s | 300s (PLAN+IMPLEMENT alone took 216s in Round 3) | `6233e05` (run_round3.py) |

## 2 Fixes Rejected

| # | Proposed Fix | Reason |
|---|-------------|--------|
| 1-6 | `_dispatch_timeout()` helper + `MIN_DISPATCH_TIME` gate at 4 dispatch sites | User directed: "do not have short timeouts, let top-level handle it." Per-dispatch timeouts are now 3600s (effectively unlimited). The top-level `wall_clock_budget` is the only real timeout. |
| — | (items 1-6 were the `_dispatch_timeout`/`MIN_DISPATCH_TIME` approach across PLAN, IMPLEMENT, VERIFYING, DEBUG dispatch sites) | |

## Key Architectural Decision

**Orchestrator is the only one who interacts with the user.** Child processes ask the orchestrator to proxy. Per-dispatch timeouts are now 1 hour (effectively unlimited). The top-level `wall_clock_budget` (default 7200s) is the only real timeout. Child processes run to completion; the orchestrator decides when to stop.
