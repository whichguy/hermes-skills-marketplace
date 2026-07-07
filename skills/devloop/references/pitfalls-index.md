# Pitfalls index

A catalog of live-caught failure modes and current mitigations. Each entry links to the full
write-up in `references/`. This is the expanded content behind the short table in
`SKILL.md`.

## LLM-consolidated git history learnings for planning

**Status: FIXED.** The charter planner now receives a CONSOLIDATED summary of prior git
history learnings, not raw commit excerpts. See `rich-journaling-advisor-review-2026-07-05.md`
for the two-phase approach (mechanical extraction → LLM consolidation) and the P0/P1/P2/P9 fixes.

## Rich journaling of learnings, references, and failure conditions

**Status: FIXED 2026-07-05 (commits `59aadf6`, `4716e84`, `4d0c6f1`, `4da32ee`, `f511f95`).**
A 3-seat advisor panel found critical gaps in the initial implementation. All P0, P1, P2
fixes were applied; 448/448 tests pass. See
`rich-journaling-advisor-review-2026-07-05.md` for the full consensus, commit details,
and the P9 direct-runner-path fix.

## N1+N2+N3 — Consolidator reads LESSONS.jsonl, eliminate triple-extraction, clean import

**Status: FIXED 2026-07-05 (commit `4da32ee`).** A 2-seat advisor panel identified that the
consolidator should read project-local LESSONS.jsonl, that rich fields should be passed
directly instead of re-extracted, and that a duplicate import should be cleaned up.
447 → 448 tests. See `rich-journaling-advisor-review-2026-07-05.md`.

## AVOID: double-prefix in consolidator journal

**Status: FIXED 2026-07-05 (commit `f511f95`).** When a `failure_conditions` entry already
started with `AVOID:`, journal rendering produced `AVOID: AVOID: ...`. Fixed by stripping
existing `AVOID:`/`DO NOT` prefixes before re-prefixing. Caught by a 2-seat quality review.
See `rich-journaling-advisor-review-2026-07-05.md`.

## Rich commit messages — LLM-driven with learnings file

**Status: FIXED 2026-07-05.** Every devloop commit is now synthesized by an LLM from the
run's full trace data, producing INTENTION/THESIS/LEARNINGS/REFERENCES sections with exact
git positions. `DEVLOOP_NO_COMMIT_LLM=1` skips the LLM call. See
`rich-journaling-advisor-review-2026-07-05.md`.

## render.py: missing basic mock return

The `_mock_with` basic mock case fell through to a bare comment and returned `None`, crashing
`_render_entry`. Fixed by adding the missing `return (with_line, post)`. See
`render-py-bugs-2026-07-05.md`.

## render.py: broken `inject_as_callable` placeholder

The `inject_as_callable` path returned a malformed tuple with a dead `if False` branch,
causing the caller to use `None` as a string. Fixed by returning `(None, inject_post)`
cleanly and updating `_render_entry` to handle `withline is None`. See
`render-py-bugs-2026-07-05.md`.

## render.py: `_lit()` converted datetime to string

`_lit()` now special-cases `datetime`/`date`/`time`/`timedelta` before the `repr()` fallback,
emitting real code literals and auto-importing them. See `advisor-consensus-2026-07-05.md` and
`render-py-bugs-2026-07-05.md`.

## render.py: `inject_as_callable` and `dep_inject` branches structurally broken

**Status: FIXED 2026-07-05.** Both DI branches produced invalid Python and were untested.
Removed; raw mode handles DI. See `advisor-consensus-2026-07-05.md`.

## ANSWERS mechanism now feeds through to the designer

**Status: FIXED 2026-07-05.** The ANSWERS→designer gap was the primary bottleneck in the
5-round calendar-quick-add failure. `runner.py` extracts `— ANSWERS: ...` from the request
and `dispatch.py` `designer_spec_via_ask()` appends it to the designer prompt. See
`human-review-recovery.md` and `test-rendering-root-cause.md`.

## Renderer now supports call_args inspection

**Status: FIXED 2026-07-05.** `_mock_with()` returns `(with_line, post_lines)` instead of a
single string, enabling `assert_called_once`, `assert_called_with`, and `assert_call_arg`
inside the mock `with` block. See `three-layer-defense-2026-07-05.md`.

## Quality lint now triggers redesign, not immediate HUMAN_REVIEW

**Status: FIXED 2026-07-05 (commit `4b2df1e`).** The quality_lint gate now spends the ONE
oracle regeneration budget on a designer redesign when it fails, matching the judge-distrust
path. The designer prompt now explicitly explains that structured mode with `mocks` ALWAYS
renders as `mock.patch` and therefore must use the raw escape hatch for external deps. See
`quality-lint-redesign-2026-07-05.md`.

## Redesign path now incorporates judge feedback

**Status: FIXED 2026-07-05 (commit `1eb0de2`).** Three complementary improvements:
pre-judge static lint gate, judge reason text returned as `(bool, str)`, and designer prompt
negative examples. See `three-layer-defense-2026-07-05.md` and
`validation-run-2026-07-05.md`.

