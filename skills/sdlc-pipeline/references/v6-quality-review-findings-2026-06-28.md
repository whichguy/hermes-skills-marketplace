# v6 Quality Review — Advisor Findings & Fix Plan (2026-06-28)

2-seat advisor panel (DeepSeek V4 Pro + Kimi K2.7 Code) reviewed the v6 iterative
state machine implementation in `sdlc_state.py` (1421 lines). Both independently
found the same 5 critical issues with strong consensus.

## Panel

| Seat | Model | Time | Output |
|---|---|---|---|
| Architect | deepseek-v4-pro:cloud | 162.7s | 10.6KB |
| Code Reviewer | kimi-k2.7-code:cloud | 53.9s | 17.7KB |
| Generalist | glm-5.2:cloud | timed out | — |

## Convergent Findings (both advisors agree)

### HIGH — Must Fix

1. **Checkpoint/resume is not real** — `save_state()` persists 7 fields, `load_state()` only restores 2. Stagnation counters saved but never restored. Critical fields (`last_plan`, `prev_gaps`, `prev_pass_count`, `state`) not persisted. A resume starts from INIT with all context lost.

2. **`iterative_transition()` is dead code** — fully implemented (lines 897-963) but never called from `run_iterative_state_machine()`. All transitions are inline. If wired in, it has bugs (double iteration increment, LINT_FIX ignores failures).

3. **Debug cascade failure → infinite loop** — when `debug_cascade()` fails completely (line 1272-1274), state goes to PLAN with no stagnation counter incremented. Can burn all 45 iterations with no early exit.

4. **`gap_stagnation` uses exact string equality** — natural language gap descriptions with slightly different wording for the same structural gap won't match. Counter resets when it shouldn't.

5. **`commit_hash` passed as `"pending"`** — `append_learning()` called before `git_commit()`, so the learning entry never gets the real commit hash.

### MEDIUM — Both Advisors Flagged

6. v6 dispatches don't set `thinking` levels (v5 sets plan=medium, implement=low)
7. Wide loop threshold `>= 1` is aggressive — first repeated root cause triggers re-planning
8. `uncertain_streak` not reset on HUMAN_REVIEW entry
9. Coder has terminal toolsets but told not to run lint
10. Duplicate import block (lines 33-43 and 60-70)
11. `file_paths` always empty in learnings

### CONFIRMED — Both Advisors Verified Correct

- State machine flow (INIT→PLAN→IMPLEMENT→LINT_FIX→RUN_TESTS→DEBUG→VERIFYING) — no dead ends
- Model assignments correct (GLM planner, qwen-coder implement, deepseek verifier, cascade debugger)
- Context passing correct (PLANNING gets learnings+code+gaps, IMPLEMENTING gets plan, VERIFYING gets PROJECT.md+code)
- `repeated_root_cause()` checked BEFORE appending (off-by-one fix correct)
- LINT_FIX retry counter resets on success, escape hatch at 3 → FAILED
- Three independent stagnation counters don't interfere
- Impasse report dispatches DeepSeek for diagnosis
- Resume counter incremented after FAILED
- v5 `run_state_machine()` and `default_transition()` fully intact

## Fix Plan (8 fixes, ~135 lines changed)

### Fix 1: Checkpoint/resume — expand save/load

**`save_state()` call (line 1340):** expand from 7 to 15 fields — add `state`, `last_plan`, `prev_gaps`, `prev_pass_count`, `prev_passing_tests`, `uncertain_streak`, `lint_retry_count`, `start_time`, `wall_clock_budget`.

**`load_state()` restore (line 1018-1026):** restore all 15 fields. Resume from saved state (not always INIT). Only set `state = SDLCState.INIT` when no saved state exists.

### Fix 2: Debug cascade failure — add stagnation signal

Line 1272-1274: increment `run.test_stagnation` on cascade failure. Check against `stagnation_limit` → FAILED if exceeded.

### Fix 3: gap_stagnation — normalized text comparison

Line 1313: use `re.sub(r"\s+", " ", (text or "").lower().strip())` normalization (same as `repeated_root_cause()`).

### Fix 4: commit_hash ordering

Lines 1239-1253: move `git_commit()` before `append_learning()`. Capture real hash via `git rev-parse --short HEAD`.

### Fix 5: Delete iterative_transition()

Delete lines 897-963. The inline transitions in `run_iterative_state_machine()` are the single source of truth.

### Fix 6: Reset uncertain_streak on HUMAN_REVIEW

Line 1333-1334: add `run.uncertain_streak = 0` before entering HUMAN_REVIEW.

### Fix 7: Remove duplicate import block

Delete lines 60-70 (duplicate of lines 33-43).

### Fix 8: Set thinking levels on v6 dispatches

- PLANNING (line 1095): add `thinking="medium"`
- IMPLEMENTING (line 1128): add `thinking="low"`
- VERIFYING (line 1285): add `thinking="high"`

## Design Insight: 45 Iterations Changes Everything

When max_iterations scales from 5 to 45, **stagnation detection becomes the primary terminator** and max_iterations becomes a safety net. This means:

- Stagnation counters must be reliable (exact string match is not)
- Checkpoint/resume must actually work (losing state on resume is unacceptable)
- Debug cascade failure needs its own stagnation signal (otherwise it burns iterations)
- The wide-loop threshold (`>= 1` vs `>= 2`) matters more at scale
