# Fixed Pitfalls Archive

> Historical record of pitfalls found and fixed in devloop.
> These are preserved for debugging context but no longer active concerns.
> Extracted from SKILL.md 2026-07-07 to reduce skill size from 65KB → ~40KB.

### LLM-consolidated git history learnings for planning (2026-07-05)

**Status: FIXED.** The charter planner now receives a CONSOLIDATED summary of prior git history learnings, not raw commit excerpts. Two-phase approach:

1. **Mechanical extraction** — `_git_history_learnings()` scans the last 30 commits for THESIS/LEARNINGS/INTENTION sections, extracts raw full bodies, and also reads the cross-run `LEARNINGS.jsonl` journal. Fast (~10ms), no LLM needed.

2. **LLM consolidation** — The raw history is fed to the planner model with a consolidation prompt that enforces:
   - **Latest information wins** — if a later commit corrects an earlier learning, keep only the corrected version
   - **Consolidate by topic** — group related learnings, merge duplicates, not organized by commit
   - **Compact** — max 15 lines, each one actionable
   - **Reference SHAs** — each line prefixed with the commit SHA for traceability
   - **Skip noise** — ignore boilerplate and non-actionable observations
   - **Focus on patterns** — what worked, what failed, what was surprising

The consolidated summary is written to `.devloop/git_learnings_consolidated.txt` and injected into the charter prompt as a `PRIOR GIT HISTORY LEARNINGS` block. Falls back to mechanical extraction in test mode (`DEVLOOP_NO_HISTORY_LLM=1` or HERMES_BIN stubs).


### Rich journaling of learnings, references, and failure conditions (FIXED — 2026-07-05)

**Status: FIXED (commits `59aadf6` + `4716e84`).** A 3-seat advisor panel (DeepSeek + Kimi + MiniMax, 2026-07-05) found two critical gaps in the initial implementation. All P0, P1, and P2 fixes were applied in commit `4716e84` (442/442 tests pass). See `references/rich-journaling-advisor-review-2026-07-05.md` for the full consensus.

**What was built (bridge path, commit `59aadf6`):**

1. **Reordered `_run`**: Build the rich commit message BEFORE journaling (was reversed), so structured sections can be extracted and journaled.
2. **`_extract_commit_section()`**: Mechanically extracts LEARNINGS, REFERENCES from the commit message using a known-section header table — avoids false-positive cutoffs on `AVOID:` content lines.
3. **`_extract_failure_conditions()`**: Pulls AVOID: lines and failure-signal keywords from LEARNINGS text and from the run's reason on non-COMPLETE terminals.
4. **Enriched `_append_run_learning()`**: Journals `learnings_text`, `references`, and `failure_conditions` as structured fields.
5. **Enriched consolidator journal reader**: Feeds all rich fields to the LLM consolidator.
6. **Updated consolidator prompt**: "Latest wins on contradiction" rule, AVOID: prefix convention.

**P0 fixes (commit `4716e84`):**

- **Project outer loop now writes rich fields** (`project.py:268`): Extracts `learnings_text`, `references`, and `failure_conditions` from the bridge's `devloop_result.commit_message` and passes them to `state.append_learning`. The bridge now includes `commit_message` in `devloop_result`.
- **Mechanical fallback now includes the journal** (`dispatch.py:435`): `_mechanical_learnings_fallback` receives the `learnings_journal` and includes failure conditions in its output. A mechanical latest-wins dedup (by normalized line) prevents duplicates.

**P1 fixes (commit `4716e84`):**

- **Failure-condition extraction tightened**: Requires explicit `AVOID:` or `DO NOT` prefix on the line — substring matching removed.
- **AVOID: dedup in project fold**: Normalized lowercased form tracked; duplicates between `learnings_text` and `failure_conditions` are skipped.
- **Status metrics stripped from `lesson` field**: Rebuilds count and file counts removed — `lesson` is now design-oriented, not telemetry.
- **Mechanical latest-wins dedup**: Fallback path normalizes and deduplicates by line content.

**P2 fix (commit `4716e84`):**

