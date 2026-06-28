# Real Run: Iterative Plan Refinement with Advisors (2026-06-28)

## Context

Designing an orchestrator state machine for iterative TDD development. The plan
went through 3 rounds of advisor review, each narrowing scope:

| Round | Plan Version | Panel | Focus | Outcome |
|---|---|---|---|---|
| 1 | v1 → v2 | DeepSeek + Kimi + GLM (3 seats) | Full design review | 5 HIGH issues, 10 MEDIUM → v2 |
| 2 | v2 → v2.1 | DeepSeek only (1 seat) | Targeted: did v1 fixes hold? | 9 pseudocode bugs → v2.1 |
| 3 | v2.1 → v3 | DeepSeek + Kimi + GLM (3 seats) | v3 additions (philosophy, parallel, impasse) | Unanimous: split serial/parallel |

## Pattern: Iterative Plan Refinement

This is a composition of Pattern 1 (Advisors) applied iteratively:

```
write plan v1
  → dispatch 3-seat panel (broad review)
  → read reviews, patch plan → v2
  → dispatch 1-seat targeted review (did fixes hold?)
  → read review, patch plan → v2.1
  → add new features → v3
  → dispatch 3-seat panel (review new features)
  → read reviews → converge on recommendation
```

### When to use this pattern

- Design documents that evolve through feedback
- Multi-version plans where each version needs independent review
- When v1 has known issues and v2 needs verification before adding features

### When NOT to use

- Single-version reviews (use Pattern 1)
- Quick yes/no questions (use Pattern 4)
- When the plan is stable after round 1 (stop — don't over-review)

### Key insight: narrow the panel between rounds

Round 1 uses the full 3-seat panel for broad coverage. Round 2 uses a single
targeted reviewer (DeepSeek) to verify specific fixes — cheaper and faster than
re-running the full panel. Round 3 goes back to the full panel for new features.

This "full → targeted → full" rhythm balances thoroughness with cost.

## Split-Recommendation Synthesis

All 3 advisors independently recommended the same structural change: split the
plan into v3-serial (ship now) and v3.1-parallel (design pass needed). When
all seats converge on the same recommendation unprompted, it's a strong signal.

### Synthesis decision tree for split recommendations

| Signal | Action |
|---|---|
| All seats recommend same split | Apply the split immediately |
| 2/3 recommend split, 1/3 disagrees | Read the dissenter's reasoning; if it's weak, apply split |
| 1/3 recommends split | Note it but don't act — not enough consensus |
| Split recommended but details differ | Take the most detailed recommendation as the template |

## Round 1: v1 → v2 (3 seats, broad review)

**Panel:** DeepSeek (Architect), Kimi (Code Reviewer), GLM (Generalist)
**Prompt:** "Review the orchestrator state machine design for an iterative TDD development loop"
**Context:** Full v1 plan as context file

**Results:**
- DeepSeek: 81.5s, 13KB — 5 HIGH, 10 MEDIUM issues
- Kimi: 78.7s, 8KB — code-level issues, pseudocode bugs
- GLM: 167.2s, 17KB — most detailed, 15-item gap table

**Key findings applied to v2:**
- +INIT state (validate PROJECT.md, create worktree)
- +LINT_FIX state (script-only, no model)
- +FAILED state (explicit terminal)
- +HUMAN_REVIEW state (user clarification gate)
- LEARNINGS.jsonl over git commit messages
- Halved turn limits (PLANNING 10→5, IMPLEMENTING 15→8)

## Round 2: v2 → v2.1 (1 seat, targeted)

**Panel:** DeepSeek only
**Prompt:** "Review v2 against v1 — did the 5 HIGH fixes actually hold? Any new issues?"
**Context:** v2 plan as context file

**Results:** 46s, 9.4KB — all 5 HIGH fixes confirmed resolved, 9 new pseudocode bugs found

**Key findings applied to v2.1:**
- LINT_FIX infinite loop (3-retry escape hatch)
- Stagnation logic inversion (check AFTER testing, not before)
- HUMAN_REVIEW cycle limit (3 max)
- Regression tracking in stagnation
- Counter resets on progress
- Separate counters (test_stagnation, root_cause_stagnation, gap_stagnation)

## Round 3: v2.1 → v3 (3 seats, new features review)

**Panel:** DeepSeek (Architect), Kimi (Code Reviewer), GLM (Generalist)
**Prompt:** "Review v3 additions: pragmatic momentum philosophy, parallel dispatch, impasse→user clarification"
**Context:** v3 plan as context file

**Results:**
- DeepSeek: 45s, 13.7KB — 8 CONFIRMED, 7 NEW ISSUE (1 HIGH, 4 MEDIUM, 2 LOW), 4 REMAINING
- Kimi: 79s, 8.0KB — 5 CONFIRMED, 8 NEW ISSUE (1 CRITICAL, 5 HIGH, 2 MEDIUM), 3 REMAINING
- GLM: 167s, 17.2KB — most detailed, 15-item gap table

**Unanimous recommendation:** Split into v3-serial (ship now, 6 fixes) and v3.1-parallel (design pass needed, 5 HIGH gaps)

**Critical gaps identified (all 3 flagged):**
1. No partial-file rollback for failed parallel tasks (CRITICAL)
2. PLANNING output format undefined for parallel decomposition (HIGH)
3. No checkpoint/resume layer — counters reset on restart (HIGH)
4. Stagnation check in DEBUGGING wastes the fix (HIGH)
5. Disjoint file scope insufficient for true independence (HIGH)

## Cost Summary

| Round | Seats | Wall Time | Cloud Cost | Value |
|---|---|---|---|---|
| 1 (broad) | 3 | ~167s | 3× | Found 5 HIGH + 10 MEDIUM issues |
| 2 (targeted) | 1 | ~46s | 1× | Verified fixes, found 9 bugs |
| 3 (features) | 3 | ~167s | 3× | Unanimous split recommendation |
| **Total** | **7 calls** | **~380s** | **7×** | **Plan went from v1 (7 states, undefined stagnation) to v3-serial (implementation-ready)** |

## Lessons

1. **Targeted round between full rounds saves cost.** Round 2 (1 seat, 46s) verified v1 fixes cheaper than re-running 3 seats.
2. **GLM is consistently the most detailed reviewer** (167s both rounds, 15-17KB output) but also the slowest.
3. **When all seats converge on a structural recommendation, act on it immediately.** Don't re-review the recommendation.
4. **The "full → targeted → full" rhythm works for multi-version design review.** Broad coverage → verify fixes → review new features.
