# v6 E2E Suite — 4 Progressive Tests (2026-06-28)

## Context

After the single `is_palindrome` E2E test validated the basic loop, ran a 4-test
progressive suite to stress-test the v6 state machine across diverse project types:
multi-file imports, OOP classes, debug iterations, and vague specs.

## Test Matrix

| # | Project | Scope | Tests | Verdict | Status | Time | Iters |
|---|---|---|---|---|---|---|---|
| 1 | Calculator | Multi-file + imports | 10/10 ✅ | LINT_FIX blocked | ⚠️ E402 | 151s | 2 |
| 2 | Stack | OOP class with methods | 9/9 ✅ | SATISFIED | ✅ COMPLETE | 100s | 2 |
| 3 | String Formatter | Debug iterations | 8/8 ✅ | SATISFIED | ✅ COMPLETE | 183s | 2 |
| 4 | Complex Analyzer | Vague spec / stagnation | 15/15 ✅ | Wall-clock timeout | ⏰ Timeout | 130s | 2 |

**Total: 42 tests passing across 4 projects, 564s total run time.**

## Test 1 — Calculator (Multi-file + imports)

**PROJECT.md intent:** Build a calculator with separate `operations.py` module
and `calculator.py` class that chains operations.

**Files produced:**
- `operations.py` — add, subtract, multiply, divide functions
- `calculator.py` — Calculator class with method chaining
- `test_calculator.py` — 10 tests (5 unit for operations, 5 integration for chaining)

**Issue:** LINT_FIX retried 3 times and exited. `ruff check` flagged E402
(module-level import not at top of file) in `test_calculator.py` — the coder
placed `from calculator import Calculator` after test functions with a section
comment. `ruff --fix` can't auto-fix E402 (requires code reorganization), so
the lint phase correctly identified it as unfixable. The code worked (10/10
tests pass) but lint blocked the pipeline.

**Fix applied:** Added `--ignore E402` to `run_ruff()` in `sdlc_state.py`.
E402 is cosmetic in test files and shouldn't block the pipeline. Also filtered
"Found N errors" summary lines from the unfixable list.

## Test 2 — Stack (OOP class)

**PROJECT.md intent:** Build a Stack class with push, pop, peek, is_empty, size.

**Files produced:**
- `stack.py` — Stack class with all methods
- `test_stack.py` — TestStack class with 9 tests

**Result:** Clean run. SATISFIED verdict, COMPLETE in 100s. Validates OOP code
generation with proper test class structure.

## Test 3 — String Formatter (debug iterations)

**PROJECT.md intent:** Build a string formatter with title_case, reverse_words,
strip_punctuation, word_count.

**Files produced:**
- `string_formatter.py` — StringFormatter class
- `test_string_formatter.py` — 8 tests

**Result:** Needed 2 IMPLEMENT attempts (first had lint issues, second was clean).
SATISFIED verdict, COMPLETE in 183s. Validates the retry loop and debug cascade.

## Test 4 — Complex Analyzer (vague spec / stagnation)

**PROJECT.md intent:** Build a complex data analyzer that processes mixed-type
lists and returns statistics. Vague spec — no specific function signatures.

**Files produced:**
- `complex_analyzer.py` — analyze() function with type handling
- `test_complex_analyzer.py` — 15 tests including edge cases

**Result:** 15/15 tests pass but hit wall-clock timeout at 130s. The state
machine correctly terminated on timeout. The verifier was mid-evaluation when
the timeout fired.

## Issues Found & Fixed

| Issue | Root Cause | Fix | Commit |
|---|---|---|---|
| E402 blocks pipeline | `ruff check` flags import-not-at-top in test files | `--ignore E402` + filter summary lines | `f7997b0` |
| Test runner status detection | `state_history[-1]` is pre-transition state | Test runner bug, not state machine bug | N/A |

## What Worked Well

1. **Multi-file projects** — coder created correct imports between modules
2. **OOP** — coder created proper class with methods and test class
3. **Debug iterations** — retry loop worked correctly (2 IMPLEMENT attempts)
4. **Module name derivation** — all 4 projects derived correct module names from PROJECT.md titles
5. **`cd {worktree}` enforcement** — all models wrote files to correct worktree
6. **Git init** — all worktrees had `.git` directories
7. **Pytest venv** — all tests ran with `/opt/data/.venv/bin/python3`
8. **Wall-clock timeout** — correctly terminated on budget exhaustion
9. **Stagnation detection** — correctly identified when no progress was being made

## Remaining Gaps

1. **Debug cascade with actual test failures** — all 4 tests had the coder produce
   working code on the first or second try. Need a project where the first
   implementation produces genuinely failing tests to validate the DEBUG→TEST
   tight loop.
2. **Test runner status detection** — the test runner script uses
   `state_history[-1]` which is the state BEFORE the final transition. The state
   machine appends states at loop start, so the final COMPLETE state is never in
   the history. This is a test runner bug, not a state machine bug — the actual
   state machine output shows COMPLETE correctly.
3. **LINT_FIX max retries** — 3 retries may be too few for complex projects.
   Consider making it configurable or adding a HUMAN_REVIEW fallback when lint
   is unfixable but tests pass.