- **Stale filename reference fixed**: `LEARNINGS.json` → `LEARNINGS.jsonl` in the fallback path.

**P5+P7+P8 improvements (commit `9cb229b`, 2026-07-05):**

- **P5 — Consolidator timeout warning**: When the LLM consolidator times out and falls back to mechanical extraction, a `logging.warning` is now emitted. Previously the fallback was silent — the planner got unconsolidated noise with no indication the "latest wins" rule wasn't applied.
- **P7 — `ts` field in bridge journal**: `_append_run_learning` now includes a `ts` (ISO 8601 UTC timestamp) field, matching the project loop's `_now()` format. Enables reliable chronological ordering in the consolidator.
- **P8 — Template fallback is design-oriented**: The `DEVLOOP_NO_COMMIT_LLM=1` template fallback now produces educational content (`Confirmed approach: ...` / `REFUTED THESIS: ...` / `Unresolved: ...`) instead of status lines (`Terminal: COMPLETE`, `Files: ...`). Includes `AVOID:` line for failures.

**P9 fix — Direct runner path rich fields (commit `4d0c6f1`, 2026-07-05):**

The P0 fix only worked through the bridge path (`devloop_bridge.run_build`). The default direct runner path (`runner.run_task` → `project.run_project`) returned no `devloop_result` wrapper, so `project.py` got `commit_msg=''` and LESSONS.jsonl entries had empty rich fields. Found by a 2-seat advisor panel (DeepSeek + Kimi) reviewing the improvement plan against the actual source code.

- **Fix**: `project.py` now synthesizes rich fields via `devloop_bridge._build_rich_commit_message` when no bridge wrapper is present (direct runner path). Same `_extract_commit_section` + `_extract_failure_conditions` as the bridge path.
- **Tests**: 3 new tests (P1a bridge path, P1b direct runner path, dedup test). 442 → 445 tests.
- **Documentation**: Two-journal split documented at top of both `project.py` and `devloop_bridge.py`.
- **Applied by**: Kimi (kimi-k2.7-code:cloud) as a fixer with `-t file,terminal`. Controller independently verified all patches, ran full test suite, committed, and pushed.

**Test safety:** `DEVLOOP_NO_COMMIT_LLM=1` env var skips the LLM commit message builder in tests. 442/442 tests pass (4 new tests added for P0-2, P1-4, P1-6).

**Pitfall:** A blank line before an `AVOID:` line caused the section extractor to cut early — `AVOID:` looks like an all-caps section header. Fixed by using a known-section header table instead of any all-caps word.


### N1+N2+N3 — Consolidator reads LESSONS.jsonl, eliminate triple-extraction, clean import (FIXED 2026-07-05)

**Status: FIXED (commit `4da32ee`).** A 2-seat advisor panel (DeepSeek + Kimi, GLM synthesis) reviewed the plan and identified key refinements before implementation. The controller implemented all 3 fixes directly (not via fixer dispatch — faster when the controller has full context).

**N1 — Consolidator reads project-local LESSONS.jsonl:**
- `dispatch.py:_git_history_learnings` now reads `target_dir/.devloop/LESSONS.jsonl` in addition to `LEARNINGS.jsonl`, with same last-20 cap
- Project-local learnings (now rich after P9) reach the planner's git history context
- Consolidator prompt updated to mention both journal sources
- Guarded with `os.path.isfile` (may not exist on fresh worktree)

**N2 — Eliminate triple-extraction risk:**
- `_append_run_learning` now RETURNS the extracted rich fields dict
- `_run` captures the return and exposes `learnings_text`/`references`/`failure_conditions` directly in `devloop_result`
- `project.py` consumes `devloop_result` rich fields directly (no re-extraction)
- `failure_result` mirrors the new keys (`test_failure_result_shape_matches_run_shape` passes)
- Only the direct runner path still synthesizes (one extraction point, not three)

**N3 — Clean up duplicate import:**
- Single `import devloop_bridge` at top of synthesis block (was duplicate in if/else)
- Naturally resolved by N2's restructure

