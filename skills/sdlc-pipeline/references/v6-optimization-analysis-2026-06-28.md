# v6 Orchestrator Optimization Analysis (2026-06-28)

Single E2E test (binary search, 15/15 tests pass, COMPLETE in 97.6s, 1 iteration).

## Timing Breakdown

| Phase | Time | % | Model | Turns |
|-------|------|---|-------|-------|
| PLAN | 24.8s | 25% | GLM-5.2 | 5 (thinking=medium) |
| IMPLEMENT | 52.1s | 53% | qwen3-coder | 8 (thinking=low) |
| LINT_FIX | ~0s | 0% | (script) | — |
| RUN_TESTS | ~0s | 0% | (script) | — |
| VERIFY | 18.3s | 19% | deepseek-v4 | 8 (thinking=high) |
| OVERHEAD | 2.4s | 2% | — | — |
| **TOTAL** | **97.6s** | **100%** | | |

**Key finding: 98% of wall-clock is model calls.** Non-model overhead is already minimal (2%).

## Optimization Opportunities (ranked by impact × feasibility)

| ID | Optimization | Savings | Feasibility | Risk |
|----|-------------|---------|------------|------|
| **OPT1** | Skip PLAN on iteration 1 — feed PROJECT.md directly to coder | ~25s (25%) | ✅ High | Low — PROJECT.md IS the plan for first iteration |
| **OPT2** | Fast-verify when all tests pass with 0 regressions — skip DeepSeek | ~18s (19%) | ✅ High | Low — trust tests when coverage is good |
| OPT3 | Reduce coder max_turns 8→4 for simple projects | ~25s (25%) | ⚠️ Med | Medium — multi-file may not finish in 4 |
| OPT4 | Cache `read_code_state` between PLAN & VERIFY in same iteration | ~0.5s | ✅ High | Low — called 2x per iteration |
| OPT5 | Skip VERIFY on iteration 1 when tests pass (trust TDD) | ~18s (19%) | ⚠️ Med | Medium — may miss edge cases |
| OPT7 | Use GLM for coder instead of qwen3-coder for simple projects | ~30s? | ⚠️ Med | Medium — GLM less code-competent |

**Combined OPT1+OPT2 savings: ~43s (44%) → 97.6s → ~55s per simple project.**

## Bugs Found

| ID | Bug | Fix |
|----|-----|-----|
| **BUG1** | Iteration counter off-by-one — shows "Iteration 2/45" on first real iteration | Move `run.iteration += 1` from PLAN to INIT, or start at -1 |
| **BUG2** | Env vars `SDLC_WALL_CLOCK`/`SDLC_MAX_ITER` not parsed — shows 7200s instead of 300s | Add `os.environ.get()` parsing at function entry |
| **BUG3** | IMPLEMENT preview shows "reached max iterations" warning from qwen — looks like orchestrator error | Filter "reached maximum iterations" from previews |

## Recommended Immediate Actions

1. **BUG1 + BUG2** — Fix iteration counter + add env var parsing (5 lines, 0 risk)
2. **OPT1** — Skip PLAN on iteration 1 (~25s savings) — PROJECT.md goes straight to coder
3. **OPT2** — Fast-verify when all tests pass (~18s savings) — trust test results, skip DeepSeek
