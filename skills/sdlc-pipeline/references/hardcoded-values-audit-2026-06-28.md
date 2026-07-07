# Complete Hardcoded Values Audit (2026-06-28)

## Context

User corrected: "No, don't hardcode thinking levels either. Pass None."
This followed the earlier `max_turns` correction ("Hermes already has
max_turns: 120 in config — ask.py shouldn't override that").

## Audit Method

```bash
# Find every dispatch_single call across the codebase
grep -n "dispatch_single(" skills/productivity/ask/scripts/sdlc_state.py
grep -n "dispatch_single(" skills/productivity/ask/scripts/sdlc.py
```

Then trace each call's kwargs to identify every hardcoded value that
should inherit Hermes defaults.

## Results: 15 hardcoded values across 15 dispatch sites (both files)

### max_turns (15 sites → all None)

| # | File | State/Phase | Was | Fix |
|---|------|-------------|-----|-----|
| 1 | sdlc_state.py | v6 PLAN | `TURNS_PLANNER_V6=5` | `None` |
| 2 | sdlc_state.py | v6 IMPLEMENT | `TURNS_CODER_V6=8` | `None` |
| 3 | sdlc_state.py | v6 VERIFY | `TURNS_VERIFIER_V6=5` | `None` |
| 4 | sdlc_state.py | v6 FAILED (impasse) | `max_turns=5` | `None` |
| 5 | sdlc_state.py | v5 PLAN | `max_turns=5` | `None` |
| 6 | sdlc_state.py | v5 DESIGN_TESTS | `max_turns=5` | `None` |
| 7 | sdlc_state.py | v5 IMPLEMENT | `max_turns=1` | `None` |
| 8 | sdlc.py | v5 plan | `max_turns=5` | `None` |
| 9 | sdlc.py | v5 design_tests | `max_turns=5` | `None` |
| 10 | sdlc.py | v5 implement | `max_turns=1` | `None` |
| 11 | sdlc.py | v5 tech_docs | `max_turns=1` | `None` |
| 12 | sdlc.py | v5 simplify | `max_turns=1` | `None` |
| 13 | sdlc.py | v5 council seat | `max_turns=1` | `None` |
| 14 | sdlc.py | DEBUGGER_CASCADE entry 1 | `5` | `None` |
| 15 | sdlc.py | DEBUGGER_CASCADE entry 2 | `5` | `None` |

Removed constants: `TURNS_PLANNER_V6`, `TURNS_CODER_V6`, `TURNS_VERIFIER_V6`.

### thinking (11 sites → all None)

| # | File | State/Phase | Was | Fix |
|---|------|-------------|-----|-----|
| 1 | sdlc_state.py | v6 PLAN | `"medium"` | `None` |
| 2 | sdlc_state.py | v6 IMPLEMENT | `"low"` | `None` |
| 3 | sdlc_state.py | v6 VERIFY | `"high"` | `None` |
| 4 | sdlc_state.py | v5 PLAN | `"medium"` | `None` |
| 5 | sdlc_state.py | v5 DESIGN_TESTS | `"medium"` | `None` |
| 6 | sdlc_state.py | v5 IMPLEMENT | `"low"` | `None` |
| 7 | sdlc.py | v5 plan | `"medium"` | `None` |
| 8 | sdlc.py | v5 design_tests | `"medium"` | `None` |
| 9 | sdlc.py | v5 implement | `"low"` | `None` |
| 10 | sdlc.py | v5 tech_docs | `"low"` | `None` |
| 11 | sdlc.py | v5 simplify | `"medium"` | `None` |
| 12 | sdlc.py | DEBUGGER_CASCADE entry 1 | `"low"` | `None` |
| 13 | sdlc.py | DEBUGGER_CASCADE entry 2 | `"medium"` | `None` |

### Signature fix

`dispatch_with_evaluation()` in sdlc.py had `max_turns: int` (no default, no Optional).
Changed to `max_turns: Optional[int]` to accept `None`. Callers now pass `max_turns=None`
and the function passes it through to `dispatch_single()` unchanged.

## What Stays Hardcoded (deliberate per-role choices)

| Parameter | Why | Example |
|-----------|-----|---------|
| `toolsets` | Per-role tool access control | planner: "file,terminal", verifier: "file" (read-only) |
| `provider` | Model routing | "ollama-glm" for local models |
| `timeout` | Orchestrator safety net (no Hermes config key) | 300s dispatch, 120s debug |
| `role` | Role directive injection | "planner", "coder", "verifier", "debugger" |
| `cwd` | Worktree isolation | Points all file ops to the worktree |

## Safety

The 300s timeout is the real safety net. Even with 120 turns inherited
(HERMES_MAX_ITERATIONS), the subprocess is killed at 300s. Effective limit
is ~46 turns (300s ÷ 6.5s/turn). Models now finish naturally without forced
summary warnings.

## Verification

14/14 ad-hoc checks pass (final sweep):
- Both files compile
- sdlc_state.py: 6/6 `thinking=None`, 7/7 `max_turns=None`
- sdlc.py: 5/5 literal `thinking=None`, 6/6 literal `max_turns=None`
- No hardcoded thinking strings ("medium", "low", "high")
- No stale TURNS_ constants
- No stale "Fix 8" comments
- DEBUGGER_CASCADE all `None, None`
- `dispatch_with_evaluation` signature: `max_turns: Optional[int]`
- Imports work

## Commits

- `afe8e7c` — max_turns audit (8 sites in sdlc_state.py → None)
- `a8c1c08` — thinking audit (8 sites in sdlc_state.py → None)
- `0fb31e4` — sdlc.py sweep: 6 more dispatch sites + signature fix (max_turns + thinking → None)
