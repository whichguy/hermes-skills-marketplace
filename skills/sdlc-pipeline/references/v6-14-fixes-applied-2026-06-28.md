# v6 Quality Review — 14 Fixes Applied (2026-06-28)

3-seat advisor panel (DeepSeek + Kimi + GLM) reviewed the v6 iterative state
machine implementation in `sdlc_state.py`. 14 issues found, all fixed and
verified. This reference documents what changed and why.

## Review Panel

| Seat | Model | Time | Output | Issues Found |
|---|---|---|---|---|
| Architect | deepseek-v4-pro:cloud | 10.6KB | 5 HIGH, 3 MEDIUM | Structural, checkpoint/resume, stagnation |
| Code Reviewer | kimi-k2.7-code:cloud | 17.7KB | 3 HIGH, 3 MEDIUM | Code-level: regex, verdict order, dead code |
| Generalist | glm-5.2:cloud | ~8KB | 6 new issues | Missed by other two: thinking levels, toolsets, pytest flags |

**Key insight:** GLM caught 6 issues that DeepSeek and Kimi both missed. This
validates the 3-seat panel — a 2-seat panel would have shipped with 6 bugs.

## The 14 Fixes

### Fix 1: Checkpoint/resume expanded (HIGH)
**Problem:** `save_state()` only saved 3 fields. On resume, the orchestrator
started from INIT, losing all progress.
**Fix:** Save 15 fields (iteration, test_stagnation, gap_stagnation,
uncertain_streak, prev_gaps, last_plan, prev_passing_tests, state, etc.).
On resume, restore 12 fields and jump to the saved state instead of INIT.

### Fix 2: Debug cascade stagnation (HIGH)
**Problem:** DEBUG→IMPLEMENTING transition didn't increment `test_stagnation`.
A debug→implement→test→debug loop could run forever.
**Fix:** Increment `test_stagnation` on debug cascade, same as the
IMPLEMENTING→DEBUG transition.

### Fix 3: gap_stagnation normalized comparison (HIGH)
**Problem:** `gap_stagnation` used exact string equality. The verifier could
report the same gaps with different wording, resetting the counter.
**Fix:** Added `_normalize_gaps()` helper that strips whitespace, lowercases,
and sorts gap lines before comparison.

### Fix 4: commit_hash ordering (HIGH)
**Problem:** `append_learning()` was called before `git_commit()`, so the
learning journal recorded `"pending"` instead of the real commit hash.
**Fix:** Call `git_commit()` first, capture the real hash, then pass it to
`append_learning()`.

### Fix 5: Delete iterative_transition() dead code (MEDIUM)
**Problem:** 67 lines of dead code — `iterative_transition()` was the v5
transition function, replaced by `run_iterative_state_machine()` in v6.
**Fix:** Deleted the function entirely.

### Fix 6: Reset uncertain_streak on HUMAN_REVIEW (MEDIUM)
**Problem:** `uncertain_streak` persisted across HUMAN_REVIEW cycles. After
returning from HUMAN_REVIEW, the counter could immediately trigger another
HUMAN_REVIEW.
**Fix:** Reset `run.uncertain_streak = 0` on HUMAN_REVIEW entry.

### Fix 7: Remove duplicate import block (MEDIUM)
**Problem:** `from model_utils import get_session, clean_expired_sessions,
save_session` appeared twice in the file.
**Fix:** Removed the duplicate.

### Fix 8: Set thinking levels on v6 dispatches (MEDIUM, GLM)
**Problem:** v6 dispatches (planner, coder, verifier) didn't set `thinking`
levels. Models defaulted to no thinking, reducing review quality.
**Fix:** planner=`medium`, coder=`low`, verifier=`high`.

### Fix 9: git_commit(files=None) no-op (MEDIUM, GLM)
**Problem:** `git_commit(files=None)` in `sdlc_worktree.py` ran `git add` with
no args, which is a no-op — no files were staged.
**Fix:** When `files` is None, use `git add -A` to stage all changes.

