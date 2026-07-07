# devloop — testing

devloop is the sole SDLC path (legacy retired 2026-07-01), so the tests are held to a high
bar: deterministic, fast, and **proven non-vacuous** by mutation testing. Two entry points:
**tiers** (how much it costs) and the **suite index** (what it validates).

## Tiers (the staged ladder — start here)

One entry point, `tests/tiers.py <tier>`, fastest first. Cost + signal both grow as you climb.
No new framework: the real-model tests are env-gated (`DEVLOOP_RUN_REAL`), so `fast` excludes
them for free.

| Tier | What | ~Time | LLM? | When |
|---|---|---|---|---|
| `fast` | the WHOLE deterministic suite (`pytest tests/`) | ~10s | No | every change |
| `smoke` | one tiny `add(a,b)` build **end-to-end** through the real v1 loop, independently corroborated | ~1-2m | Yes (1) | quick "does the whole loop still work" gut-check |
| `mutants` | OPTIONAL **extended-testing** mutation guard — every registered mutant must be KILLED (the current total is ALWAYS `len(mutants.MUTANTS)` — never trust a written-down count) | ~5-6m (killer-first ordering; grows with the roster) | No | ON DEMAND / EXTENDED — not the default loop; **recommended (not enforced) before a merge to main** |
| `spike` | QUICK real-engine go-check: `spike/tasks_quick.jsonl` (1 modify + 1 vague, ×1) — full spine incl. frozen-tests + regression + independent suite check; GO iff **0 false-completes** | ~5m | Yes (2) | the routine "is the engine still safe" check |
| `spike-full` | COMPREHENSIVE suite: `spike/tasks_extended.jsonl` (12 tasks × 3) | ~2-3h | Yes | ON DEMAND, run detached — before big releases / after major engine changes |

Named suites have two depths: smoke/default (`tiers.py suite <group>`) runs only that group's
tests and is the fast per-iteration default; full (`tiers.py suite <group> full`) runs those tests
plus only that group's mutation guard. Global `tiers.py full` is the complete seal: `fast` plus
the full mutation guard across every registered mutant.

```bash
# in-container, under uv (so pytest is importable):
uv run --with pytest python3 tests/tiers.py fast
uv run --with pytest python3 tests/tiers.py all         # fast -> smoke (mutants/spike stay opt-in)
uv run --with pytest python3 tests/tiers.py full        # fast -> full mutation guard (complete seal)
uv run --with pytest python3 tests/tiers.py suite       # list the validation groups below
uv run --with pytest python3 tests/tiers.py suite loop-spine   # run ONE group
uv run --with pytest python3 tests/tiers.py suite loop-spine full  # group tests + scoped mutants
```

From the host, prefix with `docker exec hermes bash -lc '…'`. Every `tests/test_*.py` also runs
dependency-free (`python3 tests/test_x.py`) — no pytest, no conftest.

## The suite index (what validates what)

`fast` sliced into named groups. The group → file mapping lives ONLY in `tests/tiers.py`
(`SUITES`); `tests/test_smoke.py` pins that the groups partition `mutants.TEST_FILES` exactly,
so this index cannot silently drift. Each row below is a representative INPUT → EXPECTED OUTPUT
contract the group enforces (the tests pin many more).

### 1. `fail-closed-kernel` — every refusal path that guards COMPLETE
| Input | Expected output |
|---|---|
| charter with an empty/`id`-less DoD | `stop_condition` refuses; ambiguity gate → HUMAN_REVIEW |
| NaN/±Inf confidence, or an EMPTY assumptions list | ambiguity gate → HUMAN_REVIEW (never auto-PROCEED; empty-assumptions over-route kept by design) |
| "make it faster" with no number in the request | vague_goal_gate → HUMAN_REVIEW ("no measurable target") |
| criterion quoting a number the request never stated (incl. a unit-converted one: 200 ms → 0.2) | vague_goal_gate → HUMAN_REVIEW (fabricated benchmark) |
| spike run where COMPLETE lacks green evidence, or the independent suite re-run is red | `analyze` flags a **false_complete** → GO bar fails |
| coverage + trusted judges + passing evidence + green suite | the ONE path to COMPLETE |