**Tests:** 445 → 447 (2 new: `test_consolidator_reads_project_lessons_jsonl`, `test_devloop_result_has_rich_fields`). All pass.

**Advisor feedback incorporated:**
- Drop glob discovery → direct `target_dir` read
- Drop source tagging (YAGNI)
- `_mechanical_learnings_fallback` gets LESSONS content via merged journal
- Mirror rich fields in `failure_result` (test would break otherwise)
- Update consolidator prompt text (both sources)
- `os.path.isfile` guard (fresh worktree)
- N2 before N3 order

**Pitfall:** The controller implemented directly rather than dispatching a fixer — this was faster because the controller had full context (plan + advisor feedback fresh in mind). Reserve fixer dispatch for when the controller lacks context or the changes are mechanical/boilerplate. See `advisors/references/plan-review-implement-devloop-2026-07-05.md` for the full Pattern 9 real run.


### AVOID: double-prefix in consolidator journal (FIXED 2026-07-05)

**Status: FIXED (commit `f511f95`).** Found by a 2-seat quality review (DeepSeek + Kimi, GLM synthesis) of commit `4da32ee`. When a `failure_conditions` entry already starts with `AVOID:`, the journal rendering `f"    AVOID: {fc}"` at `dispatch.py:451/490` produced `AVOID: AVOID: ...` — a double-prefix that polluted the consolidator journal and leaked through mechanical dedup.

**Fix:** Strip existing `AVOID:`/`DO NOT` prefix before re-prefixing in both the LEARNINGS.jsonl and LESSONS.jsonl journal readers. One-line guard per occurrence.

**Test:** 447 → 448 (1 new: `test_avoid_double_prefix_stripped_in_consolidator`). All pass.

**Key insight:** This bug was missed by both the controller and the implementation-phase advisors. Only the post-implementation quality review (Phase 4 of Pattern 9) caught it. A 2-seat quality review costs ~4 minutes and catches bugs that would otherwise ship.


### Rich commit messages — LLM-driven with learnings file (2026-07-05)

**Status: FIXED.** Devloop commits were bare labels (`devloop COMPLETE: <name>`, `devloop: squash-merge <branch>`) with no context. Now every devloop commit is synthesized by an LLM from the run's full trace data, producing INTENTION/THESIS/LEARNINGS/REFERENCES sections with exact git positions.

**How it works:**

1. **Learnings journal** — After every run, `_append_run_learning()` in `devloop_bridge.py` appends the run's outcome (terminal, criteria trusted, rebuilds, reason) to `devloop-traces/LEARNINGS.jsonl`. This is an append-only journal that accumulates lessons across runs.

2. **LLM synthesis** — `_build_rich_commit_message()` dispatches an LLM call with:
   - Run data: intent, terminal, judge verdicts, evidence results, rebuilds, changed files, trace path
   - Prior learnings: last 20 entries from `LEARNINGS.jsonl`
   - Recent git log: 10 commits with exact SHAs
   - Trace events: last 30 events from the run's `trace.jsonl`
   
   The LLM synthesizes these into a structured commit message with exact git positions for future reference.

3. **Template fallback** — If the LLM is unavailable or the run has no real grounding data (test fake), falls back to a template message. The `DEVLOOP_NO_COMMIT_LLM=1` env var skips the LLM call entirely.

4. **Test safety** — The LLM call only fires when real grounding data exists (`grounding.criteria` or `trace_summary` is non-empty) AND `HERMES_BIN` is not a test stub (paths starting with `/tmp/` are skipped). This prevents real LLM calls during test suite runs.

Both the branch commit (`worktree.finalize`) and the squash merge commit (`worktree.merge_branch`) use the rich message. See `git-learnings` skill for the format specification.


### ANSWERS mechanism now feeds through to the designer (FIXED 2026-07-05)

**Status: FIXED.** The ANSWERS→designer gap was the primary bottleneck in the
5-round calendar-quick-add failure. Two patches applied:

1. **runner.py** — Extracts `— ANSWERS: ...` from the request string and annotates
   the charter with `_answers` before passing it to the designer.
