# P1-P18 Implementation Session (2026-06-28)

## Context

After the v6 iterative state machine was built and validated, a comprehensive
improvement plan was generated from all accumulated session learnings (17
reference docs, current code). The plan had 18 items across 5 categories:
CORRECTNESS, PERFORMANCE, ROBUSTNESS, OBSERVABILITY, ARCHITECTURE.

## Implementation Approach

Qwen-coder (qwen3-coder-next:q4_K_M) was dispatched via `delegate_task` to
implement all 18 items "with judgment" — meaning it should skip items that
don't make sense and implement the rest. The subagent ran for 15 minutes
before timing out.

## Results

### Implemented (14 items)

| Item | Category | What was done |
|------|----------|---------------|
| P1 | CORRECTNESS | `_has_negated_gaps()` — sentence-level negation analysis |
| P2 | CORRECTNESS | `root_cause_stagnation` jumps to limit instead of incrementing |
| P3 | CORRECTNESS | `cascade_stagnation` separate counter (not conflated with test_stagnation) |
| P4 | CORRECTNESS | `DiminishingReturnsTracker.max_iterations` attribute |
| P6 | OBSERVABILITY | CLI entry point with argparse |
| P7 | OBSERVABILITY | `git diff --name-only` captures changed files for learnings traceability |
| P8 | OBSERVABILITY | `read_learnings_formatted()` structured text for planner consumption |
| P9 | ROBUSTNESS | Ruff unfixable lines filtered (no summary/stats lines) |
| P12 | OBSERVABILITY | `read_learnings_formatted()` provides structured PLANNING output |
| P14 | OBSERVABILITY | `_log_event()` writes events.jsonl for structured debugging |
| P15 | OBSERVABILITY | STATUS.json written alongside checkpoint for external monitoring |
| P16 | ARCHITECTURE | Model constants from env vars (SDLC_MODEL_PLANNER, etc) |
| P17 | ROBUSTNESS | LINT_FIX → HUMAN_REVIEW when tests pass but lint stuck |
| P18 | OBSERVABILITY | Structured debug cascade context (failing test names + details) |

### Skipped (4 items)

| Item | Reason |
|------|--------|
| P5 | User explicitly rejected: "always plan and replan" |
| P10 | Parallel dispatch — needs full design pass (v3.1) |
| P11 | Patch-based isolation — needs full design pass (v3.1) |
| P13 | Import-graph analysis — premature for serial-first approach |

## Post-Hoc Fixes Required

The subagent's self-reported summary claimed all 18 items were implemented, but
post-hoc review found 3 bugs:

1. **P15 scope error**: `save_state()` referenced `run.start_time` but `run` was
   not in scope — the function receives `data` dict. Fixed: `data.get('start_time', time.time())`.

2. **P7 unwired**: `last_changed_files` field was defined and git diff was
   captured, but the captured value was never passed to `append_learning()`.
   Fixed: changed `[]` to `run.last_changed_files` in the append_learning call.

3. **P14 defined-but-never-called**: `_log_event()` function was defined but
   never called from any state transition. **Fixed 2026-06-28 (commit `73f224d`):**
   8 call sites added — INIT, PLAN, IMPLEMENT, LINT_FIX, RUN_TESTS, DEBUG,
   VERIFYING, and verdict SATISFIED. Each logs timestamp, iteration, state,
   and elapsed time to events.jsonl. Qwen-coder review caught this; fix was
   applied in a follow-up session.

## Verification

34/34 ad-hoc verification checks passed after post-hoc fixes. 3 "failures" were
regex false positives in the verification script (confirmed via direct grep).

## Key Lessons

1. **Subagent self-reports are unreliable** — always verify with `git diff` and
   targeted ad-hoc verification scripts.
2. **Local models (qwen3-coder-next) can implement 14/18 items in 15 minutes**
   but leave subtle wiring bugs. Post-hoc review is essential.
3. **User preferences are definitive** — P5 was proposed as an optimization but
   the user explicitly rejected it. The skill now marks both P5 (skip PLAN) and
   OPT2 (fast-verify) as REJECTED.
4. **Ad-hoc verification scripts need 3-5 iterations** to get regex right —
   line-number prefixes, indented comments, and passthrough kwargs all cause
   false positives.
