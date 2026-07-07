# Devloop Learnings — Advisors SKILL.md Refactor Attempt

**Date:** 2026-07-06  
**Run:** build-37YOUR_PHONE_NUMBERYOUR_PHONE_NUMBER04  
**Terminal:** HUMAN_REVIEW (test fault)  
**Duration:** ~26 minutes  
**Result:** No files changed — devloop never reached implementation phase

## Summary

Devloop was dispatched to refactor the advisors SKILL.md from 85KB → ~8-12KB by extracting patterns, pitfalls, and quick-reference content into on-demand reference files. The run failed at the judge gate — 5 of 8 criteria had no judge-trusted test, triggering a test fault that re-IMPLEMENT cannot fix.

## What Happened (Phase by Phase)

| Phase | Status | Detail |
|---|---|---|
| Charter | ✅ | 8 criteria decomposed, no blocking questions |
| Ambiguity Gate | ✅ | Confidence above floor |
| Design | ✅ | 8 tests generated for 8 criteria |
| Coverage | ✅ | All 8 covered |
| Quality Lint | ✅ | No bad patterns detected |
| Judge (round 1) | ❌ | 2/8 trusted (c2, c6) |
| Redesign | Triggered | c1, c3, c4, c5, c6, c7 sent back |
| Judge (round 2) | ❌ | 3/8 trusted (c2, c6, c8) — c6 fixed but c1/c3/c4/c5/c7 still rejected |
| Terminal | HUMAN_REVIEW | Test fault — re-IMPLEMENT can't fix untrusted tests |

## Judge Verdicts (Final)

| Criterion | Judge A | Judge B | Trusted? | Issue |
|---|---|---|---|---|
| c1 (SKILL.md 8-12KB) | ❌ NO | ❌ NO | No | Size-range test doesn't clearly encode "lightweight" intent |
| c2 (9 patterns extracted) | ✅ | ✅ | Yes | Regex count check is clear |
| c3 (all pitfalls preserved) | ❌ NO | ❌ NO | No | Test depends on `SKILL.md.orig` — doesn't exist |
| c4 (Quick Reference moved) | ❌ NO | ✅ | No | Split vote; Judge A rejected |
| c5 (no info lost) | ❌ NO | ✅ | No | Split vote; content-comparison too complex to judge |
| c6 (context sections retained) | ✅ | ✅ | Yes | Substring checks for known markers |
| c7 (indices point to refs) | ❌ NO | ❌ NO | No | Expects 9 `#pattern-N` links — too specific |
| c8 (test suite passes) | ✅ | ✅ | Yes | Integration test running real suite |

## Root Causes

### 1. Tests depend on `SKILL.md.orig` — a file that doesn't exist

Three criteria (c3, c4, c5) reference `advisors/SKILL.md.orig` as a backup of the original SKILL.md. The designer assumed the implementation would create this backup, but:
- Devloop's frozen-tests gate prevents the coder from creating test-supporting files
- The backup file was never part of the constraint specification
- Even if the coder created it, the test would fail because the backup isn't in the repo

**Lesson:** Tests must not depend on files that don't exist in the repo. The designer should have used `git show HEAD:skills/autonomous-ai-agents/advisors/SKILL.md` or read the original from the git history instead.

### 2. Content-preservation criteria are hard to judge

"Every non-empty body line from the original SKILL.md appears verbatim across the new files" is a content-comparison test. Judges see a Python one-liner that reads files and does string matching, and they say "NO" because:
- The test logic is complex (read 5 files, split lines, filter, check membership)
- Judges can't verify the test actually encodes the intent without running it
- The criterion is structural, not behavioral — judges are trained for behavioral

**Lesson:** Content-preservation and structural-file criteria don't fit devloop's test-first judge model. These are better verified by:
- Running a diff between old and new (controller does this)
- Checking file sizes and section counts (simple assertions)
- Manual review of the new structure

### 3. Devloop never reached implementation

The entire 26-minute run was charter → design → judge → redesign → judge → fail. No code was written, no files were refactored. The SKILL.md is still 85,345 bytes.

**Lesson:** When the judge rejects tests for >50% of criteria after redesign, the task likely doesn't fit devloop's model. The redesign attempt improved c6 (trusted in round 2) but couldn't fix the fundamental issue that content-restructuring criteria are hard to test.

### 4. Worktree boundary breach

Devloop's coder agent touched `test_dispatch_advisors.py` (which we explicitly said not to modify). The boundary guard restored it, but this shows:
- The coder didn't respect the constraint even when explicitly stated
- Complex constraints ("don't touch these specific files") are hard for agent prompts to enforce
- The boundary guard is a safety net, not a replacement for prompt compliance

**Lesson:** For "don't touch X" constraints, rely on the boundary guard (it works) but don't expect the coder to honor them from the prompt alone.

## When Devloop Works vs Doesn't

| Task Type | Devloop? | Why |
|---|---|---|
| Build a new Python module with functions | ✅ | Behavioral criteria, clear test assertions |
| Fix a bug in existing code | ✅ | Reproduce → fix → verify cycle |
| Refactor code (extract function, rename) | ✅ | Input/output behavior preserved, tests verify |
| **Markdown content restructuring** | ❌ | Content preservation isn't behavioral; judges can't evaluate |
| **File splitting (move sections between files)** | ❌ | Structural criteria, not behavioral |
| **Documentation reorganization** | ❌ | "Every word preserved" is a content-comparison test |
| **Config file restructuring** | ⚠️ | Works if criteria are behavioral (parse → check value), fails for structural |

## Recommendation

For this task (advisors SKILL.md refactoring), use one of:
1. **Direct execution** — controller reads the original, writes reference files, trims SKILL.md, runs existing test suite to verify
2. **Kimi fixer dispatch** — `prompt_model.py -t file,terminal` with a clear prompt to extract content into reference files
3. **Manual + verification** — do the refactoring, then verify with a simple script that checks file sizes and section counts

## Artifacts

- **Trace:** `/opt/data/devloop-traces/build-37YOUR_PHONE_NUMBERYOUR_PHONE_NUMBER04/trace.jsonl`
- **Judge verdicts:** `/opt/data/devloop-traces/build-37YOUR_PHONE_NUMBERYOUR_PHONE_NUMBER04/judge_verdicts.json`
- **Design spec:** `/opt/data/devloop-traces/build-37YOUR_PHONE_NUMBERYOUR_PHONE_NUMBER04/design_spec.json`
- **Devloop branch:** `devloop/build-37YOUR_PHONE_NUMBERYOUR_PHONE_NUMBER04` (only contains the test file)
- **Worktree:** `/opt/data/advisors-refactor` on branch `wt/advisors-skill-refactor`
- **LEARNINGS.jsonl entry:** `2026-07-06T13:08:56Z` — "test fault: criteria ['c1', 'c3', 'c4', 'c5', 'c7'] have no judge-trusted test"