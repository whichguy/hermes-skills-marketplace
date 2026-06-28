# Real Run: PostgreSQL vs MongoDB — Advisors v3 (2026-06-27)

## Setup

- **Question:** "Should we use PostgreSQL or MongoDB for a financial approval engine? ACID required, ~100K rows, multi-step approval workflows."
- **Toolsets:** file, web
- **Max turns:** 3 per seat
- **Synthesizer:** deepseek-v4-pro:cloud

## Panel

| Seat | Model | Role |
|---|---|---|
| 1 | deepseek-v4-pro:cloud | Reasoner |
| 2 | kimi-k2.7-code:cloud | Coder |
| 3 | glm-5.2:cloud | Generalist |

## Results

| Seat | Model | Time | Position |
|---|---|---|---|
| Reasoner | deepseek-v4-pro:cloud | 25.2s | PostgreSQL |
| Coder | kimi-k2.7-code:cloud | 8.8s | PostgreSQL |
| Generalist | glm-5.2:cloud | 10.2s | PostgreSQL |
| **Synthesis** | deepseek-v4-pro:cloud | 15.2s | PostgreSQL (unanimous) |

**Total wall time:** 40.3s (parallel dispatch, synthesis sequential)

## Key Observations

1. **Unanimous consensus** — all three models independently chose PostgreSQL with no dissent
2. **DeepSeek was slowest** (25.2s) but produced the most detailed reasoning
3. **Kimi was fastest** (8.8s) with code-focused arguments
4. **GLM produced English output** — the `--english-only` auto-append worked correctly
5. **Synthesis was high quality** — structured table of agreements, no false balance

## Synthesis Excerpt

> **Unanimous — PostgreSQL. Three advisors, zero dissent.**
>
> All three advisors converge on the same core arguments:
> - ACID is native, not bolted-on
> - Relational model maps to approval workflows naturally
> - PostgreSQL's `WITH RECURSIVE` handles multi-step approval chains
> - Audit trails are simpler with row-level triggers

## Files Written

```
/tmp/advisors-test/seat-1-reasoner.md    (DeepSeek output)
/tmp/advisors-test/seat-2-coder.md       (Kimi output)
/tmp/advisors-test/seat-3-generalist.md  (GLM output)
/tmp/advisors-test/synthesis.md          (Synthesizer output)
```
