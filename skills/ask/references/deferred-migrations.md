# Deferred Migrations

Designs that are approved, fully specified, and waiting for a trigger condition.
Each entry captures the design so it survives session scroll-off.

---

## SDLC File-Based Handoff

- **Status:** DEFERRED
- **Date designed:** 2026-06-28
- **Reviewed by:** 3-seat advisor panel (DeepSeek + Kimi + Qwen), unanimous defer
- **Design doc:** `sdlc-file-lifecycle-2026-06-28.md` (in this directory)

### What Changes

Migrate 3 SDLC phases from embedded content prompts to file-reference prompts:
- **PLAN:** write `.sdlc/PLAN.md` instead of keeping plan in `run.last_plan` only
- **IMPLEMENT:** read `.sdlc/PLAN.md` instead of embedding plan in prompt
- **VERIFYING:** read source files from disk instead of embedding `read_code_state()` output
- **IMPASSE:** add `.sdlc/PLAN.md` + `.sdlc/GAPS.md` to diagnosis context

### Trigger Conditions (implement when ANY fires)

1. A phase prompt exceeds the model's context window
2. Pipeline uses a smaller-context model (sub-16K context, e.g., local 7B)
3. A checkpoint/resume bug is traced to lost in-memory state
4. A new phase needs access to prior artifacts (PLAN.md, GAPS.md)

### Pre-Work Required

`read_learnings_formatted()` must be implemented first — it's the actual blocker.
See item #5 in DeepSeek's improvement proposals (2026-06-28).

### Estimated Effort

~60 lines new code + ~8 lines modifications in sdlc_state.py (revised from
original ~40 estimate after advisor panel review).

### Risk

Low — backwards-compatible. Files are additive. When files are missing,
existing embedded-content behavior is the fallback.

### What NOT to Change

- `dispatch_single()` — dumb pipe, no changes
- `debug_cascade()` — shared with v5, tightly coupled
- v5 state machine — different phase functions

### Resume Consistency Design

`ITERATION_STATE.json` is authoritative for state machine position.
`.sdlc/` files are advisory for content. They can disagree without corruption.
Worst case: planner sees slightly stale gap/learning data (harmless).

### Fallback Design

Lightweight heuristic (diagnostic, not gate):
- `_plan_references_learnings()` checks if plan text contains keywords from learnings
- If 0 matches → emit warning `⚠️ plan may not have consumed learnings`
- Pipeline continues — if plan is bad, tests fail and debug loop catches it