2. **dispatch.py** `designer_spec_via_ask()` — Reads `_answers` from the charter
   and appends it to the designer prompt: `"USER ANSWERS (from a prior round — these
   override defaults):\n{answers}\n"`.

The designer now sees ANSWERS from HUMAN_REVIEW rounds. This was the root cause of
5/5 calendar-quick-add failures where the designer kept generating string-literal
tests despite explicit ANSWERS to use real datetime objects.

**If this still fails:** The remaining gap is Fix 4 (loop.py redesign path doesn't
pass judge verdicts to the redesign call — see below). When devloop stalls in a
test-judge loop (3+ rounds with the same criterion failing despite ANSWERS), stop
and build the skill directly. The engine's test-quality gates are correct.


### Renderer now supports call_args inspection (FIXED 2026-07-05)

**Status: FIXED.** `_mock_with()` in render.py now returns a `(with_line, post_lines)`
tuple instead of a single string. Post-lines are indented into the mock `with` block
body, enabling:

- `assert_called_once: true` → `{mock}.assert_called_once()`
- `assert_called_with: [[args], {kwargs}]` → `{mock}.assert_called_with(args, kwargs)`
- `assert_call_arg: [pos, key, expected]` → `assert {mock}.call_args[pos][key] == expected`

`_DESIGN_SPEC_PROMPT` was also enhanced with guidance on when to use raw escape hatch
(non-JSON-literal types, call_args inspection, side-effect verification) and how to
use the new structured mock assertion fields.

**Test suite impact:** 405 passed, 3 pre-existing tests need updating for the new
tuple return format (`test_render_header_imports_only_whats_used`,
`test_render_mocks_and_approx`,
`test_render_skips_nonallowlisted_side_effect_failclosed`).


### Quality lint now triggers redesign, not immediate HUMAN_REVIEW (FIXED 2026-07-05)

**Status: FIXED (commit `4b2df1e`).** The quality_lint gate originally had only two
outcomes: pass or HUMAN_REVIEW. When the designer generated tests with `mock.patch`
patterns (which structured mode with `mocks` always renders as), the run died
immediately — wasting the charter/design cycle. The judge-distrust path already had
a redesign retry; quality_lint now gets the same treatment.

**Fix (loop.py):** When quality_lint fails and `repair_used` is still available,
the run spends its ONE oracle regeneration budget on a redesign. The quality_lint
findings are fed to the designer as judge-style feedback (category + fix hint),
so the designer knows exactly what patterns to avoid. If the redesign passes
quality_lint, the run continues to judges; if it still fails, the run routes to
HUMAN_REVIEW with the findings.

**Designer prompt hardening (dispatch.py):** The designer prompt now includes a
CRITICAL section explaining that structured mode with `mocks` ALWAYS renders as
`with mock.patch(...)` — which the quality lint gate rejects. The model is told
to use the RAW ESCAPE HATCH for any criterion that touches an external dependency
(subprocess, urllib.request, os.environ, etc.). Structured mode is only safe for
pure-logic criteria (string parsing, URL building, data transformation).

**Key insight:** The original prompt said "use DI not mock.patch" but didn't
explain that structured mode with `mocks` = `mock.patch` = rejected. The model
kept using structured mode with mocks thinking it was fine. The fix makes the
causal chain explicit: structured mocks → mock.patch → quality_lint rejection →
use raw escape hatch instead.

**Same budget as judge-distrust:** ONE oracle regeneration per run (repair_used
flag), so this doesn't increase run cost — it just spends the budget earlier
and cheaper (quality_lint redesign is ~30s vs ~6min for a full judge round-trip).


### Redesign path now incorporates judge feedback (FIXED 2026-07-05)

**Status: FIXED.** Three complementary improvements applied (2026-07-05, commit `1eb0de2`):

1. **Pre-judge static gate** (`quality_lint.py`, Kimi): Catches 5 known-bad patterns
   (module-level `mock.patch`, `Mock` without call inspection, datetime string literals,
   weak substring command assertions, `assert_called_with` on non-Mock)
   in <100ms BEFORE the expensive judge round-trip. Wired into `loop.py` after coverage
   and before judges. 10 regression tests in `tests/test_quality_lint.py`.

