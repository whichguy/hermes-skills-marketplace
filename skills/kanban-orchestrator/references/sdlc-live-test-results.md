# SDLC Live Chain Test Results — 2026-06-27

First end-to-end run of the 5-phase SDLC chain (`kanban-sdlc.sh`) on a real project
(adding `divide()` to a Calculator class with 9 existing tests).

## Chain Summary

| Phase | Task ID | Profile | Model | Status | Duration | Key Output |
|---|---|---|---|---|---|---|
| T1 Research | `t_f5272a74` | worker | Qwen | ✅ done | ~4 min | `RESEARCH.md` with 5 options, recommendation, verdict |
| T2 Tests | `t_17fa97fb` | worker | Qwen | ✅ done | ~4 min | `TEST_PLAN.md` + `test_divide.py` (5 tests) |
| T3 Implement | `t_25e6f7ed` | worker | Qwen | ✅ done | ~6 min | `CHANGES.md` + `divide()` in calculator.py |
| T4 Review | `t_2de00b9e` | reviewer | DeepSeek | ✅ done | ⚠️ manual | `REVIEW.md` — APPROVED (after crash recovery) |
| T5 Final test | `t_9ad1e946` | worker | Qwen | ✅ done | ~2 min | `TEST_RESULTS.md` — 14/14 pass |

## What Worked

1. **File-based handoff contracts** — All 5 files created (RESEARCH.md → TEST_PLAN.md → CHANGES.md → REVIEW.md → TEST_RESULTS.md)
2. **Parent-child dependencies** — T2 waited for T1, T3 waited for T2, etc. No premature dispatch.
3. **`dir:` workspace sharing** — Each phase could read prior phases' files
4. **notify-subscribe per task** — Subscriptions registered before dispatcher tick
5. **Pre-flight skill check** — Correctly warned about missing skills (after COLUMNS fix)
6. **`spike` skill for T1** — Worker produced structured research with verdict (not a plan file)
7. **TDD for T2** — Worker wrote tests first, then T3 implemented to pass them
8. **14/14 tests pass** — No regressions, all new tests pass
9. **`--skill` multi-load verified** — T3 loaded both `test-driven-development` and `systematic-debugging` correctly

## Script Bugs Found and Fixed

| Bug | Fix | Status |
|---|---|---|
| JSON key `task_id` → actually `id` | Fixed all 5 instances in `kanban-sdlc.sh` | ✅ |
| `hermes skill list` → actually `hermes skills list` | Fixed pre-flight check | ✅ |
| Skill names truncated in table → grep misses | Fixed with `COLUMNS=200` | ✅ |

## Issues Found and Fixed

### 1. DeepSeek Reviewer Crashes on Missing pytest (HIGH) — ✅ FIXED R5

**Symptom:** T4 (reviewer, DeepSeek model) crashed 5 consecutive times, auto-blocked.
**Root cause:** DeepSeek model keeps trying `python3 -m pytest` despite pytest not being installed and explicit instructions to use unittest.
**Fix applied:** T4 and T5 task bodies now explicitly forbid pytest in ALL CAPS. Added `hermes kanban reassign --reclaim` as a recovery path.

### 2. tests/ Directory Deleted During T3 (MEDIUM) — ✅ FIXED R5

**Symptom:** After T3 completed, the `tests/` directory was gone. T4 couldn't find test files.
**Root cause:** T3 worker cleaned up its workspace and removed files it didn't create.
**Fix applied:** T3 task body now includes "DO NOT delete any existing files in the project directory."

### 3. T4 Required Manual Intervention (MEDIUM) — ✅ MITIGATED R5

**Symptom:** 5 consecutive crashes → auto-blocked → manual unblock + complete.
**Root cause:** Same as #1 — DeepSeek + pytest bias.
**Mitigation:** Same as #1. Also added `hermes kanban reassign --reclaim` for mid-run profile switching.

## R5 Council Review (2026-06-27)

DeepSeek + Kimi reviewed the plan and script against latest Hermes docs. 8 new findings, 6 applied:

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Status name: `in_progress` → `running` | CRITICAL | ✅ Verified via CLI, plan updated |
| 2 | No multi-board support | HIGH | ✅ `--board` support added to script |
| 3 | No `--idempotency-key` (duplicates on rerun) | HIGH | ✅ T1 now has idempotency key |
| 4 | File attachments vs `dir:` undocumented | MEDIUM | ✅ Rationale documented |
| 5 | Phase 5b cron design wrong | MEDIUM | ✅ Rewritten in plan |
| 6 | Deprecated daemon warning missing | MEDIUM | ✅ Added to script header |
| 7 | Profile description CLI not mentioned | LOW | ✅ Documented |
| 8 | Docker/s6 supervision not mentioned | LOW | ✅ Noted in plan |

## Verification

Final state: 14/14 tests pass, all 5 handoff files present, all 5 tasks `done` on board.
R5 script: 18/18 verification checks pass (idempotency, boards, pytest forbidden, daemon warning, T3 no-delete, reassign mention, plan fixes).
