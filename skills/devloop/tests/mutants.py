#!/usr/bin/env python3
"""Mutation guard for the devloop kernel.

Injects deliberate bugs into a COPY of the skill and confirms the test suite KILLS each
one (fails). A SURVIVED mutant means a vacuous/missing test.

OPTIONAL / EXTENDED tier (user decision 2026-07-01; scoped 2026-07-03): NOT part of the general
suite and not a routine pre-commit gate — run it detached when you want the non-vacuity proof
(recommended before a merge to main). REGISTER a killing mutant for every new CRITICAL-SURFACE
guard (false-complete / merge / exit-contract — see TESTING.md's decision test: "would removing
it allow a false COMPLETE/merged/exit-0?"); routine shape/type/telemetry guards rely on their
direct unit test instead. ~5-6 min (killer-first test ordering; grows with the roster); the run
COPIES this tree once and edits in place per mutant, so do not edit source files while it runs.

    python3 tests/mutants.py        # exit 0 iff every mutant is killed
    python3 tests/mutants.py --files worktree.py  # run only one source file's mutants

NOT named test_*/*_test so pytest does NOT collect it; the run is guarded by __main__.
Portable: derives the skill dir from this file, so it works on host or in-container.
"""
import os
import shutil
import subprocess
import sys
import tempfile

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the devloop dir
PY = sys.executable