2. **Judge reason text** (Minimax): Judges now return `(bool, str)` instead of bare
   `bool`. The str is a one-sentence reason extracted from the judge's second reply
   line. `dod_oracle.py` returns `judge_a_reason`/`judge_b_reason` fields in verdicts.
   `runner._redesign` threads the reason text into the designer feedback prompt.
   `loop.py` trace and `_design_spec` include judge reasons. Backward-compatible:
   `_unwrap()` normalizes bare `bool` → `(bool, "")`.

3. **Designer prompt negative examples** (Kimi): `_DESIGN_SPEC_PROMPT` now includes
   three concrete bad→good examples (stdio patch → DI, mock.patch → parameter injection,
   string datetime → real datetime) so the designer avoids known-bad patterns from the
   start.

See `references/three-layer-defense-2026-07-05.md` for the full architecture and
`references/validation-run-2026-07-05.md` for the end-to-end validation that
proved the fix: the same `calendar-quick-add` request that failed 5 times before
succeeded in 1 round with 0 rebuilds after the 3-layer defense was applied.


### render.py: `_lit()` converts datetime to string, not code literal (FIXED 2026-07-05)

**Status: FIXED.** `_lit()` now special-cases `datetime`, `date`, `time`, and
`timedelta` before the `repr()` fallback, emitting real code literals (e.g.,
`datetime(2026, 7, 6, 12, 0)` instead of the string `'datetime.datetime(2026, 7, 6, 12, 0)'`).
Lists, tuples, and dicts are rendered recursively so datetime elements inside
compound values also get the special-case treatment. A `from datetime import
datetime, date, time, timedelta` header is auto-added to rendered test files
when any datetime-typed value is detected.

See `references/advisor-consensus-2026-07-05.md` for the full 5-advisor review
and `references/render-py-bugs-2026-07-05.md` for the implementation details.


### render.py: `inject_as_callable` and `dep_inject` branches are structurally broken (FIXED 2026-07-05)

**Status: FIXED.** Both DI branches in `_mock_with()` were removed. They produced
invalid Python and no test exercised either branch. The normal mock path already
handles `assert_called_once`, `assert_called_with`, and `assert_call_arg` correctly.
Raw mode handles DI. See `references/advisor-consensus-2026-07-05.md` (P0).


### Judge verdicts now return reason text (FIXED 2026-07-05)

**Status: FIXED.** Judges now return `(bool, str)` tuples — the bool vote plus a
one-sentence reason. `dod_oracle.judge_assertions` returns `judge_a_reason` and
`judge_b_reason` fields in verdicts. `runner._redesign` threads the reason text
into the designer feedback prompt so the redesigner knows WHY tests were rejected,
not just THAT they were rejected. `loop.py` trace and `_design_spec` include judge
reasons. Backward-compatible: `_unwrap()` normalizes bare `bool` → `(bool, "")`.
118/118 tests pass. See `references/three-layer-defense-2026-07-05.md`.


### GLM-5.2 planner returns bare strings for open_questions/assumptions (FIXED 2026-07-05)

**Status: FIXED (commit `efde4e3`).** The planner model (GLM-5.2:cloud) sometimes returns
`open_questions` and `assumptions` as lists of **strings** instead of the expected
dict shape (`{"text": "...", "blocking": false}` / `{"text": "...", "confidence": 0.7}`).
`validate_charter()` in `state.py:142` correctly rejects these with
`"open_questions[0] is not an object"`, routing to HUMAN_REVIEW — but this wastes a
full devloop round-trip on a model output format issue, not a real ambiguity.

**Fix:** `_coerce_qa()` in `dispatch.py` now accepts a `kind=` parameter
(`"open_questions"` or `"assumptions"`) and adds ONLY the relevant key:
`blocking` for open_questions, `confidence` for assumptions. Previously it added
BOTH keys to every bare string, cross-contaminating the schema. The call sites
in `_wrap_charter()` pass the correct `kind` for each field.

