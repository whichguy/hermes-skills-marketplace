# DeepSeek Plan Review: v3.4 Fix Plan (2026-07-05)

## Context

After the v3.4 self-review found 10 bugs and they were fixed, the user suspected
the 5K threshold was arbitrary. Kimi confirmed it was too low and too arbitrary.
The controller wrote a fix plan and dispatched DeepSeek to review it architecturally.

## Dispatch

- **Brief:** 5.2K chars at `/tmp/advisors-plan-review/brief.md`
- **Seat:** DeepSeek V4 Pro (202.6s, 11.2K chars)
- **Controller context impact:** Only the 11.2K review entered context

## Key Findings

### 5K Threshold — Wrong Justification

The original pitfall cited ARG_MAX as a constraint. DeepSeek pointed out:
> ARG_MAX is 2MB, and `dispatch_advisors.py` never passes context via
> command-line args — it writes to disk or uses stdin. ARG_MAX is irrelevant.

The real constraint is **cumulative transcript pollution**: every byte of inline
context is re-sent on every subsequent turn. 2K chars of inline context costs
~40K chars over a 20-turn session. The same data via file-reference costs ~2.8K.

**Fix:** Replace ARG_MAX rationale with cumulative transcript cost. Add a
decision table (not code) as supporting rationale.

### 6 Bugs Kimi Missed

| # | Bug | Severity |
|---|---|---|
| 1 | `synthesize()` has same double-timeout bug (line 260) | MEDIUM |
| 2 | `synthesize()` output not checked for 0-byte | LOW |
| 3 | `prepare_brief` doesn't handle unreadable files (PermissionError) | LOW |
| 4 | No overall timeout on ThreadPoolExecutor | LOW |
| 5 | `parse_seats` pipe-split edge case (spaces around pipe) | TRIVIAL |
| 6 | `clear_stale` race condition if two instances share outdir | LOW |

### Architectural Insight: Run-Specific Subdirectories

> Use run-specific subdirectories (`/tmp/advisors/<uuid>/`) instead of cleanup
> logic. Eliminates staleness entirely without race conditions or the "first
> dispatch" ambiguity. This is the cleaner fix for both Bug G and H.

### Fix Plan Corrections

| Fix | DeepSeek Verdict | Correction |
|---|---|---|
| Fix 2 (5K threshold) | ⚠️ Wrong justification | Fix ARG_MAX → cumulative transcript cost |
| Fix 3 (allowlist removal) | ✅ Correct | Explicitly delete colon-parsing branch, not just allowlist |
| Fix 5 (stale outdir) | ⚠️ Two gaps | Add `.err` glob, clarify "first dispatch" semantics |
| Fix 6 (double timeout) | ⚠️ Incomplete | Also fix line 260 in `synthesize()` |
| Fix 7 (.err files) | ✅ Correct | Add `errfile` field to seats.json manifest |

## Lessons

### 2-seat panels catch bugs 1-seat panels miss

Kimi reviewed the fix plan first and found the 5K threshold issue. DeepSeek
then reviewed the same plan and found 6 additional bugs Kimi missed. A 1-seat
panel would have shipped with 6 bugs. Different training lineages catch
different things — the overlap is where bugs hide.

### Decision tables > single magic numbers

Both advisors agreed: a decision table with rationale is better than a single
5K threshold. The table supports the rule of thumb without replacing it. The
controller needs the simple heuristic; the table is supporting rationale in
SKILL.md.

### ARG_MAX is a red herring for file-referenced dispatch

The `dispatch_advisors.py` helper writes briefs to disk and never passes large
context via command-line arguments. `prompt_model.py`'s `--context-file` flag
also avoids ARG_MAX. The real constraint is cumulative transcript cost — every
byte of inline context is re-sent on every subsequent turn.
