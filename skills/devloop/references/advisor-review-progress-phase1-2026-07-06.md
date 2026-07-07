# Advisor Review: Devloop Progress Output Phase 1 — 2026-07-06

**Panel:** DeepSeek V4 Pro (architectural) · Kimi K2.7 Code (code-level) · Qwen 3.6 35B (local lens)
**Date:** 2026-07-06
**Subject:** Phase 1 planning announcements implementation + Phase 2-5 plan review

## Consensus Findings

### Unanimous (3/3)
- `_progress()` vs `_announce()` separation is correct — keep as-is
- `category` param in `_announce()` is dead code — remove
- Compact mode broken (gates `==0` not `<=1`) — **FIXED**
- Phase 2 completion summaries → emit from `loop.py`
- Phase 5 mid-loop HUMAN_REVIEW also needs announcements

### Majority (2/3)
- Phase 4 learnings → `devloop_bridge.py` (Kimi + Qwen; DeepSeek said loop.py)
- Phase 3 evidence stderr → summary by default, tail in verbose (Kimi + Qwen)

### Single-advisor findings
- DeepSeek: Missing DESIGN phase announcement — add to Phase 2
- Kimi: Add `progress` trace event type for post-run replay
- Kimi: Centralize `_return_human_review()` helper in loop.py
- Qwen: HUMAN_REVIEW blocking questions should bypass compact mode
- Qwen: Consider `minimal` mode (-1) for cron jobs

## Bugs Found and Fixed

| # | Severity | Description | Fix |
|---|----------|-------------|-----|
| 1 | HIGH | `_announce()` gates on `==0` instead of `<=1` — compact mode is a no-op | Changed to `<=1` |
| 2 | LOW | `category` param in `_announce()` is dead code | Removed from signature + 6 call sites |
| 3 | — | No compact-mode test | Added `test_progress_compact_suppresses_announce_keeps_progress` |

## Phase 2-5 Plan Adjustments (from advisor feedback)

1. **Phase 2**: Add DESIGN phase announcement (test count, criterion-to-test mapping, coverage)
2. **Phase 2**: Emit from `loop.py` (not runner.py) — the loop has the in-memory state
3. **Phase 3**: Summary by default; stderr tail only in verbose mode
4. **Phase 4**: Emit from `devloop_bridge.py` (has the rich commit message with learnings)
5. **Phase 5**: Centralize `_return_human_review()` helper in `loop.py` for ALL HUMAN_REVIEW exits
6. **Phase 5**: HUMAN_REVIEW blocking questions should bypass compact mode (critical info)
7. **Future**: Add `progress` trace event type for post-run replay capability