# (file, exact old substring, mutated new substring, description)
MUTANTS = [
    ("gate.py", "if not coverage_ok:", "if False:",
     "stop_condition: drop the DoD coverage check"),
    ("gate.py", 'if any(not c.get("id") for c in dod):', "if False:",
     "stop_condition: stop fail-closing on id-less criteria"),
    ("gate.py", "if not vs:", "if False:",
     "_judges_ok: stop failing on a criterion with no judge verdict"),
    ("gate.py", 'if not any(v.get("encodes") is True and not v.get("escalate") for v in vs):',
     "if False:",
     "_judges_ok: stop requiring a trusted (encodes & !escalate) test per criterion"),
    ("gate.py", 'affirm_seats = {v.get("seat") for v in verdicts if v.get("affirm") is True and v.get("seat")}',
     "affirm_seats = seats_present",
     "council_gate: count seats PRESENT instead of AFFIRMED"),
    ("gate.py", "and not isinstance(c, bool) and math.isfinite(c)", "and not isinstance(c, bool)",
     "ambiguity_gate: drop the isfinite guard (NaN auto-PROCEEDs)"),
    ("gate.py", "low = min(confs) if confs else 0.0", "low = min(confs) if confs else 1.0",
     "ambiguity_gate: empty assumptions fail OPEN"),
    ("gate.py", "if replans >= config.MAX_REPLANS:", "if False:",
     "backoff_exhausted: never route to HUMAN_REVIEW (no termination)"),
    ("evidence.py", "if not required_ids:", "if required_ids is None:",
     "all_passing: empty required set passes vacuously"),
    ("evidence.py", "return all(cid in ledger and _passed(ledger[cid]) for cid in required_ids)",
     "return any(cid in ledger and _passed(ledger[cid]) for cid in required_ids)",
     "all_passing: ANY instead of ALL criteria"),
    ("dod_oracle.py", "uncovered = [cid for cid in required if cid not in covered]", "uncovered = []",
     "check_structural_coverage: always report full coverage"),
    ("state.py", 'CHARTER_MAY_BE_EMPTY = frozenset({"assumptions", "open_questions"})',
     "CHARTER_MAY_BE_EMPTY = frozenset()",
     "validate_charter: reject valid empty assumptions/open_questions"),
    ("spike/run_spike.py", "gated_stop_ok = (not reported_complete) or evidence_green",
     "gated_stop_ok = True",
     "spike.analyze: accept a forged COMPLETE (no green evidence)"),
    ("spike/run_spike.py", "go = runs_pass and enough_tasks and enough_runs", "go = runs_pass",
     "evaluate_bar: ignore the >=5 tasks / >=2 runs requirement"),
    ("project.py", 'if item["attempt_n"] < max_attempts:',
     "if True:",
     "project loop: never stop enqueuing re-attempts (no termination)"),
    ("project.py", 'if terminal == "COMPLETE":\n        return "achieved"',
     'if True:\n        return "achieved"',
     "project classify_outcome: treat any terminal as achieved (forged success)"),
    ("project.py", "if terminal == \"HUMAN_REVIEW\" and (_blocked_on_ambiguity(charter) or not charter.get(\"dod\")):",
     "if terminal == \"HUMAN_REVIEW\" and (False or not charter.get(\"dod\")):",
     "project: re-attempt an ambiguity-blocked purpose, burning the cap on an unanswerable question"),
    ("project.py", "or not charter.get(\"dod\")", "or False",
     "project: re-attempt an empty-DoD charter (planner produced no spec) instead of escalating"),
    ("project.py", 'base = f"{item[\'id\']}-a{len(item[\'attempts\']) + 1}"',
     'base = item["id"]',
     "project: reuse the worktree name across attempts (create_worktree collision)"),
    ("project.py", 'while _branch_exists(repo, f"devloop/{name}"):', 'while False:',
     "project: leftover-branch probe dropped — a re-run over a kept devloop/* branch aborts the whole drain"),
    ("project.py", 'if terminal == "HUMAN_REVIEW" and (result or {}).get("retryable") is False:', 'if False:',
     "project: a non-retryable (deterministic-gate) HUMAN_REVIEW re-attempts, burning the cap on a reproducible block"),
    ('runner.py', 'goal_text = request.split(config.LESSONS_HEADER, 1)[0]', 'goal_text = request',
     "runner: folded lessons reach the vague-goal gate again (every project re-attempt trips a marker)"),
    ('runner.py', '"retryable": not vague}', '"retryable": True}',
     "runner: a deterministic vague-goal block reads as retryable (the project loop burns its cap on it)"),
    ("state.py", 'f.write(line + "\\n")', 'f.write("")',
     "append_learning: do not actually write the lesson (lessons lost)"),
    ("testgen.py", "return {nid: cid for nid, cid in planned.items() if _covered(nid, collected)}",
     "return {nid: cid for nid, cid in planned.items()}",
     "collect_spec_map: trust the spec's claimed coverage without real pytest collection"),
    ("render.py", "if has_expected == has_raises:", "if False:",
     "render: accept a case with both/neither expected and raises (ambiguous oracle)"),
    ("render.py", 'return [f"assert {call}({callargs}) == {rhs}"]', 'return ["assert True"]',
     "render: emit a vacuous assertion instead of the real one"),
    ("render.py", 'return [f"with pytest.raises({exc}):", f"    {call}({callargs})"]',
     'return [f"{call}({callargs})"]',
     "render: a raises-case without pytest.raises (a bare call never fails)"),
    ("render.py", "funcs[0].name == fn", "True",
     "render: raw escape-hatch test name not pinned to test_<cid>"),
    ("spike/run_real_spike.py",
     'false_complete = (expect_hr and completed) or (completed and bool(run.get("regression_red")))',
     "false_complete = False",
     "real-spike analyze: stop detecting an ambiguous-task COMPLETE as a false-complete (fail-open)"),
    ("spike/run_real_spike.py",
     'false_complete = (expect_hr and completed) or (completed and bool(run.get("regression_red")))',
     "false_complete = expect_hr and completed",
     "real-spike analyze: a COMPLETE that broke the pre-existing suite no longer counts as a false-complete"),
    ("spike/run_real_spike.py", "no_false_completes = not any(r.get(\"false_complete\") for r in results)",
     "no_false_completes = True",
     "real-spike evaluate_bar: drop the false-complete veto (a forged COMPLETE could still GO)"),
    ("spike/run_real_spike.py", "go = no_false_completes and enough_tasks and enough_runs",
     "go = no_false_completes",
     "real-spike evaluate_bar: ignore the >=5 tasks / >=2 runs coverage requirement"),
    # ---- coverage buildout (2026-06-30): 54 mutants the prior suite let SURVIVE, now killed by the
    # ---- per-source test_<module>.py / test_<module>_more.py suites (empirically probe-confirmed). ----
    ('devloop_bridge.py', '"devloop_result": {"terminal": "HUMAN_REVIEW", "branch": None, "worktree": None,',
     '"devloop_result": {"terminal": "COMPLETE", "branch": None, "worktree": None,',
     'failure_result: a failed-closed bridge result must be HUMAN_REVIEW, never read as success'),
    ('devloop_bridge.py', 'return failure_result(f"devloop runtime error: {type(e).__name__}: {e}")',
     'raise',
     'call_guarded: swallow-and-fail-closed on a devloop runtime exception (mutant re-raises into pipeline.py)'),
    ('dispatch.py', """        assump = "\\n".join(f"- {a.get('text', '')}" for a in charter.get("assumptions", [])
                           if isinstance(a, dict) and a.get("text"))""",
     '        assump = ""',
     'implementer_via_ask: cut the assumptions plumb-through (recorded reuse preferences never reach the coder)'),
    ('worktree.py', 'untracked = _git(wt, "ls-files", "--others", check=False).stdout.splitlines()',
     'untracked = []',
     'changed_files: back to gitignore-blind (a fail-closed repo .gitignore hides every created file)'),
    ('worktree.py', 'if changed:\n            _git(path, "add", "-f", "--", *changed, check=False)',
     'if False:\n            _git(path, "add", "-f", "--", *changed, check=False)',
     'finalize: skip the commit (work destroyed — checkout removed AND contentless branch deleted)'),
    ('devloop_bridge.py', '"error": None if terminal in ("COMPLETE", "HUMAN_REVIEW")',
     '"error": None if terminal in ("COMPLETE",)',
     'bridge: HUMAN_REVIEW regresses to an error outcome instead of needs-your-input'),
    ('devloop_bridge.py', '"needs_human": needs_human, "open_questions": blocking,',
     '"needs_human": False, "open_questions": blocking,',
     'bridge: the needs_human affordance flag is dropped'),
    ('dispatch.py', 'return max(DISPATCH_TIMEOUT_S, int(os.environ.get("DEVLOOP_DISPATCH_TIMEOUT_S", "0") or 0))',
     'return min(DISPATCH_TIMEOUT_S, int(os.environ.get("DEVLOOP_DISPATCH_TIMEOUT_S", "0") or 0))',
     '_dispatch_timeout: min instead of max (an env value SHORTENS every model call — policy violation)'),
    ('trace_view.py', 'out.append(f"{p}  {s or \'?\'}: {compact}")',
     'pass',
     'trace_view: silently drop unknown event types (the old bug, resurrected)'),
    ('loop.py', 'dod=[{k: c.get(k) for k in ("id", "criterion", "verify_intent", "tier")}\n             for c in charter.get("dod", []) if isinstance(c, dict)],',
     'dod=[],',
     '_charter_event: drop the DoD text from the trace (false-completes undiagnosable post-hoc)'),
    ('loop.py', 'if viol:', 'if False:',
     'frozen-tests gate disabled (a coder can delete/rewrite test files and still COMPLETE)'),
    ('loop.py', 'missing = [p for p in frozen if p not in now]', 'missing = []',
     'frozen-tests: deleting a test file no longer counts (delete-a-red-test turns the suite green)'),
    ('loop.py', 'changed = [p for p in frozen if p in now and now[p] != frozen[p]]', 'changed = []',
     'frozen-tests: rewriting a judged test no longer counts (forged green vs a gutted oracle)'),
    ('loop.py', 'restored = _frozen_restore(cwd, frozen_tests)', 'restored = []',
     'frozen-tests: drop the self-heal (a once-misbehaving coder wastes the whole run instead of one rebuild)'),
    # ---- prompt-callable completion (2026-07-01): auto-merge + CLI contract ----
    ('devloop_bridge.py',
     'if (terminal == "COMPLETE" and fin.get("branch_kept") and fin.get("committed")\n'
     '            and not keep_branch):',
     'if False:',
     'bridge: auto-merge skipped — a COMPLETE run never lands its code'),
    ('worktree.py', 'if _git(repo, "status", "--porcelain", check=False).stdout.strip():',
     'if False:',
     'merge_branch: dirty-target guard dropped — merge attempted over uncommitted work'),
    # ---- pre-merge sync + LLM resolution (user decisions 2026-07-02) ----
    ('worktree.py', 'if not base or tip != base:', 'if False:',
     'merge_branch: advanced-target detection dropped — an advanced target merges with NO combined-tree verification'),
    ('worktree.py', 'if regression_check is None:', 'if False:',
     'merge_branch: fail-closed missing-check path dropped — a stray caller merges an unverified combination'),
    ('worktree.py', 'if m.returncode != 0:', 'if False:',
     '_sync_and_verify: sync-conflict check dropped — a conflicted sync proceeds as if merged'),
    ('worktree.py', '_git(path, "reset", "--hard", pre, check=False)', 'pass',
     '_sync_and_verify: reset-on-red dropped — the review branch keeps unverified sync/fix commits'),
    ('worktree.py', 'if any(_TEST_FILE_RE.search(p.replace(os.sep, "/")) for p in conflicted):', 'if False:',
     '_resolve_conflicts: test-file conflict guard dropped — the LLM resolver may rewrite the oracle'),
    ('worktree.py', 'if "<<<<<<<" in body or ">>>>>>>" in body:', 'if False:',
     '_resolve_conflicts: marker guard dropped — a lying resolver commits conflict markers'),
    ('worktree.py', 'if _restore_test_files(path, frozen):', 'if False:',
     "_resolve_conflicts: test-restore guard dropped — the resolver's test edits survive toward the merge"),
    ('worktree.py', "ok, why = regression_check(path)   # the GATE decides, not the fixer's claim",
     'ok, why = True, ""',
     "_sync_and_verify: fixer re-check dropped — the LLM's claim merges without the gate re-running"),
    ('worktree.py', '_restore_test_files(path, frozen)\n                _git(path, "add", "-A", check=False)',
     '_git(path, "add", "-A", check=False)',
     "_sync_and_verify: fixer test-restore dropped — the fixer's test edits get committed"),
    ('worktree.py', 'with open(excl, "a") as f:\n                f.write(f"\\n{_WT_DIRNAME}/\\n")',
     'pass',
     '_ensure_locally_ignored: exclude write dropped — the in-repo checkout dirties the repo (dirty-guard blocks every auto-merge)'),
    ('worktree.py', 'if changed and wt_info.get("seed_ignore"):', 'if False:',
     'finalize: .gitignore seed dropped — the user-required tracked ignore entry never lands'),
    ('worktree.py', 'return ignored', 'return not ignored',
     '_ensure_locally_ignored: inverted — fresh repos never get the tracked-.gitignore seed'),
    ('devloop_bridge.py', 'base=wt.get("base"),', 'base=None,',
     'bridge: fork-point not threaded — every merge takes the conservative sync path (fast path dead)'),
    # ---- judged mid-run test repair (user decision 2026-07-02) ----
    ('loop.py', 'audit_b is not None \\\n                    and not st.get("repair_used"):',
     'audit_b is not None \\\n                    and False:',
     'run_v1: repair trigger dropped — a wrong oracle always surrenders to a human'),
    ('loop.py', 'if untrusted and redesign is not None and not st.get("repair_used"):', 'if False:',
     'run_v1: up-front oracle retry dropped — one flaky judge dissent wastes the whole run'),
    ('loop.py', 'st["repair_used"] = True              # burned BEFORE the attempt: one repair, ever',
     'pass              # burned BEFORE the attempt: one repair, ever',
     '_attempt_test_repair: at-most-once bound dropped — a still-wrong repaired oracle repairs forever'),
    ('loop.py', 'state.on_repair(st)                        # ONE fresh budget; repair_used pins it',
     'pass                        # ONE fresh budget; repair_used pins it',
     'run_v1: post-repair budget reset dropped — the repaired oracle inherits an exhausted budget'),
    ('loop.py', 'frozen_tests = rep["frozen"]               # the repaired oracle is re-frozen',
     'pass               # the repaired oracle is re-frozen',
     'run_v1: repaired oracle not re-frozen — the self-heal restores the OLD wrong tests over it'),
    ('loop.py', 'cov_ok, uncovered = dod_oracle.check_structural_coverage(charter["dod"], new_map)',
     'cov_ok, uncovered = True, []',
     '_attempt_test_repair: coverage re-gate skipped — an uncovering repair continues the loop'),
    ('loop.py', 'untrusted = gate.untrusted_criteria(charter, verdicts)',
     'untrusted = []',
     '_attempt_test_repair: judge re-gate skipped — judge-rejected repaired tests continue the loop'),
    ('gate.py', 'is_wrong = len(votes) == 2 and all(votes)', 'is_wrong = any(votes)',
     'audit_tests: unanimity weakened to any-vote — one flaky auditor overturns the oracle'),
    ('gate.py', 'if ev is None or _evidence._passed(ev):', 'if ev is None:',
     'audit_tests: green-evidence skip dropped — working oracles get audited (and can be overturned)'),
    ('gate.py', 'except Exception:   # noqa: BLE001 — a crashed auditor never indicts the oracle\n                votes.append(False)',
     'except Exception:   # noqa: BLE001 — a crashed auditor never indicts the oracle\n                votes.append(True)',
     'audit_tests: a crashed auditor counts as an indictment (fail-open toward rewriting the oracle)'),
    # ---- environment-aware interpretation (user ask 2026-07-02) ----
    ('dispatch.py', '_chat(_CHARTER_PROMPT + request + _environment_survey(target_dir),',
     '_chat(_CHARTER_PROMPT + request,',
     'charter: environment survey dropped — interpretation is repo-blind again'),
    ('dispatch.py', '+ _environment_survey(target_dir))', '+ "")',
     'refiner: environment survey dropped from the refine prompt'),
    ('runner.py', 'make_charter = lambda req: dispatch.charter_via_ask(req, target_dir=target)  # noqa: E731',
     'make_charter = lambda req: dispatch.charter_via_ask(req, target_dir=None)  # noqa: E731',
     'runner: charter environment threading dropped (the survey never sees the checkout)'),
    # ---- end-of-run grounding: promise -> proof chain (user ask 2026-07-02) ----
    ('loop.py', '"grounding": grounding, "scope_dropped": scope_dropped}', '"grounding": None, "scope_dropped": scope_dropped}',
     'run_v1: grounding report dropped from the COMPLETE result (proof chain invisible)'),
    ('devloop_bridge.py', '"grounding": grounding,', '"grounding": None,',
     'bridge: grounding not threaded into devloop_result'),
    ('devloop_bridge.py', 'if grounding and grounding.get("criteria"):', 'if False:',
     'bridge: grounding dropped from the human summary (evidence never shown)'),
    ('scripts/devloop_cli.py', 'repo = br.SCRATCH          # NEVER implicit cwd (mutant-pinned)',
     'repo = None          # NEVER implicit cwd (mutant-pinned)',
     'devloop_cli: implicit cwd resurrected (cwd-if-git could target the ~/.hermes data repo)'),
    ('scripts/devloop_cli.py',
     'if res.get("error") is None and dr.get("terminal") == "COMPLETE" and (\n'
     '            dr.get("merged") or (args.keep_branch and dr.get("kept_branch"))):\n'
     '        return 0',
     'if True:\n        return 0',
     'devloop_cli: exit-code contract broken — a non-merged/non-COMPLETE run exits 0 (shell-boundary false-complete)'),
    ('scripts/devloop_cli.py',
     'dr.get("merged") or (args.keep_branch and dr.get("kept_branch"))',
     'dr.get("merged") or args.keep_branch',
     'devloop_cli: --keep-branch exits 0 even when NO branch was actually kept (hollow success)'),
    ('scripts/devloop_cli.py',
     'res = br.call_guarded(br.run_build, args.request, timeout=args.timeout, repo=repo,\n'
     '                              keep_branch=args.keep_branch)',
     'res = br.call_guarded(br.run_build, args.request, timeout=args.timeout, repo=repo,\n'
     '                              keep_branch=False)',
     'devloop_cli: --keep-branch never reaches the bridge (branch merged against the user request)'),
    ('devloop_bridge.py',
     'if (terminal == "COMPLETE" and fin.get("branch_kept") and fin.get("committed")\n'
     '            and not keep_branch):',
     'if (terminal == "COMPLETE" and fin.get("branch_kept") and fin.get("committed")):',
     'bridge: --keep-branch no longer skips the auto-merge (the kept-branch promise is broken)'),
    ('render.py', 'if "pytest." in body:', 'if True:',
     'render: unconditional pytest import resurrected -> F401 fails strict-lint target repos'),
    ('render.py', 'if "mock." in body:', 'if False:',
     'render: mock import dropped even when mocks are rendered -> the whole oracle NameErrors'),
    ('worktree.py', "os.environ.get('DEVLOOP_GIT_EMAIL', 'devloop@hermes')", "'devloop@hermes'",
     '_identity: DEVLOOP_GIT_EMAIL knob dropped (automation attribution unconfigurable)'),
    ('dispatch.py',
     '"ids (dod:cN), test expectations, or this loop in code or comments — write them as if the tests "',
     '"ids (dod:cN), or this loop in code or comments — write them as if the tests "',
     'coder prompt: harness-etiquette directive weakened (test expectations may be narrated in shipped code)'),
    ('dispatch.py',
     '"- NEVER overfit a wrong test: if a test asserts an expected value that CONTRADICTS the "',
     '""',
     'coder prompt: no-overfit rule gutted (wrong tests get silently special-cased green — the run-3 hack)'),
    ('dispatch.py',
     '"RECOMPUTE each asserted expected value from the CRITERION\'s plain semantics before "',
     '""',
     'judge prompt: value-recompute directive gutted (wrong-arithmetic tests judged trusted — the run-3 hack)'),
    ('loop.py', 'if (overfit_a is not None and overfit_b is not None and redesign is not None',
     'if (False and overfit_a is not None and overfit_b is not None and redesign is not None',
     'run_v1: green-side overfit audit trigger dropped (coded-around wrong oracles COMPLETE unchecked)'),
    ('loop.py', 'is_overfit = len(votes) == 2 and all(votes)', 'is_overfit = any(votes)',
     'overfit audit: unanimity weakened to any-vote (one flaky auditor YES spends the repair budget)'),
    ('loop.py', 'grounding["overfit_advisory"] = overfit_advisory', 'pass',
     'overfit audit: split-vote advisory dropped from the grounding chain'),
    ('loop.py',
     'st["repair_used"] = True   # the one regeneration, spent on the green-side indictment',
     'pass   # the one regeneration, spent on the green-side indictment',
     'overfit audit: indictment no longer spends the shared budget (second regeneration possible)'),
    ('loop.py', 'if not ok_rep:', 'if False:',
     'overfit audit: failed re-gate no longer routes HUMAN_REVIEW (completes on an indicted oracle)'),
    ('loop.py', 'and not st.get("repair_used") and not st.get("overfit_checked")):',
     'and not st.get("overfit_checked")):',
     'overfit audit: shared-budget guard dropped (green audit can double-spend after a red-side repair)'),
    ('loop.py', 'if scope_audit is not None and not st.get("scope_checked"):', 'if False:',
     'run_v1: commit-scope gate dropped (coder scratch merges into the target)'),
    ('loop.py', 'for p in [c for c in changed if c not in protected]:', 'for p in list(changed):',
     'commit scope: PROTECTED set dropped (the oracle test file can be classified scratch)'),
    ('loop.py', 'for p, content in snap.items():', 'for p, content in {}.items():',
     'commit scope: restore-on-red dropped (a wrong scratch call destroys a needed file)'),
    ('loop.py', 'ev2 = evidence.run(cid, verify_cmd_for(cid), cwd=cwd)',
     'ev2 = evidence.run(cid, ["true"], cwd=cwd)',
     'commit scope: post-prune per-criterion re-verify faked green'),
    ('loop.py', 'pruned_ok, why_red = gate.regression_gate(reg2)', 'pruned_ok, why_red = True, ""',
     'commit scope: post-prune whole-suite re-check faked green'),
    ('loop.py', 'v = "deliverable"   # fail-closed: wrong exclusion is destructive',
     'v = "scratch"   # fail-closed: wrong exclusion is destructive',
     'commit scope: crashed-auditor default inverted (everything becomes scratch)'),
    ('dispatch.py',
     '"- Do NOT create virtualenvs or install packages; run tests with the interpreter already available.\\n"',
     '""',
     'coder prompt: no-venv directive dropped (coder venvs waste every attempt walk/lint)'),
    ('devloop_bridge.py',
     'shutil.copytree(os.path.dirname(str(trace_path)), dest_dir, dirs_exist_ok=True)',
     'os.makedirs(dest_dir, exist_ok=True); shutil.copyfile(str(trace_path), os.path.join(dest_dir, "trace.jsonl"))',
     '_preserve_trace: bundle narrowed back to trace-only (stage artifacts die with the worktree)'),
    ('loop.py',
     '_persist(run_dir, "design_spec.json", _design_spec(charter, test_to_criterion, judge_verdicts))',
     'pass',
     'run_v1: design_spec.json (the intent->test mapping artifact) no longer persisted'),
    ('loop.py', '_persist(run_dir, "grounding.json", grounding)', 'pass',
     'run_v1: grounding.json no longer persisted to the inspection bundle'),
    ('loop.py', '\n    _persist_oracle(run_dir, frozen_tests)', '\n    pass',
     'run_v1: the frozen oracle (rendered_tests.json) no longer persisted'),
    ('dispatch.py', 'if os.environ.get("DEVLOOP_DEBUG") != "1":',
     'if os.environ.get("DEVLOOP_DEBUG") == "1":',
     '_capture_debug: gate inverted — full prompts/replies captured when debug is OFF'),
    ('worktree.py', 'if os.environ.get("DEVLOOP_KEEP_WORKTREE") == "1":', 'if False:',
     'finalize: DEVLOOP_KEEP_WORKTREE ignored (post-mortem tree always destroyed)'),
    ('trace_view.py', 'for c in dod:', 'for c in []:',
     'chain view: every criterion block dropped (the TDD chain renders empty)'),
    ('loop.py', '_emit(run_dir, step="frozen_tests", n=len(frozen_tests))', 'pass',
     'order pin: the freeze is no longer demonstrable BEFORE the first implement in the trace'),
    ('loop.py', '\n            pg = _partial_grounding(charter, st, judge_verdicts, test_to_criterion)',
     '\n            pg = None',
     'run_v1: back-off HUMAN_REVIEW no longer ships the partial grounding chain'),
    ('loop.py', '\n        pg = _partial_grounding(charter, st, judge_verdicts, test_to_criterion)',
     '\n        pg = None',
     'run_v1: test-fault HUMAN_REVIEW no longer ships the partial grounding chain'),
    ('loop.py', 'g["grounded"] = False', 'g["grounded"] = True',
     '_partial_grounding: a FAILED terminal claims grounded=True (a paper false-complete)'),
    ('devloop_bridge.py', 'if grounding and grounding.get("criteria"):',
     'if terminal == "COMPLETE" and grounding and grounding.get("criteria"):',
     '_summary: grounding block re-gated to COMPLETE-only (failed runs lose their ✗ diagnosis)'),
    ('dispatch.py', 'if tier not in ("unit", "integration"):', 'if False:',
     '_wrap_charter: tier allowlist dropped (arbitrary tier strings invent a new taxonomy)'),
    ('dispatch.py',
     '\'integration-tier criterion (tier: "integration") that exercises the NEW behavior \'',
     "'criterion that exercises the NEW behavior '",
     'survey: the integration-criterion requirement gutted (modify tasks lose the larger-validate tier)'),
    ('dispatch.py',
     '"  - TIER discipline (each criterion below carries a tier): tier=unit isolates the NEW logic — "',
     '""',
     'designer prompt: tier discipline gutted (no mock-isolation for unit, no no-mock rule for integration)'),
    ('loop.py', '"tier": c.get("tier", "unit"),\n         "tests": sorted(inv.get(c["id"], [])),',
     '"tier": "unit",\n         "tests": sorted(inv.get(c["id"], [])),',
     '_design_spec: criterion tier hardcoded (the small/larger validate split invisible in the bundle)'),
    ('loop.py', '"tier": c.get("tier", "unit"),   # unit|integration — the small/larger validate split',
     '"tier": "unit",   # unit|integration — the small/larger validate split',
     '_grounding_report: criterion tier hardcoded (grounding loses the validation-ladder view)'),
    ('scripts/devloop_cli.py', 'if top != real:', 'if False:',
     'devloop_cli: enclosing-repo toplevel check dropped (a plain subdir targets the DATA repo)'),
    ('devloop_bridge.py', 'if not os.path.isdir(os.path.join(scratch, ".git")):', 'if not _is_git_repo(scratch):',
     '_scratch_repo: upward-walk detection resurrected (scratch inside /opt/data never inits; branches cut off the data repo)'),
    # ---- deep-review batch (2026-07-01): vague-goal gate, regression gate, charter element guard ----
    ('gate.py', 'if not hits:', 'if True:',
     'vague_goal_gate: disable the marker screen entirely (every vague request PROCEEDs)'),
    ('gate.py', 'if not req_nums:', 'if False:',
     'vague_goal_gate: skip the no-measurable-target branch (marker + digit-free charter PROCEEDs)'),
    ('gate.py', 'if fabricated:', 'if False:',
     'vague_goal_gate: accept planner-fabricated benchmark numbers (the spike_recal false-complete shape)'),
    ('runner.py', 'decision, reason = gate.vague_goal_gate(goal_text, charter)',
     'decision, reason = (config.DECISION_PROCEED, "")',
     'run_task: bypass the vague-goal gate wiring (falls through to the ambiguity gate alone)'),
    ('gate.py', 'if code in (0, 5):', 'if code in (0, 1, 5):',
     'regression_gate: a RED whole-suite run (exit 1) reads as pass'),
    ('gate.py', 'getattr(ev, "exit_code", None)', 'getattr(ev, "exit_code", 0)',
     'regression_gate: shapeless evidence defaults to exit 0 (fail-open on a wrong-shaped record)'),
    ('loop.py', 'if not reg_ok:', 'if False:',
     'run_v1: drop the whole-suite regression gate (a modify task that breaks existing tests COMPLETEs)'),
    ('state.py', 'errs += [f"{k}[{i}] is not an object" for i, x in enumerate(charter[k])',
     'errs += [f"{k}[{i}] is not an object" for i, x in enumerate([])',
     'validate_charter: skip the element-shape check (a bare-string assumption crashes ambiguity_gate)'),
    ('gate.py', 'low = min(confs) if confs else 0.0', 'low = max(confs) if confs else 0.0',
     'ambiguity_gate: low = min(confs) must apply the floor to the WEAKEST assumption, not the strongest'),
    ('gate.py', 'seats_present = {v.get("seat") for v in verdicts if v.get("seat")}', 'seats_present = {v.get("seat") for v in verdicts}',
     "council_gate: seats_present filter `if v.get('seat')` — a seatless verdict must NOT count toward COUNCIL_SIZE"),
    ('gate.py', 'affirm_seats = {v.get("seat") for v in verdicts if v.get("affirm") is True and v.get("seat")}', 'affirm_seats = [v.get("seat") for v in verdicts if v.get("affirm") is True and v.get("seat")]',
     'council_gate: affirm_seats must be a SET (distinct-seat quorum) — duplicate affirms from one seat count once'),
    ('evidence.py', 'r.returncode == 0', 'r.returncode <= 0',
     'run(): passed=(r.returncode == 0) — signal-killed (negative exit code) honesty'),
    ('evidence.py', 'd.get("passed", False)', 'd.get("passed", True)',
     "Evidence.from_dict(): passed=bool(d.get('passed', False)) — fail-closed rehydrate default"),
    ('evidence.py', 'e.get("passed", False)', 'e.get("passed", True)',
     "_passed(): dict branch bool(e.get('passed', False)) — fail-closed default on un-rehydrated dict"),
    ('evidence.py', 'timeout = timeout or evidence_timeout_s()', 'timeout = timeout',
     'run(): timeout = timeout or evidence_timeout_s() — default-timeout fallback wiring'),
    ('evidence.py', 'return 3600', 'return 1',
     'evidence_timeout_s(): return 3600 — default subprocess timeout floor (project policy: never lower)'),
    ('state.py', 'not c.get("id") or not c.get("verify_intent")', 'not c.get("id") and not c.get("verify_intent")',
     "validate_charter: per-criterion checkability `not c.get('id') or not c.get('verify_intent')` (state.py:128)"),
    ('state.py', 'except (json.JSONDecodeError, OSError):', 'except OSError:',
     'load_checkpoint: torn-write fail-safe `except (json.JSONDecodeError, OSError):` (state.py:102)'),
    ('state.py', 'in (None, "", [], {})', 'in (None, "", [])',
     "validate_charter: empty-value sentinel `in (None, '', [], {})` (state.py:125)"),
    ('state.py', 'raise TypeError(f"not JSON-serializable: {type(o).__name__}")', 'return None',
     '_json_default: fail-loud `raise TypeError(...)` for a non-to_dict object (state.py:66)'),
    ('dod_oracle.py', 'if cid not in by_crit:', 'if True:',
     'judge_assertions: grouping guard `if cid not in by_crit` (one verdict per criterion, test_ids combined)'),
    ('dod_oracle.py', '"encodes": a and b,', '"encodes": b,',
     'judge_assertions: `encodes = a and b` (2-model AGREEMENT requires BOTH judges) in the untested reject-by-A path'),
    ('dod_oracle.py', 'ex.submit(judge_a, crit, by_crit[cid])', 'ex.submit(judge_a, crit, by_crit[cid][:1])',
     'judge_assertions: judges receive the FULL test set `by_crit[cid]`, not a truncated one'),
    ('dod_oracle.py', 'if c.get("id")', 'if True',
     "check_structural_coverage: `if c.get('id')` filter gracefully skips id-less / empty-id criteria"),
    ('render.py', 'if not all(isinstance(k, str) and _IDENT.match(k) for k in kwargs):', 'if False:',
     "_render_case: kwargs-key identifier validation (render.py:49) — each kwarg key flows UNESCAPED into the call"),
    ('render.py', 'and isinstance(call, str) and _IDENT.match(call)):', 'and isinstance(call, str)):',
     '_render_entry: call-name identifier validation (render.py:112) — `call` is inserted UNESCAPED into the source'),
    ('render.py', 'if m["side_effect"] not in _ALLOWED_EXC:', 'if False:',
     '_mock_with: side_effect allowlist guard (render.py:76) — side_effect is emitted UNESCAPED'),
    ('render.py', 'if cid in seen:', 'if False:',
     'render_spec: duplicate criterion_id dedup (render.py:149) — `if cid in seen: continue` keeps the FIRST def'),
    ('render.py', 'if not isinstance(args, list) or not isinstance(kwargs, dict):', 'if False:',
     '_render_case: args/kwargs container-type guard (render.py:47) — fail-closes on a malformed case shape'),
    ('render.py', 'and not classes', 'and True',
     '_valid_raw: top-level-class rejection (render.py:93, `and not classes`) — pins the raw escape-hatch shape'),
    ('testgen.py', '    if not planned:\n        return {}\n    if not pytest_available():\n        raise RuntimeError(_PYTEST_MISSING)', '    if not planned:\n        return {}\n    if not pytest_available():\n        return planned',
     'collect_spec_map: pytest-unavailable branch must RAISE, never return planned (fail-OPEN fake coverage)'),
    ('testgen.py', '        raise RuntimeError(_PYTEST_MISSING)', '        return {}',
     'collect_spec_map: the raise itself must fire (not return {}) when pytest is unavailable (masquerades missing dep)'),
    ('testgen.py', 'c.startswith(nid + "[")', 'c.startswith(nid)',
     "_covered: the `nid + '['` parametrize boundary (line 93) prevents prefix-collision false credit"),
    ('lint.py', 'ok = False\n                continue', 'ok = True\n                continue',
     'lint_paths: spawn-failure except branch sets ok=False'),
    ('lint.py', 'r.get("error") or r.get("exit_code") not in (0, None)', 'r.get("exit_code") not in (0, None)',
     'failures(): error-key classification of un-spawnable/timed-out entries'),
    ('lint.py', 'os.path.splitext(p)[1].lower()', 'os.path.splitext(p)[1]',
     'lint_paths: case-insensitive extension normalization via .lower()'),
    ('lint.py', 'not in (0, None)', 'not in (0,)',
     'failures(): skipped results (exit_code absent -> None) must never count as failures'),
    ('lint.py', '"covered": bool(runnable)', '"covered": True',
     'discover(): covered honesty must reflect bool(runnable), not hardcoded True'),
    ('lint.py', '["node", "--check", p]', '["node", "--version"]',
     'lint_paths: js (.js) end-to-end linting path never exercised through lint_paths'),
    ('loop.py', 'if not lint_ok:     # syntactic breakage -> feed back + rebuild, skip the test/judge passes', 'if False:     # syntactic breakage -> feed back + rebuild, skip the test/judge passes',
     'run_v1 post-IMPLEMENT lint gate `if not lint_ok` (loop.py line 222) on the production path'),
    ('loop.py', 'st = state.new_run_state(charter)\n    ids = [c["id"] for c in charter["dod"]]\n    by_id',
     'st = state.load_checkpoint(run_dir) or state.new_run_state(charter)\n    ids = [c["id"] for c in charter["dod"]]\n    by_id',
     'run_v1: RE-ADD the deleted loop-level resume (a planted checkpoint must be IGNORED — every invoke is fresh)'),
    ('loop.py', 'if files_changed == 0:     # coder changed nothing AND not complete -> dispatch error', 'if False:     # coder changed nothing AND not complete -> dispatch error',
     'run_v1 noop-coder fast route `if files_changed == 0` -> _dispatch_error (loop.py line 249)'),
    ('project.py', 'except Exception:', 'except OSError:',
     '_safe_changed: the `except Exception` fail-safe that keeps a per-task diff error from killing the project loop'),
    ('project.py', 'if it["status"] == "in_progress":', 'if it["status"] != "completed":',
     'run_project crash-recovery: only `in_progress` is reset to `pending`; a blocked purpose must NOT be retried'),
    ('project.py', 'if pending:', 'if False:',
     "_render_report: the 'N purpose(s) still pending (loop did not fully drain)' warning branch (project.py:211)"),
    ('project.py', 'if not blocked and not pending:', 'if True:',
     "_render_report: the 'all purposes resolved; nothing outstanding' all-clear branch (project.py:213)"),
    ('project.py', 'it["attempts"] and it["attempts"][-1].get("terminal") == "COMPLETE"', 'it["attempts"][-1].get("terminal") == "COMPLETE"',
     "_summarize: the `it['attempts'] and` empty-attempts guard in the achieved computation (project.py:190)"),
    ('runner.py', '"terminal": "HUMAN_REVIEW", "reason": str(e)', '"terminal": "COMPLETE", "reason": str(e)',
     'run_task: designer RuntimeError (pytest unavailable) -> HUMAN_REVIEW branch (lines 64-68)'),
    ('runner.py', 'dispatch.assert_distinct_models(dispatch.CODER, dispatch.DESIGNER, dispatch.JUDGE_A, dispatch.JUDGE_B)', 'dispatch.assert_distinct_models(dispatch.CODER)',
     'run_task: real-judge path invokes dispatch.assert_distinct_models BEFORE worktree creation (line 42)'),
    ('runner.py', 'make_designer = make_designer or dispatch.designer_spec_via_ask',
     'make_designer = make_designer or (lambda target: (lambda charter: {}))',
     'run_task: the STRUCTURED spec designer is THE default (mutant swaps in an empty-map stub)'),
    ('dispatch.py', '"planner output unparseable", "blocking": True', '"planner output unparseable", "blocking": False',
     'charter_via_ask: fail-closed branch (unparseable/empty planner output -> empty dod + a blocking question)'),
    ('dispatch.py', '"exit_code": code,', '"exit_code": 0,',
     'implementer_via_ask.implement: real exit_code passthrough that feeds loop.py:123/218 dispatch-error fast-fail'),
    ('dispatch.py', 'if last_failure:', 'if False:',
     'implementer_via_ask.implement: `if last_failure:` repair-feedback injection into the coder prompt'),
    ('dispatch.py', 'changed += sum(1 for k in before if k not in after)', 'changed += sum(0 for k in before if k not in after)',
     "_count_changed: deletion-counting term (drives files_changed -> loop.py 'coder made no file change')"),
    ('dispatch.py', '"changed_paths": _changed_paths(before, after)', '"changed_paths": []',
     'implementer_via_ask.implement: changed_paths return that drives the post-IMPLEMENT lint gate (loop.py:60)'),
    ('dispatch.py', 'dirs[:] = [x for x in dirs if x not in worktree._JUNK_SEGMENTS]\n        for f in files:',
     'dirs[:] = dirs\n        for f in files:',
     '_snapshot: junk-dir prune dropped -> coder venvs/caches reach the lint gate + no-op detection'
     ' (learn-accept live catch: 852 third-party files linted)'),
    ('dispatch.py', 'dirs[:] = [x for x in dirs if x not in worktree._JUNK_SEGMENTS]\n        for f in files:',
     'dirs[:] = [x for x in dirs if x in worktree._JUNK_SEGMENTS]\n        for f in files:',
     '_snapshot: junk filter inverted -> ONLY junk is walked; real coder edits become invisible'),
    ('render.py', 'return f"test_devloop_dod_{slug}.py" if slug else CANONICAL_FILE',
     'return CANONICAL_FILE',
     'canonical_file: per-run oracle filename regressed to the shared fixed name -> re-runs clobber'
     ' the prior oracle and concurrent runs always merge-conflict on it'),
    ('render.py', 'slug = _SLUG_RE.sub("_", str(run_name or "").lower()).strip("_")[:40]',
     'slug = str(run_name or "")[:40]',
     'canonical_file: slug sanitization dropped -> raw run names reach filesystem paths/node ids'),
    ('dispatch.py', 'run_name=os.path.basename(os.path.realpath(target_dir)))',
     'run_name=None)',
     'designer_spec_via_ask: per-run oracle filename threading dropped (every run shares one file)'),
    ('worktree.py', 'if expected_branch and out["target"] != expected_branch:', 'if False:',
     'merge_branch: mid-run branch-switch guard dropped -> COMPLETE work lands on the WRONG branch'),
    ('worktree.py',
     'cur = _git(repo, "symbolic-ref", "--short", "HEAD", check=False)\n'
     '    if cur.returncode != 0:',
     'cur = _git(repo, "symbolic-ref", "--short", "HEAD", check=False)\n'
     '    if False:',
     'merge_branch: detached-HEAD refusal dropped -> COMPLETE work can false-report merged'),
    ('worktree.py', '"start_branch": start_branch,', '"start_branch": "",',
     'create_worktree: derivation-branch recording dropped -> the branch-switch guard is disarmed'),
    ('devloop_bridge.py', 'expected_branch=wt.get("start_branch"))', 'expected_branch=None)',
     'bridge: start_branch threading into merge_branch dropped (branch-switch guard never armed)'),
    ('worktree.py', 'for _ in range(2):', 'for _ in range(0):',
     'merge_branch: index.lock retry dropped -> a foreign transient lock degrades a verified COMPLETE'),
    ('worktree.py',
     'out.update(notes)\n'
     '        if not ok:\n'
     '            out["reason"] = why\n'
     '            return out\n'
     '        out["synced"] = True',
     'out.update(notes)\n'
     '        if False:\n'
     '            out["reason"] = why\n'
     '            return out\n'
     '        out["synced"] = True',
     'merge_branch: red combined-tree refusal dropped -> an unverified combination false-merges'),
    ('worktree.py', '"index.lock" not in ((r.stderr or "") + (r.stdout or ""))',
     '"index.lock" in ((r.stderr or "") + (r.stdout or ""))',
     'merge_branch: retry trigger inverted (retries every failure EXCEPT lock contention)'),
    ('worktree.py', 'with open(excl, "a") as f:\n            f.write("\\n.devloop/\\n")',
     'with open(excl, "w") as f:\n            f.write("\\n.devloop/\\n")',
     'worktree.create_worktree: info/exclude written in append mode (additive local ignore)'),
    ('worktree.py', '_git(repo, "worktree", "add", "-b", branch, wt, base)', '_git(repo, "worktree", "add", "-b", branch, wt)',
     "worktree.create_worktree: base commit-ish argument is passed to 'worktree add'"),
    # ---- guard mutants for the 3 non-mutant kernel fixes shipped with this buildout ----
    ('state.py', 'if not isinstance(c, dict):     # a malformed (non-dict) criterion fails closed', 'if False:     # a malformed (non-dict) criterion fails closed',
     'validate_charter: non-dict dod entry guard (fails closed instead of AttributeError-crashing)'),
    ('state.py', 'if isinstance(obj, dict):     # ignore parseable-but-non-dict lines', 'if True:     # ignore parseable-but-non-dict lines',
     'read_learnings: non-dict line filter (a stray non-object must not enter the lessons builder)'),
    ('gate.py', 'except (AttributeError, TypeError) as e:  # malformed (non-dict) verdict shape', 'except RuntimeError as e:  # malformed (non-dict) verdict shape',
     'council_gate: verdict-shape parse guard catches the non-dict AttributeError (fails closed, not crashes)'),
    ('dispatch.py', '+ _IMPL_STYLE', '+ ""',
     'implementer_via_ask: drop the handoff-quality (breadcrumbs/docs + error-checking) directives from the coder prompt'),
    ('dispatch.py', 'if not _unusable(*last):', 'if True:',
     '_chat (#36): never retry — a transient empty/refusal/error result is returned on the first try'),
    ('dispatch.py', 'return any(m in low for m in _REFUSAL_MARKERS)', 'return False',
     '_unusable (#36): stop treating an explicit model refusal as a retryable result'),
    ('dispatch.py', 'if attempt >= config.DIAGNOSE_AFTER_ATTEMPT:', 'if False:',
     'implementer (#35): never escalate to the diagnoser on a repeat failure (debug cascade disabled)'),
    ('dispatch.py', 'text if text and "dispatch error" not in text[:40].lower() else ""', 'text if text else ""',
     'diagnose_via_ask (#35): stop filtering a dispatch-error reply -> garbage guidance fed to the coder'),
    ('dispatch.py', 'return sum(votes) * 2 > len(votes)\n    return judge', 'return sum(votes) > 0\n    return judge',
     'judge majority -> any-single-YES trusts a test (a flaky YES no longer needs a majority)'),
    ('dispatch.py', 'if sum(1 for v in votes if v) * 2 <= len(votes):', 'if sum(1 for v in votes if v) == 0:',
     'advisor majority -> block on ANY vote (a single flaky over-block routes a fine task to a human)'),
    ('dispatch.py', 'or f.startswith("test_") or f.startswith("."):', 'or f.startswith("."):',
     '_repo_symbols: leak test functions into the designer module hint (test_ files must be excluded)'),
    # ---- devloop_bridge (the pipeline.py strangler seam) ----
    ('devloop_bridge.py', 'os.environ.get("DEVLOOP_ENABLED", "1")', 'os.environ.get("DEVLOOP_ENABLED", "0")',
     'devloop_enabled: default OFF would disable the SDLC engine when the toggle is unset (it must default ON now)'),
    # ---- corner-condition hardening (2026-07-02): scratch-by-default, one HR dialect, crash-finalize ----
    ('devloop_bridge.py', 'if repo is SCRATCH or repo is None:', 'if repo is SCRATCH:',
     '_run: repo=None no longer aliases to scratch — an unset repo leaks through as the run target'),
    ('devloop_bridge.py', 'if repo is SCRATCH or repo is None:', 'if False:',
     '_run: scratch default dropped entirely — the SCRATCH sentinel itself leaks through as the repo'),
    ('devloop_bridge.py', '"needs_human": False, "open_questions": [],', '"needs_human": True, "open_questions": [],',
     'failure_result: an engine CRASH masquerades as a needs-input outcome (CLI exit 2 instead of 1)'),
    ('runner.py', 'worktree.finalize(wt, f"devloop CRASHED ({type(e).__name__}): {name}")', 'pass',
     'run_task crash-finalize dropped — an engine exception leaks the checkout + devloop/<name> branch again'),
    ('dispatch.py', 'timeout=timeout or _dispatch_timeout(), cwd=cwd)', 'timeout=timeout, cwd=cwd)',
     '_chat_raw: dispatch-timeout floor unwired — an unset caller timeout becomes an unbounded subprocess hang'),
    ('loop.py', 'return {"terminal": "NO_TERMINATION", "state": st, "trace_path": trace, "reason": nt_reason}',
     'return {"terminal": "COMPLETE", "state": st, "trace_path": trace, "reason": nt_reason}',
     'run_v1: max_passes exhaustion returns COMPLETE — an undecided run reads as success (the worst false-complete)'),
    # ---- scout -> build pipeline (relentless-solve as pathfinder, user decision 2026-07-03) ----
    ('scout.py', 'if r.returncode != 0 or outcome not in _TERMINAL_OUTCOMES:',
     'if outcome not in _TERMINAL_OUTCOMES:',
     'run_scout: nonzero-exit gate dropped — a crashed scout whose stdout still claims success reads as a finding'),
    ('scout.py', 'if outcome == "success" and doc["no_path"] is None:', 'if doc["no_path"] is None:',
     'run_scout: capped/dry runs with a step list read as CONCLUDED — unverified steps get built'),
    ('scout.py', 'if doc["no_path"] and outcome in ("success", "information-dry"):', 'if doc["no_path"]:',
     'run_scout: a no-path note from a CAPPED run reads as a concluded verdict'),
    ('scout.py', 'sc["ok"] and not scout_only', 'sc["ok"]',
     'run_pipeline: --scout-only ignored — the build runs anyway'),
    ('scout.py', 'not scout_only and not sc["unconcluded"]', 'not scout_only',
     'run_pipeline: unconcluded findings get built'),
    ('scout.py', 'and bool(sc["steps"]))', ')',
     'run_pipeline: empty/no-path findings enqueue a build anyway (steps gate dropped)'),
    ('scout.py', 'type(sv) is not int or sv != SCHEMA_VERSION', 'False',
     'load_steps: schema-version gate gutted — any future artifact dialect is accepted blind'),
    ('scout.py', 'len(steps) > MAX_STEPS', 'False',
     'load_steps: step-count sanity cap dropped — a runaway artifact enqueues an unbounded build'),
    ('scout.py', 'if steps and no_path:', 'if False and steps and no_path:',
     'load_steps: a contradictory steps+no_path finding is accepted instead of refused'),
    ('scout.py', "f\"{s['purpose']}\\n\\nSuccess criterion: {s['success_criterion']}\"", "f\"{s['purpose']}\"",
     'steps_to_purposes: the success criterion no longer rides into the devloop charter'),
    ('scout.py', 'hashlib.sha256(f"{os.path.realpath(repo)}\\0{request}".encode("utf-8")).hexdigest()[:16]',
     '"0000000000000000"',
     'scout_slug: identity hash dropped — colliding requests/repos share a state dir and read each other\'s findings'),
    ('scout.py', 'f"{os.path.realpath(repo)}\\0{request}"', 'f"{request}"',
     'scout_slug: repo dropped from the hash — the SAME request against a DIFFERENT repo resumes the wrong drain PLAN and exits 0 having built nothing (review must-fix)'),
    # ---- squash merge (user decision 2026-07-03: one clean commit per run on the target) ----
    ('worktree.py', 'if _git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:', 'if False:',
     'merge_branch: empty-delta gate dropped — a no-delta squash tries to commit nothing and fails the whole merge'),
    ('worktree.py', 'if not new:', 'if False:',
     'merge_branch: commit-tree-failure gate dropped — a failed squash commit-tree falls through instead of failing safe; merged is reported on a commit that never built'),
    ('worktree.py', '_git(repo, "reset", "--hard", "-q", check=False)   # undo the staged squash', 'pass',
     'merge_branch: staged-squash reset dropped — a failed commit leaves a staged half-merge in the target tree'),
    ('scout.py', 'shutil.rmtree(state_dir, ignore_errors=True)', 'pass',
     'run_scout: --fresh ignored — prior scout state silently resumes'),
    ('scout.py', 'if script is None:', 'if False:',
     'run_scout: missing relentless-solve degrades to a crash instead of a structured refusal'),
    ('scout.py', 'if terminal == "COMPLETE" and not dr.get("merged"):', 'if False:',
     'bridge_step_run_task: an unmerged COMPLETE counts achieved — the next step builds on code that never landed'),
    ('scripts/devloop_pipeline_cli.py', 'return 1 if sc.get("unconcluded") else 0', 'return 0',
     'pipeline CLI: an unconcluded scout exits 0 — a hollow success at the shell boundary'),
    ('scripts/devloop_pipeline_cli.py', 'return 0 if drained else 1', 'return 0',
     'pipeline CLI: blocked/pending steps exit 0 — a false-complete at the shell boundary'),
    ('scripts/devloop_pipeline_cli.py',
     'drained = bool(items) and not proj.get("blocked") and all(it.get("status") == "completed" for it in items)',
     'drained = not proj.get("blocked") and all(it.get("status") != "pending" for it in items)',
     'pipeline CLI: terminal-success drain predicate weakened -> in-progress work exits 0'),
    ('devloop_bridge.py', '"retryable": result.get("retryable"), "charter": charter,',
     '"retryable": None, "charter": {},',
     '_run: retryable/charter no longer forwarded — the pipeline drain loses escalate-vs-reattempt fidelity'),
    ('devloop_bridge.py', '"retryable": False, "charter": {}, "boundary_restored": [],',
     '"retryable": None, "charter": {}, "boundary_restored": [],',
     'failure_result: an engine crash reads re-attemptable — burns drain budget instead of escalating'),
    ('scout.py', 'pre = _git_status(repo)', 'pre = []',
     'run_pipeline: dirty-repo precondition dropped — the pipeline scouts/merges over uncommitted user work (and the scrub baseline is gone)'),
    ('scout.py', 'scrubbed = _scrub_scout_debris(repo)', 'scrubbed = []',
     'run_pipeline: scout debris scrub dropped — a disobedient scout\'s trial-implementation stays in the target repo (the live-caught breach)'),
    ('scout.py', 'if scrubbed is None:', 'if False:',
     'run_pipeline: a FAILED debris restore no longer fails closed — the build runs on a repo in an unknown state'),
    ('scout.py', 'shutil.rmtree(pdir, ignore_errors=True)', 'pass',
     'run_pipeline: --fresh no longer clears the drain — a blocked PLAN.json resumes as an instant no-op re-report'),
    ('devloop_bridge.py', 'boundary_restored, boundary_failed = _restore_boundary_breach(repo, pre_status)',
     'boundary_restored, boundary_failed = [], []',
     '_run: worktree-boundary guard dropped — agent escape debris stays in the target repo main tree (the live-caught deletion)'),
    ('devloop_bridge.py', 'new = {p: code for p, code in post.items() if p not in pre}', 'new = dict(post)',
     "_restore_boundary_breach: pre-existing dirt no longer preserved — a user's uncommitted work gets nuked by the guard"),
    ('devloop_bridge.py', 'restored = sorted(p for p in new if p not in after)', 'restored = sorted(new)',
     '_restore_boundary_breach: verification dropped — a FAILED restore is reported as restored (the guard can lie)'),
    ('devloop_bridge.py', 'failed = sorted(p for p in new if p in after)', 'failed = []',
     '_restore_boundary_breach: failed-restore reporting dropped — breaches that survived cleanup go unnamed'),
    ('devloop_bridge.py', 'if code == "??" or code[0] in ("A", "R", "C"):', 'if True:',
     '_restore_boundary_breach: tracked-vs-untracked discrimination dropped — deleted tracked files are never restored from HEAD'),
    ('scout.py', '"Steps must be FUNCTIONAL/PRODUCT changes only — never a step whose deliverable is "',
     '""',
     "scout_intent: no-test-steps rule dropped — scouts emit 'write a test' steps that devloop's judges can never trust (live-caught cap-burn)"),
    # ---- quality-review coverage batch (2026-07-03): tested-but-unpinned guards ----
    ('scout.py', 'if doc is None:', 'if False:',
     'run_scout: missing/malformed-artifact gate dropped — a scout with no valid finding crashes/leaks instead of failing closed'),
    ('scout.py', 'if not (isinstance(s.get("purpose"), str) and s["purpose"].strip()):', 'if False:',
     'load_steps: empty-purpose steps accepted — a blank build-queue entry reaches the drain'),
    ('scout.py', 'if not (isinstance(s.get("success_criterion"), str) and s["success_criterion"].strip()):', 'if False:',
     'load_steps: criterion-less steps accepted — devloop charters a step with no checkable definition of done'),
    ('scout.py', 'if not steps and not no_path:', 'if False:',
     'load_steps: an empty finding with NO no-path reason is accepted as a valid conclusion'),
    ('scout.py', 'or outcome not in _TERMINAL_OUTCOMES:', 'or False:',
     'run_scout: unknown-outcome gate dropped — garbage engine output reads as a terminal state'),
    ('scripts/devloop_pipeline_cli.py', 'if not sc.get("ok"):', 'if False:',
     'pipeline CLI: scout-failure no longer exits 2 — a failed scout reads as a clean informational stop'),
    ('scripts/devloop_pipeline_cli.py', 'args.max_cycles if args.max_cycles is not None else defaults[0]',
     'args.max_cycles or defaults[0]',
     'pipeline CLI: explicit --max-cycles 0 silently replaced by the default (review regression)'),
    # ---- cleanup batch (2026-07-03) ----
    ('worktree.py', 'if ".devloop/" not in existing:', 'if True:',
     'create_worktree: exclude idempotence dropped — every run grows the target repo info/exclude by another .devloop/ line forever'),
    ('project.py', 'if bridged:', 'if False:',
     '_safe_changed: bridge-reported changed_files ignored — pipeline lessons/reports lose the file list ("changed 0 file(s)")'),
    # ---- scout fail-closed Batch A (2026-07-03) ----
    ('scout.py', 'if pre is None:', 'if False:',
     'run_pipeline: unreadable pre-scout git status reads as clean instead of failing closed'),
    ('scout.py', 'if dirty is None:', 'if False:',
     '_scrub_scout_debris: unreadable initial git status reads as already clean'),
    ('scout.py', 'r1.returncode != 0 or r2.returncode != 0 or post is None or post',
     'r1.returncode != 0 or r2.returncode != 0 or post',
     '_scrub_scout_debris: unreadable post-scrub status reads as a successful restore'),
    ('scout.py', 'return subprocess.run(cmd, capture_output=True, text=True, errors="replace",\n'
                 '                              timeout=timeout)',
     'return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)',
     '_invoke: undecodable child output raises instead of being replaced safely'),
    ('scout.py', 'try:\n'
                 '        for s in steps:\n'
                 '            s["purpose"].encode("utf-8")\n'
                 '            s["success_criterion"].encode("utf-8")\n'
                 '        if isinstance(no_path, str):\n'
                 '            no_path.encode("utf-8")\n'
                 '    except UnicodeEncodeError:\n'
                 '        return None',
     'if False:\n        return None',
     'load_steps: non-UTF-8 surrogate strings are accepted into the build queue'),
    ('scout.py', 'if os.path.exists(state_dir):', 'if False:',
     'run_scout: ineffective --fresh deletion silently resumes prior scout state'),
    ('scout.py', 'if os.path.exists(pdir):', 'if False:',
     'run_pipeline: ineffective --fresh deletion silently resumes prior pipeline state'),
    # ---- Batch B: false-complete + ABA correctness (2026-07-03) ----
    ('devloop_bridge.py',
     'kept_branch = bool(keep_branch and terminal == "COMPLETE" and fin.get("branch_kept")\n'
     '                       and fin.get("committed"))',
     'kept_branch = bool(keep_branch and terminal == "COMPLETE" and fin.get("branch_kept"))',
     '_run: --keep-branch committed gate dropped — a failed finalize commit reads as kept COMPLETE'),
    ('devloop_bridge.py',
     'if (terminal == "COMPLETE" and fin.get("branch_kept") and fin.get("committed")\n'
     '            and not keep_branch):',
     'if (terminal == "COMPLETE" and fin.get("branch_kept")\n'
     '            and not keep_branch):',
     '_run: auto-merge committed gate dropped — a contentless branch can false-report merged'),
    ('worktree.py', 'if base and bh == base:', 'if False:',
     'merge_branch: no-commit branch refusal dropped — an empty branch can false-report merged'),
    ('worktree.py', 'if cas.returncode != 0:', 'if False:',
     'merge_branch: CAS-refusal dropped — a tip-moved (concurrent devloop or foreign) write '
     'lands an UNVERIFIED combination as merged and deletes the branch (work lost)'),
    ('worktree.py',
     'c = _git(path, *_identity(),\n'
     '                         "commit", "-qm", f"devloop: post-sync fix for {branch}", check=False)\n'
     '                if c.returncode != 0:',
     'c = _git(path, *_identity(),\n'
     '                         "commit", "-qm", f"devloop: post-sync fix for {branch}", check=False)\n'
     '                if False:',
     'post-sync fixer commit-landed check dropped — an unfixed red combination merges as fixed'),
    ('devloop_bridge.py', 'if after is None:\n        return [], sorted(new)',
     'if False:\n        return [], sorted(new)',
     '_restore_boundary_breach: failed post-restore status is treated as verified success'),
    ('worktree.py',
     'if deleted.returncode == 0:\n'
     '        out["leaked_branch"] = branch\n'
     '        out["reason"] += "; branch deletion failed — branch leaked, delete manually"',
     'if False:\n'
     '        out["leaked_branch"] = branch\n'
     '        out["reason"] += "; branch deletion failed — branch leaked, delete manually"',
     'merge_branch: post-delete verification dropped — a leaked branch is hidden after merge'),
    ('worktree.py',
     'if r.returncode != 0:\n'
     '        # fail-SAFE: never leave a conflicted/staged tree. A conflicted squash has no\n'
     '        # MERGE_HEAD (`merge --abort` errors), but the dirty-guard above proved the tree\n'
     '        # was clean pre-attempt, so a hard reset is exactly "undo the attempt".\n'
     '        _git(repo, "reset", "--hard", "-q", check=False)\n'
     '        out["reason"] = f"merge failed: {(r.stderr or r.stdout).strip()[:200]}"',
     'if r.returncode != 0:\n'
     '        # fail-SAFE: never leave a conflicted/staged tree. A conflicted squash has no\n'
     '        # MERGE_HEAD (`merge --abort` errors), but the dirty-guard above proved the tree\n'
     '        # was clean pre-attempt, so a hard reset is exactly "undo the attempt".\n'
     '        pass\n'
     '        out["reason"] = f"merge failed: {(r.stderr or r.stdout).strip()[:200]}"',
     'merge_branch: original non-index-lock squash-failure reset dropped — target stays dirty'),
    ('worktree.py',
     'r = _git(repo, "merge", "--squash", branch, check=False)\n'
     '    if r.returncode != 0:\n'
     '        # fail-SAFE: never leave a conflicted/staged tree.',
     'r = _git(repo, "merge", "--squash", branch, check=False)\n'
     '    if False:\n'
     '        # fail-SAFE: never leave a conflicted/staged tree.',
     'merge_branch: squash-failure refusal dropped -> a failed squash can false-report merged'),
    ('devloop_bridge.py', '            out[fields[i]] = " D"', '            pass',
     '_repo_status: rename/copy original side dropped — boundary restore loses the deleted path'),
    # ---- Batch C: resume validation + load_steps shape guards (2026-07-03) ----
    ('project.py', 'type(sv) is not int or sv != 1', 'False',
     '_load_plan: schema-version pin dropped — foreign drain state is resumed blind'),
    ('project.py', 'if (plan["items"] and not roots) or roots != purposes:', 'if False:',
     'run_project: purpose-match refusal dropped — a foreign/stale PLAN resumes as instantly '
     'drained and the pipeline exits 0 having built nothing'),
    ('scout.py', 'if not isinstance(d, dict):', 'if False:',
     'load_steps: non-object top-level JSON reaches object-only field access'),
    ('scout.py', 'not isinstance(steps, list)', 'isinstance(steps, list)',
     'load_steps: list-shape predicate inverted — the build-queue type boundary is corrupted'),
    ('scout.py', 'if not isinstance(s, dict):', 'if False:',
     'load_steps: non-object step entries reach object-only field access'),
    ('scout.py',
     'if no_path is not None and not (isinstance(no_path, str) and no_path.strip()):',
     'if False:',
     'load_steps: malformed no_path values are accepted instead of refused'),
]

