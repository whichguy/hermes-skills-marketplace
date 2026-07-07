# Session Learnings & Improvement Plan — 2026-07-05

See `/opt/data/wiki/concepts/session-learnings-improvement-plan-2026-07-05.md` for the full plan.

## Summary

7 learnings identified from the devloop learnings journaling work, advisor review, Slack inspection, and gateway stability issues. 8 improvements planned, 3 implemented (P5/P7/P8 in commit `9cb229b`).

### Key Learnings

| # | Learning | Source |
|---|----------|--------|
| L1 | Exercise scripts can validate the wrong code path | Exercise tested bridge journal, not project loop journal |
| L5 | Advisor reviews catch what tests miss | All 3 seats found P0-1 that 438 passing tests missed |
| L6 | Broad keyword matching produces false positives | "judge correctly rejected" captured as failure condition |
| L7 | Two writers writing different shapes to different journals | Bridge vs project loop journal schema mismatch |

### Implemented (P5/P7/P8)

- **P5**: Consolidator timeout fallback now emits `logging.warning`
- **P7**: `ts` field added to bridge journal entries
- **P8**: Template fallback commit message is now design-oriented

### Remaining

- P1: Project-loop integration test (30 min)
- P3: Env-var health check in `hermes status` (30 min)
- P6: Unify the two journal paths (1 hour)
- P2: Fix Kanban CLI inside gateway (1-2 hours)
- P4: Gateway recovery feedback (2-3 hours)
