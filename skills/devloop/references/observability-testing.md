# Observability + testing

## Progress stream

Devloop emits structured progress to stderr in two layers. Both go to stderr so they don't
interfere with stdout JSON output. `DEVLOOP_PROGRESS` controls the level:
- `verbose` (default): planning announcements + loop-phase markers
- `compact`: loop-phase markers only
- `quiet`: nothing

**Planning announcements** (Phase 1, 2026-07-06), emitted from `runner.py` before
`loop.run_v1` starts:

```
[devloop] 🧭 planning loop beginning
[devloop]   request: "Create slug.py with slugify(text): ..."
[devloop]   target: /opt/data/devloop-workspaces/.../.worktrees/...
[devloop]   branch: master @ 2703fc5
[devloop]   planner: glm-5.2:cloud
[devloop]   prior learnings: none (fresh workspace)
[devloop]   env survey: empty (greenfield)
[devloop] ✅ charter: 1 criteria (1 unit), 2 assumptions, 0 blocking questions
[devloop]   c1: slugify lowercases, trims, and hyphen-joins words [unit]
[devloop] ✅ refine: 1 → 3 criteria (split)
[devloop] ✅ advisor: no blocking concerns
```

**Loop-phase markers** (2026-07-05, expanded 2026-07-07 and 2026-07-08), emitted from `loop.py`.
Every significant phase now shows a ⏳ start marker (with context about what it's doing) followed
by a ✅/❌ completion marker (with the outcome). This start/completed pairing convention was
added 2026-07-08 so the user can see when a long phase began and when it finished:

```
[devloop] ⏳ charter (0s): decomposing request...
[devloop] ⏳ ambiguity_gate (0s): passed
[devloop] ⏳ design (0s ~120s): generating tests for 4 criteria...
[devloop] ✅ design (0s): 4 test(s) rendered for 4 criteria
[devloop] ✅ coverage (0s): 4 tests covering 4 criteria
[devloop] ✅ quality_lint (0s): checking rendered tests
[devloop] ⏳ judge (0s ~60s): judging 4 test(s) for 4 criteria...
[devloop] ✅ judge (21s): 4/4 criteria trusted
[devloop] ✅ lint_discovery (0s): discovered available linters
[devloop] ⏳ implement (0s ~240s): coder attempt 0...
[devloop] ✅ implement (34s): attempt 0, 2 file(s) changed
[devloop] ⏳ lint (0s ~10s): checking 2 file(s), attempt 0
[devloop] ✅ lint (0s): 3 checked, 0 skipped
[devloop] ⏳ evidence (0s): running evidence for 4 criteria, attempt 0...
[devloop] ✅ evidence (0s): attempt 0, 4/4 passed
[devloop] ✅ stop_check (0s): DoD-SATISFIED
[devloop] ⏳ regression (0s ~30s): running whole-suite regression...
[devloop] ✅ regression (0s): whole-suite
[devloop] ⏳ overfit_audit (0s): auditing 4 criteria x 2 auditors...
[devloop] ✅ overfit_audit (92s): 4 criteria x 2 auditors
[devloop] ⏳ commit_scope (0s): classifying changed files...
[devloop] ✅ commit_scope (0s): all files are deliverable
[devloop] ⏳ complete (0s): all gates passed, merging...
```

**Start/completed pairing convention** (2026-07-08): every phase that takes real time
(judge, implement, evidence, regression, overfit_audit, commit_scope, complete) gets both
a ⏳ start marker and a ✅/❌ completion marker. Instantaneous phases (charter, ambiguity_gate,
lint_discovery, frozen_tests, replan, redesign) stay single-marker. The implement phase
was the last to get a completion marker — it previously only had the start marker
(`coder attempt N...`) with no completion.

On failures, the new markers show what went wrong and the recovery path:
```
[devloop] ❌ lint: 2 checked, 0 skipped, 2 FAIL
[devloop] ❌ rebuild: attempt 0 failed lint → rebuild 1
[devloop] ❌ rebuild: attempt 0 failed regression → rebuild 2
[devloop] ❌ rebuild: attempt 0 evidence failed (3/4) → rebuild 1
[devloop] ❌ frozen_tests: violation detected, 1 file(s) restored
[devloop] ❌ replan: replan 1 triggered
[devloop] ✅ test_repair: oracle regenerated for ['c2']
[devloop] ✅ test_repair: overfit audit regenerated tests for ['c1']
[devloop] ✅ commit_scope: 2 file(s) dropped as scratch
```

**Phase 2 detail** (2026-07-07): per-criterion judge verdicts with elapsed time,
individual judge votes, and reason text on distrust:
```
[devloop] ✅ judge (41s): 1/1 criteria trusted
[devloop] ✅ judge (41s):   c1: ✓ trusted (judge_a:✓ judge_b:✓)
```
On distrust: `c2: ✗ (judge_a:✗ judge_b:✓) — "mock.patch at module level"`

**Phase 3 detail** (2026-07-07): evidence pass/fail counts after the evidence loop:
```
[devloop] ✅ evidence: 4/4 passed
```
On failure: `[devloop] ❌ evidence: 3/4 passed — FAILED: c2, c3`

**Phase 4 rebuild summary** (2026-07-07): when a coder attempt fails and triggers
a rebuild:
```
[devloop] 🔄 rebuild: attempt 0 failed — re-implementing
```

**Machine-parseable progress** (2026-07-07): every run writes `progress.jsonl` into
the trace bundle alongside `trace.jsonl`. Each line is a JSON object with `ts`,
`step`, `detail`, `ok`, and `elapsed_s`. The digest script (`scripts/devloop_digest.py`)
reads this file for zero-LLM daily summaries. See `references/observability-testing.md`
for the full schema.

## Trace and inspection bundle

Every run writes `trace.jsonl`: charter (full DoD/assumptions/open_questions), gates, judge
verdicts per judge, evidence exits, regression, timings. Render with `trace_view.py <trace>`,
or `trace_view.py --chain <trace>` for the per-criterion TDD chain (promise → intention →
judge votes → tests → evidence per attempt → terminal).

The durable **inspection bundle** survives worktree cleanup at
`<write-safe>/devloop-traces/<name>/` (2026-07-03): charter.json, design_spec.json,
rendered_tests.json, judge_verdicts.json, attempts.jsonl, grounding.json, checkpoint.json, and
(with `DEVLOOP_DEBUG=1`) dispatch/ with every model call's full prompt + raw reply.

## Testing tiers

Use `tests/tiers.py <tier>`. Real-model tests are env-gated (`DEVLOOP_RUN_REAL`), so `fast`
excludes them for free.

| Tier | What | ~Time | LLM? | When |
|---|---|---|---|---|
| `fast` | the WHOLE deterministic suite (`pytest tests/`) | ~10s | No | every change |
| `smoke` | one tiny `add(a,b)` build end-to-end through the real v1 loop | ~1-2m | Yes (1) | quick gut-check |
| `mutants` | optional extended mutation guard — every registered mutant killed | ~5-6m | No | on demand / before main merge |
| `spike` | QUICK real-engine go-check: 1 modify + 1 vague from `spike/tasks_quick.jsonl` | ~5m | Yes (2) | routine "is the engine still safe" |
| `spike-full` | COMPREHENSIVE: `spike/tasks_extended.jsonl` (12 tasks × 3) | ~2-3h | Yes | on demand, detached |

```bash
# in-container, under uv (so pytest is importable):
uv run --with pytest python3 tests/tiers.py fast
uv run --with pytest python3 tests/tiers.py all      # fast -> smoke
uv run --with pytest python3 tests/tiers.py full     # fast -> full mutation guard
uv run --with pytest python3 tests/tiers.py suite loop-spine
uv run --with pytest python3 tests/tiers.py suite loop-spine full  # group + scoped mutants
```

Every `tests/test_*.py` also runs dependency-free (`python3 tests/test_x.py`) — no pytest, no
conftest.

## Suite index (summary)

`fast` is sliced into named groups. The group → file mapping lives ONLY in `tests/tiers.py`
(`SUITES`); `tests/test_smoke.py` pins that the groups partition `mutants.TEST_FILES` exactly.

| Group | Validates |
|---|---|
| `fail-closed-kernel` | refusal paths that guard COMPLETE (empty DoD, NaN confidence, vague goals, fabricated benchmarks, false-complete detection) |
| `evidence-state` | real exit codes + persistence honesty |
| `design-oracle` | structured spec → rendered pytest |
| `loop-spine` | run_v1 mechanics (frozen-tests self-heal, lint blocks, back-off caps, test repair, overfit/scope audits, grounding) |
| `runner-pipeline` | per-task pipeline (vague/low-confidence routing, non-Python, crash-finalize, model collision) |
| `worktree-merge` | isolation + fail-safe auto-merge + pre-merge sync + ref-CAS landing |
| `bridge-cli` | CLI seams (scratch default, fail-closed errors, exit contract, worktree boundary guard) |
| `dispatch-seam` | hermes-chat model boundary (argv contract, retries, votes, environment survey, tier discipline, debug capture) |
| `outer-loop` | project drain (resume, re-attempt caps, PLAN refusal) |
| `scout-pipeline` | scout → build gating and dirty-baseline/scrub handling |

See `TESTING.md` for the full input → expected-output contracts per group, the scoped
mutant rule, and the merge smoke set.
