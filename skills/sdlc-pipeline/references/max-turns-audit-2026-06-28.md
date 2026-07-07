# max_turns=None Audit (2026-06-28)

## Problem

The v6 SDLC orchestrator had hardcoded `max_turns` values on every `dispatch_single()` call:
- v6 PLAN: `TURNS_PLANNER_V6=5`
- v6 IMPLEMENT: `TURNS_CODER_V6=8`
- v6 VERIFY: `TURNS_VERIFIER_V6=8`
- v6 impasse diagnosis: `max_turns=5`
- v5 PLAN: `max_turns=5`
- v5 DESIGN_TESTS: `max_turns=5`
- v5 IMPLEMENT: `max_turns=1`
- DEBUGGER_CASCADE (both entries): `max_turns=5`

The coder model (qwen3-coder-next) was hitting the 8-turn limit on simple 2-file projects, producing "Reached maximum iterations (8). Requesting summary..." warnings in its output. The user asked "Why would the iterations response be different?" — the answer was that `--max-turns` controls the inner loop (tool-calling iterations per subprocess), not the outer loop (orchestrator state machine cycles).

## Root Cause

`dispatch_single(max_turns=N)` passes `--max-turns N` to `hermes chat -q`. This sets `agent.max_iterations = N` in the subprocess. When the model exhausts all turns without naturally stopping, Hermes calls `handle_max_iterations()` which prints the warning and forces a final text-only response.

The hardcoded values were inappropriately low:
- 5 turns for a planner that needs to read files + write a plan
- 8 turns for a coder that needs to write multiple files + run tests
- 1 turn for a v5 coder (model can barely do anything in 1 turn)

## Fix

Pass `max_turns=None` everywhere. When `None`, `dispatch_single()` omits the `--max-turns` flag entirely, and the subprocess inherits the Hermes default (120 via `HERMES_MAX_ITERATIONS`).

The 300s timeout (`TIMEOUT_DISPATCH_V6`) is the real safety net — it kills the subprocess regardless of how many turns the model has used. At ~6.5s/turn, 300s allows ~46 turns, which is plenty for any single phase.

## Changes

| # | File | State | Was | Now |
|---|------|-------|-----|-----|
| 1 | sdlc_state.py | v6 PLAN | 5 | None |
| 2 | sdlc_state.py | v6 IMPLEMENT | 8 | None |
| 3 | sdlc_state.py | v6 VERIFY | 8 | None |
| 4 | sdlc_state.py | v6 impasse | 5 | None |
| 5 | sdlc_state.py | v5 PLAN | 5 | None |
| 6 | sdlc_state.py | v5 DESIGN_TESTS | 5 | None |
| 7 | sdlc_state.py | v5 IMPLEMENT | 1 | None |
| 8 | sdlc.py | DEBUG cascade | 5 | None (both) |

Removed constants: `TURNS_PLANNER_V6`, `TURNS_CODER_V6`, `TURNS_VERIFIER_V6`.

## Verification

11/11 ad-hoc checks pass:
- Both files compile
- No stale TURNS_ constants
- 7/7 dispatch_single calls pass `max_turns=None`
- Both DEBUGGER_CASCADE entries use `None`
- Imports work, timeouts unchanged

Commit: `afe8e7c`
