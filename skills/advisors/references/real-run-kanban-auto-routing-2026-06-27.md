# Council Real Run: Kanban Auto-Routing Plan Review

**Date:** 2026-06-27
**Question:** Review the Kanban Auto-Routing test plan — does the SOUL.md approach work, are there gaps, and what should change?
**Panel:** 3 models (DeepSeek V4 Pro, Kimi K2.7, GLM 5.2) + consensus synthesis
**Total time:** ~4m (dispatch to consensus, excluding stuck Coder seat)

## Panel

| # | Seat | Model | Time | Confidence | Verdict |
|---|---|---|---|---|---|
| 1 | Reasoner | deepseek-v4-pro:cloud | 26.4s | Medium | APPROVE WITH CHANGES |
| 2 | Coder | kimi-k2.7-code:cloud | ~4m | — | STUCK (MCP filesystem errors) |
| 3 | Generalist | glm-5.2:cloud | 29.0s | Medium | APPROVE WITH CHANGES |
| Synthesis | deepseek-v4-pro:cloud | ~4m | — | — |

## Key Findings (2/3 completed)

Both Reasoner and Generalist independently identified:

1. **SOUL.md approach is sound** — injecting routing rules into the stable prompt tier is the right architecture
2. **Test plan needs explicit exclusion rules** — "Build X" alone should NOT route; needs multi-phase language
3. **Wrong-file pitfall** — must verify `$HERMES_HOME/SOUL.md` not `.hermes/SOUL.md`
4. **One-shot vs gateway session distinction** — `hermes chat -q` can't create full task graphs
5. **15 specific revisions (R1-R15)** — all incorporated into final plan

## Coder Seat Failure

The Coder (Kimi) hit MCP filesystem access errors trying to search `/opt/hermes` (outside allowed directories). After 3 consecutive MCP failures, the MCP server went unreachable. The subagent never returned a result.

**Lesson:** Subagents with `toolsets=["file"]` that try to access paths outside MCP-allowed directories can get stuck in error loops. The 5x cutoff rule should be applied — after 5x the estimate, proceed with completed seats.

## Polling Architecture Bug Discovered

During this council run, a critical bug in the delegate-progress-protocol was discovered: the skill instructed "start a background `sleep 120` timer" on every poll cycle without killing the previous one. This caused **55 stale timers** to stack up and fire simultaneously, producing a flood of `[IMPORTANT: Background process ... completed]` notifications.

**Fix applied:** Both `delegate-progress-protocol` and `council` skills patched to use a single tracked timer with kill-before-spawn semantics. SOUL.md delegation section also updated.

## Consensus

**APPROVE WITH CHANGES** — 15 revisions (R1-R15) applied to plan. Plan updated to 428 lines with all council feedback incorporated. Key changes: explicit exclusion rules, wrong-file pitfall, one-shot limitation, Bitwarden JSON pipe handling, ID capture step, link step.

## Lessons

- 2/3 seats is viable for consensus when the third is stuck — don't wait indefinitely
- MCP filesystem access errors can silently kill subagents
- The timer-stacking bug was latent in the skill text for weeks — only surfaced under extended polling
- Council + plan review is a powerful pattern: independent model review catches issues the plan author misses
