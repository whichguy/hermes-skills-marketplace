# Real Council Run — Kanban Integration Plan Review (2026-06-26)

## Context

User asked: "how do i make better automatic, seamless use of Kanban in hermes while prompting?"

Three rounds of council review on the resulting plan:

## Round 1 — DeepSeek Solo

- **Seat:** DeepSeek V4 Pro (reasoner)
- **Prompt:** Review the initial Kanban integration plan
- **Result:** 6 issues found, priority reordered
- **Time:** ~2 min
- **Outcome:** Plan updated with all 6 fixes

## Round 2 — Full Council (DeepSeek + Kimi)

- **Panel:** DeepSeek V4 Pro (reasoner) + Kimi K2.7 Code (coder)
- **Dispatch:** Individual (separate delegate_task calls)
- **DeepSeek:** 40s, medium confidence — 6 findings
- **Kimi:** 28s, medium confidence — 5 findings
- **Consensus:** DeepSeek V4 Pro — 12 improvements, Phase 3.5/3.6, Phase 4a/4b
- **Total:** ~3m 16s
- **Outcome:** Plan updated with all 12 improvements

## Round 3 — Council with Gateway Failure

- **Panel:** DeepSeek V4 Pro (reasoner) + Kimi K2.7 Code (coder)
- **Dispatch:** Individual
- **Kimi:** 9s, medium-high confidence, conditional yes — 7 issues (2 must-fix)
- **DeepSeek:** DISPATCHED BUT NEVER RETURNED
  - Dispatched at 22:21 UTC
  - Gateway restarted at ~22:24 UTC (user triggered restart)
  - Re-dispatched at 22:24 UTC
  - Still no result by 22:48 UTC (23+ min on 4-min estimate)
  - process(action="list") showed no running delegation processes
  - Declared dead at 5x cutoff
- **Consensus:** Proceeded with Kimi R3 + R2 consensus (both models agreed)
- **Outcome:** 5 fixes applied (kill-switch, gateway pre-flight, git guard, rollback, time expectations)

## Lessons

1. **Gateway restart kills subagents.** Background delegations live in the gateway process. A restart during a council run silently kills all running panel members. No error, no notification — the result just never arrives.

2. **5x cutoff is real.** DeepSeek R3 ran 23+ minutes on a 4-minute estimate. At 5x (20 min), the correct action was to stop polling and proceed with available results. Kimi's review + R2 consensus was sufficient.

3. **2-seat council is viable.** With one seat dead, the remaining seat + prior round consensus produced a useful result. Don't let one failure block the entire synthesis.

4. **Hybrid dispatch would have helped.** If R3 had used batch dispatch for the panel (both seats in one delegate_task call), the gateway restart would have killed both or neither — no partial-result ambiguity. But individual dispatch let Kimi's result survive the restart.

5. **Re-dispatch with context.** When re-dispatching DeepSeek R3, Kimi's findings were passed as context so the re-dispatched member had the full picture. This is the correct recovery pattern.