**Quality review (2026-07-05):** A 2-seat panel (DeepSeek + Kimi, GLM synthesis)
found this as one of 3 remaining items after the main N1+N2+N3 implementation.
The key pollution was a real bug — `_coerce_qa` was adding `confidence` to
open_questions and `blocking` to assumptions, which downstream code could
misinterpret. Also fixed: merge ordering documented (LESSONS.jsonl appended after
LEARNINGS.jsonl so project-local wins), and `_append_run_learning` now logs a
warning when it silently returns empty rich fields due to an exception.

See `references/glm-charter-bare-strings-2026-07-05.md` for the full diagnosis.


### Integration test example was tautological (FIXED 2026-07-05)

**Status: FIXED.** The charter prompt's integration-tier example used
`result.returncode in (0, 1)` — a tautology that passes regardless of the
actual exit code. Changed to `result.returncode == 0` with a real assertion
(`'summary' in result.stdout.lower()`). Caught by Kimi and Minimax in the
3-seat advisor review of the 2026-07-05 devloop fixes. See
`references/advisor-consensus-skills-2026-07-05.md`.


### External-system trigger was too broad (FIXED 2026-07-05)

**Status: FIXED.** The charter prompt's "MANDATORY EXTERNAL-SYSTEM INTEGRATION
CRITERIA" section triggered on ANY mention of an external system, including
code that CONSUMES or PARSES external output (e.g., "parse the JSON returned
by gh pr list"). This would over-generate integration criteria for parsers
and wrappers. Narrowed to: integration tier is required only when the code
INITIATES the outbound call itself. Added explicit NOTE distinguishing
INITIATE from CONSUME. Caught by all 3 advisors. See
`references/advisor-consensus-skills-2026-07-05.md`.


### No impl-phase defense against helper-wrapping (FIXED 2026-07-05)

**Status: FIXED.** The coder prompt (`_IMPL_STYLE`) had no rule preventing
the coder from wrapping external binary calls in internal helper functions
that the test then mocks — defeating the integration test entirely. Added
EXTERNAL BOUNDARY RULE: if the DoD includes an integration-tier criterion
that exercises a real external binary, the implementation MUST call that
binary directly via subprocess. Wrapping it in a helper that gets mocked
defeats the integration test. Caught by Minimax. See
`references/advisor-consensus-skills-2026-07-05.md`.


### Overfit audit was 54% of wall-clock (FIXED 2026-07-05)

**Status: FIXED.** The overfit audit ran 2 auditors × N criteria sequentially,
taking 357.6s (54%) of an 11-minute run. The judges already used `ThreadPoolExecutor`
for the same 2×N pattern (56.5s). The fix: parallelize the overfit audit with the
same `ThreadPoolExecutor` pattern. Verified savings: ~5 minutes per run (now ~60s for 8 calls).
See `references/validation-run-learnings-2026-07-05.md`.


### Zero progress output during runs (FIXED — Phase 1 complete 2026-07-06)

**Status: FIXED.** Devloop produced zero output during 11-minute runs — the user
saw nothing until COMPLETE or HUMAN_REVIEW. Two-phase fix:

**Phase 1 (2026-07-06):** Planning announcements in `runner.py` emit structured
multi-line output to stderr at each pre-loop phase: planning-begin (request, target,
branch, planner model, prior learnings, env survey), charter-complete (DoD criteria
with tiers, assumptions, blocking questions), refine-complete (criteria count change),
advisor-complete (blocking concerns or all-clear), and HUMAN_REVIEW (blocking questions
with re-run hint). `DEVLOOP_PROGRESS` env var controls output level: `verbose` (default,
all output), `compact` (loop-phase markers only), `quiet` (no stderr progress).

**Phase 2 (planned):** Richer output after design, judge, evidence, and stop_check
phases — per-criterion judge verdicts, evidence pass/fail counts, rebuild attempt
summaries, and key learnings after each iteration. The Phase 2-5 plan was reviewed
by a 3-seat advisor panel (DeepSeek + Kimi + Qwen) — see
`references/advisor-review-progress-phase1-2026-07-06.md` for the full consensus
and plan adjustments.

See the Observability section above for the full output format.