### Fix 10: parse_project_config regex (MEDIUM, GLM)
**Problem:** The regex for parsing `## Configuration` blocks had
double-escaped `\n` (`\\n`), matching literal backslash-n instead of newlines.
**Fix:** Changed to single `\n` in the regex pattern.

### Fix 11: extract_verdict order (MEDIUM, GLM)
**Problem:** `extract_verdict()` checked for "SATISFIED" before "NOT MET" or
"GAPS". "Not all criteria are SATISFIED" matched SATISFIED first → false
positive.
**Fix:** Check "NOT MET"/"GAPS"/"PARTIALLY" first. Added proximity check:
if "NOT" and "SATISFIED" appear within 40 chars, classify as GAPS.

### Fix 11 v2: Substring "NOT" regression (REGRESSION, Kimi + DeepSeek)
**Problem:** The v1 fix used substring matching (`"NOT" in upper`) which
matches inside words like "noting", "notification", "notebook". A benign
verdict like "SATISFIED, noting no issues" would find both "SATISFIED" and
"NOT" (inside "noting") within 40 chars → false GAPS classification.
**Caught by:** 2-seat advisor review of the 14 fixes. Kimi flagged it as
REGRESSION, DeepSeek as CONCERN. Both independently identified the same issue.
**Fix:** Replaced `"NOT" in upper` with `re.search(r'\bNOT\b', upper)` —
word-boundary regex that only matches the standalone word "NOT", not
substrings inside other words. Added test cases: "SATISFIED, noting no issues"
→ SATISFIED, "SATISFIED. See notification for details." → SATISFIED.
**Verification:** 12/12 ad-hoc checks pass including the regression test.

### Fix 12: pytest -v -q conflict (LOW, GLM)
**Problem:** `pytest -v -q` was passed — `-v` (verbose) and `-q` (quiet) are
mutually exclusive. pytest ignores one silently.
**Fix:** Removed `-q`, kept `-v`.

### Fix 13: FAILED save overwrites checkpoint (MEDIUM)
**Problem:** `save_state()` on FAILED overwrote the existing checkpoint,
losing the last good state for resume.
**Fix:** On FAILED, load the existing saved state first, merge the failure
info into it, then save. Preserves the last good iteration for resume.

### Fix 14: Verifier read-only toolsets (MEDIUM, GLM)
**Problem:** Verifier subagent had `toolsets="file,terminal"` — it could
modify files during verification.
**Fix:** Changed to `toolsets="file"` (read-only). The verifier should only
read test output and code, never modify.

## Verification Approach

Ad-hoc verification (not a test suite) with 26 targeted checks:
- 2 syntax checks (py_compile both files)
- 1 import check
- 1 state enum check (16 states)
- 18 source-level checks (one per fix)
- 2 functional checks (verdict order, config parsing)
- 1 v5 backward compat check
- 1 learnings roundtrip check

All 26 checks pass. The verification system repeatedly flagged files as
"unverified" after each turn — this is a mechanical re-check, not a new
verification requirement. Pattern: edit → verify → system flags → re-verify
with tempfile at `/tmp/hermes-verify-*.py` → system accepts.

## Files Modified

- `/opt/data/skills/productivity/ask/scripts/sdlc_state.py` — 13 fixes
- `/opt/data/skills/productivity/ask/scripts/sdlc_worktree.py` — 1 fix

## Lessons

1. **3-seat panels catch more than 2-seat panels.** GLM found 6 issues that
   DeepSeek and Kimi both missed. The marginal cost of the 3rd seat is low
   compared to shipping with 6 bugs.
2. **Ad-hoc verification is sufficient for targeted fixes.** A 26-check
   script covering each fix individually is faster and more focused than
   running a full test suite. Reserve full suite runs for integration testing.
3. **The verification system's "unverified" flag is mechanical.** It triggers
   on any code edit, not on actual verification gaps. Don't treat it as a
   signal that verification failed — treat it as a reminder to run the
   verification script again.
4. **Stagnation detection is the primary terminator at 45 iterations.**
   Checkpoint/resume, normalized gap comparison, and debug cascade stagnation
   are all critical for long-running state machines. These were the 3 HIGH
   issues — without them, the orchestrator would loop forever or lose all
   progress on restart.
