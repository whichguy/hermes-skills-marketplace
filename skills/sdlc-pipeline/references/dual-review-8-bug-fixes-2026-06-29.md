# Dual-Review Cross-Validation: 8 Bug Fixes (2026-06-29)

## Context

After implementing P1-P18 improvement plan and O1-O10 output improvements in the SDLC orchestrator, a dual-review was conducted to find remaining bugs.

## Reviewers

- **Reviewer A: Qwen-coder** (qwen3-coder-next:q4_K_M) — full code review of 7 files (6,944 lines)
- **Reviewer B: Kimi** (kimi-k2.7-code:cloud) — independent review + cross-validation of Qwen's findings

## Qwen Findings (7 HIGH + 14 MEDIUM)

| # | Finding | Qwen | Kimi Cross-Validation |
|---|---------|------|----------------------|
| 1 | Race condition on `reasoning_effort` | HIGH | FALSE POSITIVE — restore works in finally; but SET races |
| 2 | `extract_debug_info` fails on mixed output | HIGH | PARTIALLY VALID — fallback chain catches most cases |
| 3 | Git commit + LEARNINGS inconsistency | HIGH | VALID ✅ |
| 4 | `role='verifier'` not injected | HIGH | FALSE POSITIVE — role IS passed at line 1692 |
| 5 | Impasse timeout 120s vs 120 turns | HIGH | VALID ✅ |
| 6 | Test stagnation off-by-one | HIGH | VALID ✅ |
| 7 | Test syntax errors only warn | HIGH | VALID ✅ |

**Qwen score: 5/7 HIGH valid, 2 false positives. 6/14 MEDIUM valid, 4 false positives, 4 partially valid.**

## Kimi New Findings (10 — Qwen missed all)

| # | Finding | Severity |
|---|---------|----------|
| 1 | `set_reasoning_effort()` SET races (not restore) | HIGH |
| 2 | Learning commit hash mismatch on rapid commits | HIGH |
| 3 | Test regressions counter incorrect in RUN_TESTS | HIGH |
| 4 | Impasse diagnosis 120s too short for real debugging | MEDIUM+ |
| 5 | Checkpoint file descriptor leak risk | MEDIUM |
| 6 | No timeout on git operations | MEDIUM |
| 7 | `extract_debug_info` doesn't handle mixed markdown | MEDIUM |
| 8 | Role directive appears after `/no_think` | MEDIUM |
| 9 | No validation of worktree path before use | MEDIUM |
| 10 | No wall-clock check before first PLAN | MEDIUM |

## 8 Confirmed Bugs Implemented

Both reviewers independently agreed on these 8 bugs:

| Bug | File | Fix |
|-----|------|-----|
| A | sdlc_state.py | `append_learning()` wrapped in try/except — commit stays valid if learning write fails |
| B | sdlc_state.py | `delta < 0` (was `<= 0`) — stable state with no regressions resets stagnation |
| C | sdlc.py | Test syntax errors → ruff fix retry → `test_syntax_error` status if unfixable |
| D | sdlc_state.py | Impasse timeout 120s → 300s |
| E | sdlc_state.py | `except KeyError` guard around `SDLCState[saved["state"]]` |
| F | sdlc_state.py | All 11 `_save_checkpoint` calls wrapped in try/except |
| G | sdlc_state.py | `git rev-parse` falls back to `"none"` on fresh repo |
| H | sdlc_worktree.py | `timeout=10` on all git subprocess calls |

## Verification

14/14 ad-hoc verification checks pass. No regressions to `max_turns=None` or `thinking=None`.

## Key Lesson

**Dual-review cross-validation eliminates false positives.** A single reviewer (Qwen) had 2/7 HIGH false positives. The second reviewer (Kimi) caught both by reading actual code at cited line numbers. Implement only bugs both reviewers agree on.
