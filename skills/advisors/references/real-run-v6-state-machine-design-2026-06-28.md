# Real Run: v6 Iterative State Machine Design (2026-06-28)

> Pattern 7 (Iterative Plan Refinement) — 3 rounds, 7 advisor calls, 45-iteration scaling

## Session Flow

The user asked to incorporate the v6 iterative state machine into the SDLC skill
(rather than building a standalone `orchestrator.py`). This triggered a 3-round
iterative plan refinement using the advisors pattern.

### Round 1: Broad Review (3-seat panel)

**Plan:** v1 orchestrator state machine (7 states, undefined stagnation, 5 iterations)

| Seat | Model | Time | Key Finding |
|---|---|---|---|
| Architect | deepseek-v4-pro:cloud | 81.5s | 5 HIGH issues: stagnation undefined, LINT_FIX infinite loop, HUMAN_REVIEW no cycle limit, no INIT state, no LEARNINGS schema |
| Code Reviewer | kimi-k2.7-code:cloud | 79s | 4 issues: stagnation signals, regression tracking, counter reset logic, pseudocode inversion |
| Generalist | glm-5.2:cloud | 22.6s | 3 issues: wall-clock timeout, checkpoint/resume, impasse diagnosis |

**Result:** v1 → v2 (4 new states, LEARNINGS.jsonl schema, halved turn limits)

### Round 2: Targeted Verification (1-seat)

**Plan:** v2 with v1 fixes applied

| Seat | Model | Time | Key Finding |
|---|---|---|---|
| Architect | deepseek-v4-pro:cloud | 46s | All 5 v1 HIGH fixes confirmed resolved. 9 new findings: LINT_FIX→IMPLEMENTING infinite loop (3-retry limit needed), stagnation logic inversion in pseudocode, HUMAN_REVIEW cycle limit, separate counters per stagnation type |

**Result:** v2 → v2.1 (9 fixes applied)

### Round 3: Architectural Review (3-seat panel)

**Plan:** v3 with philosophy section, parallel dispatch architecture, impasse flow

| Seat | Model | Time | Key Finding |
|---|---|---|---|
| Architect | deepseek-v4-pro:cloud | 45s | Unanimous: split into v3-serial (implementation-ready) and v3.1-parallel (design pass needed) |
| Code Reviewer | kimi-k2.7-code:cloud | 79s | 6 serial fixes: stagnation check ordering, counter reset on progress, off-by-one in repeated_root_cause, regression tracking, gap stagnation, uncertain streak |
| Generalist | glm-5.2:cloud | 22.6s | Agreed with split recommendation |

**Result:** v3 → v3-serial (6 fixes applied, v3.1-parallel deferred)

### Implementation

After plan convergence, the v6 state machine was integrated into `sdlc_state.py`:
- 4 new states added to `SDLCState` enum (LINT_FIX, VERIFYING, FAILED, HUMAN_REVIEW)
- 15 new fields added to `SDLCRun` dataclass
- 14 new helper functions
- `run_iterative_state_machine()` — the new v6 execution loop
- v5 `run_state_machine()` fully preserved for backward compatibility
- Standalone `orchestrator.py` deleted per user correction

**Verification:** 12/12 ad-hoc checks passed.

## Key Learnings

1. **Split recommendation is a strong signal** — when all 3 seats independently recommend the same structural change (split into serial/parallel), act on it immediately. Don't re-review the recommendation.

2. **Targeted verification saves cost** — Round 2 used 1 seat (DeepSeek) instead of 3. For verifying specific fixes, a single targeted review is sufficient and 3× cheaper.

3. **Integrate, don't build standalone** — the user corrected the approach: extend existing skill modules rather than creating standalone scripts. This avoids fragmentation and duplicate imports.

4. **45 iterations changes everything** — at 5 iterations, max-iterations is the primary terminator. At 45, stagnation detection becomes primary and checkpoint/resume becomes critical.

## Pattern Used

Pattern 7 (Iterative Plan Refinement): broad → targeted → features, with split-recommendation synthesis.
