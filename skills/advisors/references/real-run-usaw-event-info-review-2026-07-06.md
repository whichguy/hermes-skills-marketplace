# Real Run: USAW Event Info Skill Review — 2026-07-06

## Context

Jim had just built the `usaw-event-info` skill (USAW weightlifting event
information extraction, wiki integration, cron sync). Following the same
pattern as the 2026-07-05 devloop learnings review, he asked for an advisor
panel to review the skill before writing the improvement plan.

## Pattern Used

**Pattern 1 (Advisors) + Pattern 8 (Advisors as Fixers)**

Full cycle: dispatch → synthesis → improvement plan → batch fixes → verification.

## Dispatch

- **Panel:** 3-seat (DeepSeek V4 Pro / Reasoner, Kimi K2.7 Code / Coder, Qwen 3.6 35B / Local Lens)
- **Synthesis:** GLM-5.2:cloud
- **Method:** `dispatch_advisors.py` with file-referenced pattern (brief on disk, seats read via `-t file`)
- **Context:** SKILL.md (8K chars), extractor script, sync script, mock test suite, wiki schema, wiki index
- **Question:** "Review this skill for bugs, gaps, and improvement opportunities"

## Results

- **3/3 seats completed** (77.8s, 72.3s, 68.1s)
- **GLM synthesis:** 28 findings across P0/P1/P2 priority levels
- **Output:** `/tmp/advisors-usaw-review/15ad335e/synthesis.md` (10.8K chars)

### Finding Distribution

| Priority | Count | Examples |
|----------|-------|----------|
| P0 | 2 | L1: `simplify_event()` links key bug, L2: stale HTML fixtures |
| P1 | 14 | L3-L16: alias conflicts, mock test gaps, fee regex, error recovery, time discrepancy |
| P2 | 12 | Wiki dedup, page-health monitoring, date/venue fallback, results parser tests |

## Improvement Plan

Written to `wiki/concepts/session-learnings-improvement-plan-2026-07-06-usaw.md`
following the same structured format as the 2026-07-05 plan (priority, effort,
status, description columns).

## Batch Fix Application

Jim said "Batch all S-effort fixes" — all 7 S-effort items (2×P0, 5×P1) applied
in a single pass:

| Fix | Description | Files |
|-----|-------------|-------|
| L1 (P0) | `simplify_event()` accessed nonexistent `links` key | `usaw_event_info_sync.py` |
| L3 (P1) | "medal schedule" alias conflicted with `medal_schedule` type | `usaw_event_extractor.py` |
| L4 (P1) | Sync ran 11 live fetches daily → switched to mock tests | `usaw_event_info_sync.py` |
| L5 (P1) | `update_meet_ids_reference()` was a permanent stub | `usaw_event_info_sync.py` |
| L7 (P1) | Fee regex fragile + values untested | `usaw_event_extractor.py`, `test_extractor_mock.py` |
| L13 (P1) | Failed extraction → spurious diff on next run | `usaw_event_info_sync.py` |
| L14 (P1) | Registration time discrepancy across docs | `SKILL.md`, wiki schema |

## Verification

- Mock tests: 11/11 passing (offline, <1s)
- Sync dry-run: clean (mock tests, no network, no errors)
- Committed `c5d0235` to marketplace, pushed

## Key Takeaways

1. **Advisor panels catch bugs tests miss.** The `links` key bug (L1) had been
   silently broken since Jun 24 — 11 mock tests passed but the sync script's
   link-level diff was dead code. Only a human-style code review caught it.

2. **File-referenced dispatch works at scale.** 8K chars of skill content +
   scripts stayed on disk; controller context only carried the question and
   file paths. Synthesis output (~2K chars) was the only payload that entered
   context.

3. **Batch by effort level.** Jim's "batch all S-effort" instruction is a
   recurring pattern — group fixes by effort (S/M/L) and apply all same-effort
   items in one pass. This minimizes context-switching and verification overhead.

4. **Mock tests as verification gate.** Switching sync's test suite from live
   (11 network fetches) to mock (<1s offline) made verification fast enough to
   run after every fix without slowing the batch.

5. **Improvement plan format is stable.** The same structured table format
   (Priority | Effort | Status | Description) used on 2026-07-05 worked
   equally well here. This format should be the default for all post-review
   improvement plans.