TEST_FILES = ("tests/test_smoke.py", "tests/test_e2e.py", "tests/test_lint.py",
              "tests/test_project.py", "tests/test_render.py", "tests/test_real_spike.py",
              # the production run_v1 path was UNGUARDED — the loop/dispatch suites never ran here
              # (non-mutant gap #4), so a fail-open/non-terminating run_v1 regression passed silently.
              "tests/test_loop.py", "tests/test_loop_v1.py", "tests/test_loop_dispatch_error.py",
              "tests/test_runner.py", "tests/test_dispatch.py", "tests/test_testgen.py", "tests/test_worktree.py",
              # the 13 coverage-buildout suites (one per source file) that kill the surviving mutants below
              "tests/test_gate.py", "tests/test_evidence.py", "tests/test_state.py", "tests/test_dod_oracle.py",
              "tests/test_render_more.py", "tests/test_testgen_more.py",
              "tests/test_lint_more.py", "tests/test_loop_more.py", "tests/test_project_more.py",
              "tests/test_runner_more.py", "tests/test_dispatch_more.py", "tests/test_worktree_more.py",
              "tests/test_bridge.py", "tests/test_trace_view.py", "tests/test_cli.py",
              "tests/test_scout.py", "tests/test_mutants_registry.py")

# Killer-first hints for source files whose test suite isn't found by the module-stem rule.
_KILLER_HINTS = {
    "devloop_bridge.py": ("bridge", "cli", "scout"),
    "scripts/devloop_cli.py": ("cli",),
    "scripts/devloop_pipeline_cli.py": ("scout",),
}