### 2. `evidence-state` — real exit codes + persistence honesty
| Input | Expected output |
|---|---|
| verify command exits 0 | Evidence `passed=True` |
| timeout / exit≠0 / empty command / `all_passing([])` | `passed=False` / False (fail-closed) |
| torn-write (partial JSON) checkpoint | `load_checkpoint` → None, never a crash or a resume |

### 3. `design-oracle` — structured spec → rendered pytest
| Input | Expected output |
|---|---|
| malformed spec entry / non-identifier name (injection) | entry SKIPPED → coverage fails → HUMAN_REVIEW |
| valid spec | canonical pytest emitted into a PER-RUN oracle file (`test_devloop_dod_<slug>.py` — re-runs accumulate, concurrent runs never collide); coverage DERIVED from real `pytest --collect-only` (a designer cannot fabricate it) |
| spec with no mocks/raises | oracle header imports NOTHING unused (F401-clean for strict-lint target repos); mocks/raises render their imports |
| pytest unavailable during collection | RuntimeError → runner routes HUMAN_REVIEW |

### 4. `loop-spine` — run_v1 mechanics
| Input | Expected output |
|---|---|
| coder edits/deletes a frozen test file | frozen-tests gate: originals RESTORED (self-heal), rebuild charged, forged-green blocked |
| coder writes a SyntaxError file | lint gate blocks the pass BEFORE evidence; persistent breakage → HUMAN_REVIEW |
| coder process errors / no-op with red evidence | dispatch-error fast route → HUMAN_REVIEW (no budget burn) |
| persistent red | back-off caps: 3 rebuilds × 3 replans → HUMAN_REVIEW (9 evidence runs, never runaway) |
| exhaustion + RED evidence + BOTH auditors say "test wrong" | ONE judged **test repair**: designer regenerates, coverage+judges re-gate, snapshot re-pins, fresh budget; a still-wrong repair → HUMAN_REVIEW (never a second repair) |
| up-front judge distrust (escalate/dissent on a criterion) | the same ONE regeneration budget spends on an **up-front oracle retry** (fresh design + full re-gate) before HUMAN_REVIEW — one flaky judge vote no longer wastes the run |
| exhaustion + auditor dissent / green evidence / crashed auditor | oracle KEPT; HUMAN_REVIEW with the audit verdict in the reason |
| would-be-COMPLETE + UNANIMOUS overfit indictment | the one regeneration budget spends on a green-side oracle repair (run-3 specimen: coded-around wrong tests); failed re-gate → HUMAN_REVIEW, never a COMPLETE on an indicted oracle |
| would-be-COMPLETE + SPLIT overfit vote | COMPLETE proceeds; the flag rides grounding as a non-blocking ⚠ advisory; the budget is NOT spent |
| COMPLETE + scope auditor says scratch | file pruned, FULL verification re-runs on the pruned tree; red → every file restored byte-identical; PROTECTED files (oracle/.gitignore/evidence targets) never reach the auditor; crashed auditor → deliverable (fail-closed) |
| COMPLETE | ships the **grounding report** (criterion → tests → judge votes → passing evidence) in result + trace |
| HUMAN_REVIEW (back-off / test-fault) | ships the PARTIAL grounding chain (grounded=False; ✗ rows name the unproven promises) — failed runs carry full diagnosis |
| any run | trace order pin: `coverage`/`judge`/`frozen_tests` strictly precede the first `implement` (tests gate the code, never retrofit) |
| any run | run_dir holds the inspection bundle: charter / design_spec (intent→test map) / rendered_tests (the oracle as judged) / judge_verdicts / attempts.jsonl / grounding |
| `max_passes` exhausted without a decision | **NO_TERMINATION** (bug sentinel; never COMPLETE) |
| any trace | `trace_view.render` shows EVERY event; unknown events fall through visibly |

### 5. `runner-pipeline` — the per-task pipeline
| Input | Expected output |
|---|---|
| vague request | HUMAN_REVIEW **before** design, marked `retryable: False` (deterministic block) |
| low-confidence charter | HUMAN_REVIEW, retryable (a re-drafted charter can differ) |
| non-Python request (designer collects `{}`) | coverage gate → HUMAN_REVIEW; implement/judges never fire |
| engine exception mid-run (charter crash, judge crash, Ctrl-C) | **crash-finalize**: work committed on `devloop/<name>` (kept iff real work), checkout removed, error re-raised — no leaks |
| CODER == DESIGNER (model collision) | RuntimeError BEFORE the worktree is created |