## Judge verdicts now return reason text

**Status: FIXED 2026-07-05.** Judges now return `(bool, str)`. `dod_oracle.py` returns
`judge_a_reason`/`judge_b_reason`; `runner._redesign` threads reason text into the designer
feedback. See `three-layer-defense-2026-07-05.md`.

## GLM-5.2 planner returns bare strings for open_questions/assumptions

**Status: FIXED 2026-07-05 (commit `efde4e3`).** `_coerce_qa()` in `dispatch.py` now accepts
a `kind=` parameter and adds ONLY the relevant key (`blocking` for open_questions,
`confidence` for assumptions), fixing cross-contamination. See
`glm-charter-bare-strings-2026-07-05.md`.

## Charter under-decomposes deliverable artifacts

The charter phase may not produce criteria for every named deliverable. In the validation
run, the request named `SKILL.md` and `known_places.json` but devloop only built code and
tests. **Mitigation:** when the request names specific deliverable files, verify the charter
has a criterion for each; if not, add a blocking open_question. See
`validation-run-learnings-2026-07-05.md`.

## All-unit criteria miss integration surface

The charter may produce only unit-tier criteria even when the deliverable has a CLI/API
boundary. **Mitigation:** for CLI/API requests, verify at least one integration-tier
criterion exists; if not, add a blocking open_question. Future: auto-generate integration-tier
criteria for skills with CLI entry points. See `validation-run-learnings-2026-07-05.md`.

## Unit tests with mocked external CLIs can't catch command-format bugs

**Critical finding from e2e validation.** devloop-produced `calendar-quick-add` passed all
unit tests but failed against the real `gws` binary because the unit tests only checked
substrings in the command string. **Mitigation:** when the deliverable calls an external
CLI, the charter MUST include at least one integration-tier criterion that runs the real
binary with `--dry-run` (or equivalent) and verifies the API call shape. See
`e2e-verification-gap-2026-07-05.md` and `advisor-consensus-fixes-2026-07-05.md`.

## Prevention > detection > correction

The 3-layer defense (prompt negative examples → static lint gate → judge rejection) forms a
defense-in-depth where each layer is cheaper than the one below. Invest in prevention before
detection before correction. See `validation-run-learnings-2026-07-05.md`.

## Integration test example was tautological

**Status: FIXED 2026-07-05.** The charter prompt's integration-tier example used
`result.returncode in (0, 1)` — a tautology. Changed to `result.returncode == 0` with a real
assertion. See `advisor-consensus-skills-2026-07-05.md`.

## External-system trigger was too broad

**Status: FIXED 2026-07-05.** The "MANDATORY EXTERNAL-SYSTEM INTEGRATION CRITERIA" section
triggered on ANY mention of an external system, including parsers/consumers. Narrowed to:
integration tier required only when the code INITIATES the outbound call. See
`advisor-consensus-skills-2026-07-05.md`.

## No impl-phase defense against helper-wrapping

**Status: FIXED 2026-07-05.** The coder prompt had no rule preventing wrapping external
binary calls in internal helpers that the test then mocks. Added EXTERNAL BOUNDARY RULE:
if the DoD includes an integration-tier criterion exercising a real external binary, the
implementation MUST call that binary directly via subprocess. See
`advisor-consensus-skills-2026-07-05.md`.

## Overfit audit was 54% of wall-clock

**Status: FIXED 2026-07-05.** The overfit audit ran sequentially; now uses
`ThreadPoolExecutor` like the judges, cutting ~5 minutes per run. See
`validation-run-learnings-2026-07-05.md`.

## Zero progress output during runs

**Status: FIXED Phase 1 2026-07-06.** Planning announcements emit structured stderr output
at each pre-loop phase. Phase 2-5 planned. See
`advisor-review-progress-phase1-2026-07-06.md` and `observability-testing.md`.

## Post-implementation e2e dry-run gate

**Status: AGAINST by advisors.** Both DeepSeek and Minimax argued against a post-implementation
e2e dry-run gate as fragile, false-positive-prone, and redundant with integration-tier criteria
plus quality-lint substring checks. The bug was in the test's expectation, not the
implementation. See `advisor-consensus-fixes-2026-07-05.md`.

## Test-rendering root cause

For the full round-by-round analysis of the 5 consecutive calendar-quick-add failures
(test fault, not implementation), the four code-level root causes, and the recovery pattern,
see `test-rendering-root-cause.md`.

## P0-P2 validation

After applying the render.py fixes, devloop was re-run on the same calendar-quick-add
request: 3/4 criteria passed judges (was 0/4). c4 (CLI main) remained rejected. See
`p0-p2-validation-2026-07-05.md`.

## Static gate

`test_quality_lint.py` runs BEFORE the expensive judge round-trip, catching known-bad test
patterns in <100ms. See `static-gate-2026-07-05.md`.

## Session learnings and improvement plan

7 learnings identified from the devloop journaling work, advisor review, Slack inspection,
and gateway stability issues. 3 improvements already implemented (P5/P7/P8). See
`session-learnings-improvement-plan-2026-07-05.md`.