def _ordered_tests(src_file: str):
    """TEST_FILES reordered so the mutated module's own suites run FIRST. A killed mutant
    then costs one small file instead of the whole ~22s sweep; a SURVIVING mutant still runs
    every file before the verdict, so soundness is unchanged — this is pure wall-clock."""
    hints = _KILLER_HINTS.get(src_file, (os.path.basename(src_file)[:-3],))
    first = [t for t in TEST_FILES if any(h in os.path.basename(t) for h in hints)]
    return first + [t for t in TEST_FILES if t not in first]


def _suite_passes(root: str, files=TEST_FILES) -> bool:
    for t in files:
        r = subprocess.run([PY, t], cwd=root, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return False
    return True


def _check_registry(dst: str, mutants) -> list[str]:
    """Return hard integrity failures for a candidate mutant registry."""
    texts = {}
    problems = []
    for file, old, new, desc in mutants:
        if file not in texts:
            with open(os.path.join(dst, file)) as f:
                texts[file] = f.read()
        txt = texts[file]
        count = txt.count(old)
        if count == 0:
            problems.append(f"STALE     ?? {desc}")
            continue
        if count > 1:
            problems.append(f"AMBIGUOUS ?? {desc} ({count} occurrences)")
            continue
        if old == new or txt.replace(old, new, 1) == txt:
            problems.append(f"EQUIVALENT ?? {desc}")
    return problems


def _select_mutants(substring: str, mutants=None):
    mutants = MUTANTS if mutants is None else mutants
    needle = substring.casefold()
    return [m for m in mutants if needle in m[3].casefold() or needle in m[1].casefold()]


def _select_mutants_by_files(files, mutants=None):
    mutants = MUTANTS if mutants is None else mutants
    selected_files = set(files)
    return [m for m in mutants if m[0] in selected_files]


def _run_mutants(dst: str, mutants, suite_passes=None):
    suite_passes = _suite_passes if suite_passes is None else suite_passes
    killed = survived = stale = 0
    for file, old, new, desc in mutants:
        p = os.path.join(dst, file)
        with open(p) as f:
            txt = f.read()
        if old not in txt:
            stale += 1
            print(f"  STALE   ??  {desc}")
            continue
        try:
            with open(p, "w") as f:
                f.write(txt.replace(old, new, 1))
            ok = suite_passes(dst, _ordered_tests(file))
        finally:
            with open(p, "w") as f:
                f.write(txt)  # revert
        if ok:
            survived += 1
            print(f"  SURVIVED XX {desc}")
        else:
            killed += 1
            print(f"  KILLED   OK {desc}")
    return killed, survived, stale


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    only = None
    files = None
    while args:
        flag = args.pop(0)
        if flag == "--only" and only is None and args:
            only = args.pop(0)
        elif flag == "--files" and files is None:
            files = []
            while args and args[0] not in ("--only", "--files"):
                files.append(args.pop(0))
            if not files:
                print("--files requires one or more target-file names")
                return 2
        else:
            print("usage: mutants.py [--only <substring>] [--files <file...>]")
            return 2

    selected = MUTANTS
    if only is not None:
        selected = _select_mutants(only, selected)
    if files is not None:
        selected = _select_mutants_by_files(files, selected)
    if not selected:
        filters = []
        if only is not None:
            filters.append(f"--only {only!r}")
        if files is not None:
            filters.append(f"--files {' '.join(files)}")
        print(f"NO MUTANTS MATCH {' '.join(filters)}")
        return 2

    work = tempfile.mkdtemp(prefix="devloop-mut-")
    dst = os.path.join(work, "devloop")
    shutil.copytree(SRC, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    try:
        if not _suite_passes(dst):
            print("BASELINE FAILED — fix the suite before mutation testing")
            return 2
        problems = _check_registry(dst, MUTANTS)
        if problems:
            for problem in problems:
                print(problem)
            print(f"REGISTRY INTEGRITY FAILED — {len(problems)} problem(s); no mutants run")
            return 2
        print(f"baseline: PASS ({len(selected)} mutants)\n")
        killed, survived, stale = _run_mutants(dst, selected)
        print(f"\n{killed} killed / {survived} survived / {stale} stale (of {len(selected)})")
        clean = survived == 0 and stale == 0
        print("ALL MUTANTS KILLED — tests are non-vacuous." if clean else "REVIEW survivors/stale above.")
        return 0 if clean else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
