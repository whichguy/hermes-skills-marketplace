# Quality Lint Redesign — 2026-07-05

## Problem

The quality_lint gate (Layer 1 of the 3-layer defense) caught known-bad test patterns
(module-level `mock.patch`, `Mock` without call inspection, etc.) but had only two
outcomes: pass or HUMAN_REVIEW. When the designer generated tests with `mock.patch`
patterns, the run died immediately — wasting the charter/design cycle.

The judge-distrust path already had a redesign retry (spend ONE oracle regeneration
budget to fix tests). Quality_lint should get the same treatment.

## Root Cause

The designer prompt said "use DI not mock.patch" but didn't explain the causal chain:
structured mode with `mocks` → renders as `with mock.patch(...)` → quality_lint rejects.
The model kept using structured mode with mocks thinking it was fine.

## Fix (commit `4b2df1e`)

### loop.py — quality_lint redesign path

When quality_lint fails and `repair_used` is still available:
1. Build quality_feedback from findings (same shape as judge verdicts)
2. Call `redesign(charter, all_cids, quality_feedback)` 
3. Re-run quality_lint on the redesigned tests
4. If pass → continue to judges
5. If still fail → HUMAN_REVIEW with findings

### dispatch.py — designer prompt hardening

Added CRITICAL section to `_DESIGN_SPEC_PROMPT`:
- Structured mode with `mocks` ALWAYS renders as `with mock.patch(...)` — REJECTED
- For ANY criterion touching external deps (subprocess, urllib, os.environ), use RAW ESCAPE HATCH
- Structured mode is only safe for pure-logic criteria (string parsing, URL building, data transformation)

## Key Insight

The original prompt's DI guidance was correct but incomplete. It said "use DI not mock.patch"
but didn't explain that structured mode with `mocks` = `mock.patch` = rejected. The model
needed the full causal chain to understand WHY it couldn't use structured mode.

## Budget

Same as judge-distrust: ONE oracle regeneration per run (`repair_used` flag). This doesn't
increase run cost — it just spends the budget earlier and cheaper (quality_lint redesign
is ~30s vs ~6min for a full judge round-trip).

## Test Coverage

448/448 tests pass. The quality_lint redesign path is exercised by the existing
`test_quality_lint.py` suite (10 tests) plus the full devloop test suite.