### 6. `worktree-merge` — isolation + fail-safe auto-merge + pre-merge sync
| Input | Expected output |
|---|---|
| COMPLETE, target tip == run base | fast path: SQUASH auto-merge — ONE `devloop: squash-merge` commit LANDED via `git commit-tree` (parented on the verified tip) + atomic `git update-ref <ref> <new> <tip>` ref-CAS; no worktree/merge-commit noise; branch `-D`'d only after the CAS landed (or a provably empty delta bypasses the CAS); a failed squash/commit-tree hard-resets the tree clean and keeps the branch; NO re-verify |
| target ADVANCED past the run base | **pre-merge sync**: target merged INTO the run branch in a throwaway checkout; whole-suite regression re-run on the COMBINED tree; only green merges |
| advanced + no `regression_check` (stray caller) | merge REFUSED fail-closed ("sync unavailable") |
| red combined tree | refused; sync/fix commits STRIPPED (branch = the run's verified work exactly) |
| sync conflict, no/declining resolver | `merge --abort` (never a conflicted tree); branch kept at its verified SHA |
| sync conflict + LLM resolver | resolver edits; CODE verifies (no markers, index clean, commit ok); test-file conflicts NEVER reach the resolver; resolver edits to other tests are RESTORED + refused |
| red combination + LLM fixer | ONE bounded fix; test edits restored; the regression gate re-runs and DECIDES |
| dirty target / detached HEAD | merge REFUSED; branch kept for review |
| checkout SWITCHED branches mid-run | merge REFUSED (`expected_branch` guard vs the recorded `start_branch`); branch kept |
| concurrent devloop merge OR foreign write moves HEAD off the verified tip | landing is LOCK-FREE via git's atomic ref-CAS (`update-ref <ref> <new> <tip>` advances only if the ref still equals `tip`); a move makes the CAS refuse (`tip-moved`) → branch kept for review, NO unverified combination lands. Proven by the deterministic injection test + the foreign-write test |
| FOREIGN git op holds index.lock | final merge retries (bounded, index.lock ONLY); other failures never retry |
| `DEVLOOP_KEEP_WORKTREE=1` | finalize keeps the exact checkout for post-mortems; commit/branch semantics unchanged |
| `DEVLOOP_GIT_NAME/EMAIL` set | devloop commits/merges carry that identity (defaults unchanged) |
| empty run (no artifact) | checkout AND branch removed (nothing accretes) |
| default checkout root | IN-REPO `<repo>/.worktrees/` — invisible to the repo (local exclude now; `.gitignore` seeded via the run's contentful commit; empty runs stay branchless) |

### 7. `bridge-cli` — the seams
| Input | Expected output |
|---|---|
| chat/CLI call with NO repo (or `repo=None`) | **SCRATCH workspace** — never the caller's cwd (the ~/.hermes data-repo hazard) |
| `--repo` = non-git dir / subdir of an enclosing repo / the write-safe root | CLI refuses, exit 2, engine never runs |
| engine raises anything | `call_guarded` → "devloop FAILED CLOSED", error set, exit 1 (same result keys as a normal run) |
| HUMAN_REVIEW with blocking questions | needs-input outcome (NOT an error), exit 2, re-run line printed |
| exit 0 | IFF error None ∧ terminal COMPLETE ∧ (merged ∨ `--keep-branch` with the branch ACTUALLY kept) |
| `--keep-branch` COMPLETE | merge skipped, verified branch survives, summary prints the manual merge command; no branch kept → exit 1 (never a hollow 0) |
| COMPLETE (any) | the WHOLE run_dir is copied to `devloop-traces/<name>/` (trace + every stage artifact), not just the trace |
| `DEVLOOP_ENABLED=0` (pipeline seam only) | intentional single-dispatch fallback |
| an agent phase escapes its worktree and touches the target repo's main working tree (live-caught 2026-07-03) | worktree-boundary guard: paths newly dirty across the run are restored (tracked → HEAD, untracked → deleted), pre-existing user dirt untouched; breach named in content + `devloop_result.boundary_restored` |

### 8. `dispatch-seam` — the hermes-chat model boundary
| Input | Expected output |
|---|---|
| any phase dispatch | argv contract `chat -q <prompt> -m <model> -Q --yolo [-t <toolsets>]`; subprocess timeout ≥ the 1800s floor, never unbounded |
| noisy reply with fenced JSON | parsed charter (ids assigned); unparseable/empty ×retries → empty DoD → HUMAN_REVIEW |
| judge/advisor votes | strict MAJORITY of 3 (a single flaky vote decides nothing) |
| charter/refine dispatch with a non-empty target repo | prompt carries the EXISTING ENVIRONMENT survey (modules + public symbols; align-and-reuse, never overriding the request); greenfield → no survey |
| charter tier field | each criterion tier-scoped unit\|integration (unknown → unit fail-safe); the survey REQUIRES an integration-tier criterion when modifying existing code; the designer prompt carries the mock-isolation (unit) / no-mocks (integration) discipline; tier rides design_spec.json, grounding, and the --chain view |
| coder process exit ≠ 0 | surfaced as `exit_code` → loop dispatch-error route |
| coder spawns a venv/caches | junk-pruned from the change snapshot: lint never scans third-party files; a junk-only attempt counts as a NO-OP |
| coder prompt | carries harness etiquette (no internal refs in shipped code; no venvs) |
| `DEVLOOP_DEBUG=1` | every model call's full prompt + raw reply captured under `<run_dir>/dispatch/`; OFF captures nothing |
| judge prompt | REQUIRES recomputing each asserted expected value from the criterion's semantics (wrong value = wrong test = NO) |
| coder prompt | never special-case code to satisfy a test contradicting the criterion (let it fail into the repair path); no scratch files left in the tree |
| overfit/scope auditors | majority-vote, fail-closed (False / deliverable); the loop enforces unanimity and re-verification in code |

### 9. `outer-loop` — the project drain (live caller: the scout pipeline)
| Input | Expected output |
|---|---|
| N purposes, all COMPLETE | drained; one lesson per attempt |
| non-COMPLETE with a valid DoD | re-attempt with lessons folded in, capped at `PROJECT_MAX_ATTEMPTS` → BLOCKED |
| blocking question / empty DoD / `retryable: False` | ESCALATE in ONE attempt (never burns the cap) |
| lessons containing "faster"/counts | vague gate does NOT trip (lessons stripped before gating) |
| re-run over a leftover `devloop/*` branch | attempt name suffixed `-r2` — the drain never aborts |
| existing PLAN.json with matching schema + ordered root purposes | genuine resume; completed items stay complete and in-progress items recover to pending |
| corrupt/wrong-schema PLAN.json or root-purpose mismatch | refuse closed with non-empty `blocked`; never reseed over corrupt state or blindly resume foreign state |

### 10. `scout-pipeline` — relentless-solve as pathfinder (scout.py + devloop_pipeline_cli)
| Input | Expected output |
|---|---|
| any scout run | subprocess seam only (`HERMES_HOME`, default `~/.hermes`: env ladder → deployed → mirror), `--capability read`, `--answer-cwd` pinned to the target repo; relentless missing everywhere → structured "scout unavailable", never a crash |
| scout outcome `success` + valid `scout-steps.json` | steps → `project.run_project` drain; each purpose carries the step's `Success criterion:` |
| `success`/`information-dry` + `no_path` artifact | honored "no viable path" — reported, exit 0, nothing built |
| `information-dry`/`max-cycles`/`wallclock` with a step list (or a capped `no_path`) | UNCONCLUDED — finding surfaced for review, NEVER built, exit 1 |
| nonzero exit / rc 124 / missing / malformed / oversized / contradictory artifact | fail-closed scout failure (rc 124 names the resumable re-run), exit 2, nothing built |
| same request re-run | same hashed slug → relentless RESUMES (a prior artifact is the same request's finding by construction); `--fresh` clears the slug state first and refuses if deletion was ineffective |
| per-step devloop run | bridge lifecycle (finalize + auto-merge + trace); COMPLETE without a landed merge → `MERGE_DEGRADED` (re-attempt, never "achieved"); bridge forwards `retryable`+`charter` so escalation fidelity survives the seam |
| target repo with uncommitted changes | structured refusal BEFORE any scout call (exit 2) — the pipeline merges into this repo and the scrub needs a clean baseline |
| scout modifies the target repo (agent overreach — live-caught) | debris hard-restored to the clean baseline, breach named in result+report, the finding still usable; a FAILED restore fails the scout closed (repo state unknown → nothing built) |
| any pipeline run | bundle at `devloop-traces/pipeline-<slug>/` (scout-steps.json + report.md); drain state at `devloop-pipelines/<slug>/` |
| CLI exit | 0 IFF every step built AND merged, or a clean `--scout-only`/concluded-no-path stop; 1 = blocked/pending/unconcluded; 2 = usage/scout failure |

## Invariant for changes

Any change to a kernel module must keep `tiers.py fast` green (count evolves — read pytest's
summary). Every new guard gets a **direct unit test** in the fast suite; that is the default bar.

The mutation guard is the OPTIONAL **extended** tier (user decision 2026-07-01; scoped 2026-07-03).
A killing mutant in `tests/mutants.py` is REQUIRED only for a **critical-surface** guard, and
OPTIONAL for routine ones. The one **decision test**: a guard is critical iff *removing it would
let a run reach a `COMPLETE` / merged / exit-0 outcome it should not*.
- **Critical (mutant required)** — the 0-false-completes surface: merge landing & honesty
  (`merge_branch`, the bridge auto-merge/`committed` gate, the COMPLETE→MERGE_DEGRADED downgrade,
  branch-leak reporting); scout→build gating (`run_scout` success gate, `run_pipeline`
  buildable / dirty-repo precondition / scrub-fail, `load_steps` steps-XOR-`no_path` + `MAX_STEPS`);
  the CLI exit contract (0/1/2); drain honesty (`classify_outcome`, the PLAN-refusal); and the
  loop's completion gates (vague-goal, coverage, judge-trust, frozen-tests, regression,
  overfit-audit, commit-scope).
- **Routine (mutant optional; the unit test is the proof)** — shape/type guards (`load_steps`
  `isinstance`/type checks), exclude idempotence, `_safe_changed` telemetry, worktree
  seed/bookkeeping, slug formatting, report rendering. Gutting one of these crashes or is caught
  downstream — it never yields a silent false success.

When the guard runs (extended, before a main-merge), it must report **0 survived / 0 stale**. The
deterministic suite is fast because the model-dispatch points are injected fakes — `mutants.py` is
the extended proof that fast ≠ vacuous *on the surface where a vacuous test would let wrong code ship*.

### Improvement-loop cadence + the merge smoke set

When iterating on devloop itself (see SKILL.md's "Improving devloop"), the PER-ITERATION cadence
is deliberately cheap: run **only the iteration's targeted test + the merge smoke set** — NOT the
full suite, NOT the mutation guard. Those run ONCE, at the seal. The **merge smoke set** (the
fast, high-signal core of the `worktree-merge` group — the ref-CAS landing contract) is:

- `test_merge_branch_happy_fast_path_merges_deletes_branch` — fast-path squash lands, branch gone
- `test_merge_branch_cas_landing_parents_tip_single_parent_and_clean_tree` — fast-path CAS topology + clean tree
- `test_merge_branch_cas_landing_sync_path_leaves_clean_tree` — sync-path CAS reconciles clean
- `test_merge_branch_refuses_when_foreign_write_moves_head_during_verify` — foreign HEAD move → CAS refuses
- `test_merge_branch_cas_refuses_when_head_moves_after_precheck_before_ref_update` — deterministic proof the CAS closes the residual TOCTOU window
- `test_merge_branch_real_squash_conflict_resets_clean_and_keeps_branch` — a genuine conflicted squash resets clean, branch kept

Run it in-container: `uv run --with pytest python3 tests/tiers.py suite worktree-merge` (superset)
or `... -m pytest tests/test_worktree_more.py -k merge_branch`.

**One cadence exception (learned 2026-07-04):** an iteration that changes a *guarded code line*
or edits `tests/mutants.py` MUST also run the mutant-registry integrity check
(`tests/test_mutants_registry.py`, or `python3 tests/mutants.py` which checks the registry before
running) — a landing-mechanism change can silently STALE a mutant whose `old` text you removed,
and the unit suite alone will not catch it (it surfaced two iterations late during the ref-CAS
sprint). Registry integrity is cheap; run it whenever the guarded surface moves.
