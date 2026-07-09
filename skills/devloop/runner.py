"""runner.py — run a task through the v1 loop in an isolated git worktree.

Ties it all together: create a worktree -> CHARTER (planner) -> ambiguity gate -> DESIGN (write
tests, derive the REAL collected coverage map) -> per-criterion verify commands -> run_v1
(IMPLEMENT -> evidence -> judge -> stop). Merge policy lives in the BRIDGE (auto-merge on COMPLETE); this layer only produces the committed branch.

Dispatchers are injectable (make_charter/make_designer/make_implementer/judges) so the whole
pipeline is testable deterministically with real git + real pytest and zero LLM calls; the
defaults are the real `ask`-backed dispatchers.
"""
from __future__ import annotations

import os
import sys

import config
import dispatch
import gate
import loop
import testgen
import worktree

# ── Planning announcements (Phase 1, 2026-07-06) ────────────────────────────
# Emitted from runner.run_task BEFORE loop.run_v1 starts. Shows: the request,
# target repo, branch + base SHA, planner model, prior learnings, env survey.
# Respects DEVLOOP_PROGRESS: verbose shows all, compact suppresses, quiet suppresses.


def _planning_announce(request, target, repo, name, *, planner_model=None,
                       prior_learnings=None, env_survey=None, base_sha=None):
    """Emit planning announcements to stderr (verbose only) + progress.jsonl (always).
    Called from run_task after the worktree is created but before the charter dispatch."""
    level = loop._progress_level()
    branch_info = ""
    if base_sha:
        branch_info = f" @ {base_sha[:7]}"

    lines = [
        ("🧭 planning loop beginning", None),
        ("  request", request[:120] + ("..." if len(request) > 120 else "")),
        ("  target", str(target)),
        ("  branch", f"devloop/{name}{branch_info}"),
    ]
    if planner_model:
        lines.append(("  planner", planner_model))
    if prior_learnings is not None:
        lines.append(("  prior learnings",
                       f"{len(prior_learnings)} lesson(s)" if prior_learnings else "none (fresh workspace)"))
    else:
        lines.append(("  prior learnings", "none (fresh workspace)"))
    if env_survey is not None:
        n_mods = len(env_survey) if isinstance(env_survey, (list, dict)) else 0
        lines.append(("  env survey", f"{n_mods} module(s) found" if n_mods else "empty (greenfield)"))
    else:
        lines.append(("  env survey", "empty (greenfield)"))

    for label, detail in lines:
        if level >= loop._LEVEL_VERBOSE:
            if detail is None:
                print(f"[devloop] {label}", file=sys.stderr, flush=True)
            else:
                print(f"[devloop] {label}: {detail}", file=sys.stderr, flush=True)


# ── Pre-clarify hook (2026-07-08) ──────────────────────────────────────────
# When devloop is called DIRECTLY (not through the scout pipeline), the request
# may be underspecified. NBQ fast-ranks whether clarification is needed; if so,
# the investigator researches the top questions and produces a refined prompt.
# When devloop is called through scout, the scout's own clarify phase already
# resolved these unknowns, so NBQ will find an empty bucket and skip (no
# duplication). See references/nbq-investigator-integration.md.

def _pre_clarify(request, target_dir, run_dir=None, floor=0.30):
    """Check if the request is underspecified; if so, refine it via investigator.

    Returns the refined prompt string, or None if the request is well-specified
    (NBQ bucket empty or all questions below floor). The NBQ fast-rank call is
    the gate — one model call determines whether the heavier investigator loop
    is warranted.
    """
    try:
        import json as _json
        # Resolve NBQ scripts dir
        home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
        nbq_dir = os.path.join(home, "skills", "autonomous-ai-agents",
                               "next-best-questions", "scripts")
        if not os.path.isdir(nbq_dir):
            return None  # NBQ not installed — skip gracefully
        if nbq_dir not in sys.path:
            sys.path.insert(0, nbq_dir)
        import infogain  # noqa: E402

        # Fast-rank: single model call, returns ranked questions
        cfg = infogain.eval_cfg("glm")  # all stages pinned to glm
        cfg["auto_derive"] = False      # don't derive — just rank
        result = infogain.run(request, cfg)
        # NBQ returns "bucket" (surviving questions) and "all_scored" (all candidates)
        questions = result.get("bucket") or result.get("all_scored") or result.get("questions", [])
        above_floor = [q for q in questions
                       if (q.get("value") or 0) >= floor
                       and q.get("gated_out") is not True
                       and q.get("recommendation") not in ("REDUNDANT", "SKIP")]

        if not above_floor:
            if run_dir:
                loop._progress_event(run_dir, "pre_clarify", ok=True,
                    detail="well-specified, skipping investigator")
            level = loop._progress_level()
            if level >= loop._LEVEL_VERBOSE:
                print(f"[devloop] ✅ pre_clarify: well-specified, skipping investigator",
                      file=sys.stderr, flush=True)
            return None

        # Questions above floor → run investigator in quick mode
        n_above = len(above_floor)
        if run_dir:
            loop._progress_event(run_dir, "pre_clarify", ok=None,
                detail=f"{n_above} questions above floor, investigating...")
        level = loop._progress_level()
        if level >= loop._LEVEL_VERBOSE:
            print(f"[devloop] ⏳ pre_clarify: {n_above} questions above floor, investigating...",
                  file=sys.stderr, flush=True)

        inv_dir = os.path.join(home, "skills", "autonomous-ai-agents",
                               "investigator", "scripts")
        if inv_dir not in sys.path:
            sys.path.insert(0, inv_dir)
        import iterate  # noqa: E402

        inv_result = iterate.iterate(
            request,
            cfg={
                "k": 2, "max_rounds": 1, "floor": floor,
                "output": "prompt", "fast_rank": True,
                "capability": "read",  # read-only — don't modify the repo
                "answer_cwd": target_dir,
            })

        refined = inv_result.get("refined_prompt") or inv_result.get("response")
        n_answered = sum(1 for t in inv_result.get("tombstones", [])
                         if t.get("kind") == "answered")
        n_gaps = sum(1 for t in inv_result.get("tombstones", [])
                     if t.get("kind") == "not_found")

        if run_dir:
            loop._progress_event(run_dir, "pre_clarify", ok=True,
                detail=f"refined request with {n_answered} fact(s), {n_gaps} gap(s)")
        if level >= loop._LEVEL_VERBOSE:
            print(f"[devloop] ✅ pre_clarify: refined request with "
                  f"{n_answered} fact(s), {n_gaps} gap(s)",
                  file=sys.stderr, flush=True)

        return refined if refined else None

    except Exception as e:
        # Pre-clarify is an enhancement, not a gate — any failure skips gracefully
        if run_dir:
            loop._progress_event(run_dir, "pre_clarify", ok=False,
                detail=f"skipped: {type(e).__name__}")
        level = loop._progress_level()
        if level >= loop._LEVEL_VERBOSE:
            print(f"[devloop] ⚠️  pre_clarify: skipped ({type(e).__name__})",
                  file=sys.stderr, flush=True)
        return None


def run_task(repo, request, root, name, *, judge_a=None, judge_b=None,
             make_charter=None, make_refiner=None, make_advisor=None,
             make_designer=None, make_implementer=None,
             pre_clarify=None, keep_worktree=False):
    # STRUCTURED test design (#17) is THE designer (the config every passing go/no-go spike ran;
    # coverage is DERIVED from rendered node ids, so a designer can't fabricate it). The legacy
    # free-form path was DELETED 2026-07-01 (zero passing-spike evidence; 5 parser accommodations).
    make_designer = make_designer or dispatch.designer_spec_via_ask
    make_implementer = make_implementer or dispatch.implementer_via_ask
    # Real 2-model assertion judges by default (judge != designer != coder, so no model grades its
    # own work). Fail fast on a model collision before any expensive work. Injected judges (tests)
    # skip this and the real dispatch.
    real_judges = judge_a is None and judge_b is None
    # The REFINE + ADVISOR passes run only on the real path; deterministic tests inject judges and
    # get no-op refiner/advisor (the scripted charter passes through unchanged).
    make_advisor = make_advisor or (dispatch.advisor_via_ask if real_judges else (lambda ch, req: ch))
    if real_judges:
        dispatch.assert_distinct_models(dispatch.CODER, dispatch.DESIGNER, dispatch.JUDGE_A, dispatch.JUDGE_B)

    wt = worktree.create_worktree(repo, name, root)
    try:
        target = wt["path"]
        # ENVIRONMENT-AWARE interpretation (user ask 2026-07-02): the default charter/refine
        # stages get the target checkout so their prompts carry an environment survey (existing
        # modules + public symbols via dispatch._environment_survey) — investigate what exists
        # BEFORE building a solve, aligning style/reuse without overriding the request. Bound
        # HERE (not at the top) because they close over the checkout path.
        if make_charter is None:
            make_charter = lambda req: dispatch.charter_via_ask(req, target_dir=target)  # noqa: E731
        if make_refiner is None:
            make_refiner = (lambda ch, req: dispatch.refiner_via_ask(ch, req, target_dir=target)) \
                if real_judges else (lambda ch, req: ch)  # noqa: E731
        if real_judges:
            judge_a = dispatch.judge_via_ask(dispatch.JUDGE_A, target)
            judge_b = dispatch.judge_via_ask(dispatch.JUDGE_B, target)
            _tiebreaker = dispatch.tiebreaker_via_ask(target_dir=target)
        else:
            judge_a = judge_a or (lambda t, c: True)
            judge_b = judge_b or (lambda t, c: True)
            _tiebreaker = None
        run_dir = os.path.join(target, ".devloop", "runs", name)   # hidden from the diff via info/exclude
        # DEVLOOP_DEBUG=1 (user ask 2026-07-03): point dispatch's prompt/reply capture at THIS
        # run's dir so the captures ride the post-run bundle. One run per process at the CLI
        # boundary, so an env pointer is race-free there.
        os.environ["DEVLOOP_DEBUG_DIR"] = run_dir

        # PLANNING ANNOUNCEMENT (Phase 1, 2026-07-06): show the user what's about to happen
        # before the first model call. In verbose mode: request, target, branch, planner, etc.
        _planning_announce(request, target, repo, name,
                           planner_model=getattr(dispatch, "PLANNER", None) if real_judges else None)

        # PRE-CLARIFY HOOK (2026-07-08): opt-in NBQ+investigator clarification
        # before the charter phase. Defaults to OFF — the existing vague_goal_gate
        # and ambiguity_gate already catch underspecification deterministically
        # (routing to HUMAN_REVIEW) without model calls. Pre-clarify is only
        # useful when a caller KNOWS their request is vague and wants the
        # investigator to refine it before charter. See references/nbq-investigator-integration.md.
        if pre_clarify:
            refined = _pre_clarify(request, target, run_dir=run_dir)
            if refined and refined != request:
                request = refined

        loop._progress_event(run_dir, "charter", detail="drafting charter...")
        charter = make_charter(request)            # DRAFT (planner)
        loop._progress_event(run_dir, "refine", detail="refining charter...")
        charter = make_refiner(charter, request)   # REFINE (atomicize)
        loop._progress_event(run_dir, "advisor", detail="advisor review...")
        charter = make_advisor(charter, request)   # ADVISORS review (blocking gaps -> open_questions)
        # POST-CHARTER ANNOUNCEMENT: show the user the decomposed DoD
        _n_crit = len(charter.get("dod", []))
        _n_assum = len(charter.get("assumptions", []))
        _n_block = sum(1 for q in charter.get("open_questions", []) if isinstance(q, dict) and q.get("blocking"))
        _tiers = {}
        for c in charter.get("dod", []):
            t = c.get("tier", "unit") if isinstance(c, dict) else "unit"
            _tiers[t] = _tiers.get(t, 0) + 1
        _tier_str = ", ".join(f"{_tiers[t]} {t}" for t in sorted(_tiers))
        loop._progress_event(run_dir, "charter_result",
                             n_criteria=_n_crit, n_assumptions=_n_assum,
                             n_blocking=_n_block, tiers=_tiers)
        if loop._progress_level() >= loop._LEVEL_VERBOSE:
            print(f"[devloop] ✅ charter: {_n_crit} criteria ({_tier_str}), "
                  f"{_n_assum} assumptions, {_n_block} blocking questions",
                  file=sys.stderr, flush=True)
            for c in charter.get("dod", []):
                if isinstance(c, dict):
                    print(f"[devloop]   {c.get('id', '?')}: {c.get('criterion', '')[:80]} "
                          f"[{c.get('tier', 'unit')}]", file=sys.stderr, flush=True)
        # VAGUE-GOAL gate first (deterministic, code-enforced): an unmeasurable quality goal or a
        # planner-fabricated benchmark routes to a human BEFORE the ambiguity gate ever weighs
        # confidences — the prompt-only version of this rule provably failed (spike_recal).
        # Gate on the ORIGINAL request only: the project loop folds prior lessons in under
        # config.LESSONS_HEADER, and lesson text carries outcome markers/numbers ("changed 3
        # file(s)", "FASTER") that would trip the marker screen on every re-attempt. The full
        # request (lessons included) still reaches the models.
        goal_text = request.split(config.LESSONS_HEADER, 1)[0]
        decision, reason = gate.vague_goal_gate(goal_text, charter)
        vague = decision != config.DECISION_PROCEED
        loop._progress_event(run_dir, "vague_goal_gate", ok=not vague, detail=reason[:60] if reason else "passed")
        if not vague:
            decision, reason = gate.ambiguity_gate(charter)

        if decision != config.DECISION_PROCEED:
            # don't even design for a charter that routes to a human. A vague-goal block is
            # deterministic on the request text itself — a re-attempt reproduces it — so it is
            # marked non-retryable and the project loop escalates instead of burning its cap;
            # an ambiguity block stays retryable (the model-drafted charter can differ next time).
            return {"result": {"terminal": "HUMAN_REVIEW", "reason": reason, "trace_path": None,
                               "retryable": not vague},
                    "worktree": wt, "charter": charter}

        try:
            # FEED ANSWERS into design time: if the request text contains "--- ANSWERS:" or
            # "— ANSWERS:", extract it so the designer sees user corrections. Without this,
            # answers given in a prior HUMAN_REVIEW round are invisible to the test designer,
            # which is why 5/5 calendar-quick-add runs failed on "test fault" — the designer
            # kept generating string-literal tests even though we answered "use real datetime objects".
            user_answers = ""
            for sep in ("— ANSWERS:", "--- ANSWERS:"):
                if sep in request:
                    user_answers = request.split(sep, 1)[1].strip()
                    break
            # Annotate charter so designer can see what was decided vs what's ambiguous.
            design_charter = dict(charter)
            if user_answers:
                design_charter["_answers"] = user_answers  # non-standard key, consumed by designer only
            test_map = make_designer(target)(design_charter)              # writes tests + REAL collected map
        except RuntimeError as e:   # e.g. pytest unavailable — an environment error, route gracefully
            return {"result": {"terminal": "HUMAN_REVIEW", "reason": str(e), "trace_path": None},
                    "worktree": wt, "charter": charter}
        verify = testgen.verify_cmd_for(testgen.invert(test_map))

        # JUDGED MID-RUN TEST REPAIR seams (user decision 2026-07-02): two independent auditors
        # (the judge models — both != coder/designer) and a REAL re-designer. The repair context
        # rides the wrong criteria's verify_intent — the structured designer prompt only reads
        # the dod entries, so charter-level notes would be invisible to it.
        def _redesign(c, wrong, details):
            wrongset = set(wrong)
            # Build per-criterion judge feedback for the designer: without this the
            # designer repeats the same mistake that caused the test fault (the root
            # cause of 5/5 calendar-quick-add failures — the redesign path was blind).
            # Now with judge_reason text (Minimax P4), the designer sees WHY judges
            # rejected — not just THAT they rejected.
            feedback_by_cid = {}
            for d in (details or []):
                cid = d.get("criterion_id", "")
                if cid:
                    ja, jb = d.get("judge_a"), d.get("judge_b")
                    # Collect reason text from both judges
                    ja_reason = d.get("judge_a_reason", "")
                    jb_reason = d.get("judge_b_reason", "")
                    reasons = []
                    if ja is False and ja_reason:
                        reasons.append(f"judge_a: {ja_reason}")
                    if jb is False and jb_reason:
                        reasons.append(f"judge_b: {jb_reason}")
                    if ja is False and jb is False:
                        base = "both judges rejected the test"
                        if reasons:
                            base += " — " + "; ".join(reasons)
                        feedback_by_cid[cid] = base
                    elif ja is False or jb is False:
                        base = "one judge rejected the test"
                        if reasons:
                            base += " — " + "; ".join(reasons)
                        feedback_by_cid[cid] = base
                    else:
                        feedback_by_cid[cid] = d.get("reason", "test rejected")
            dod2 = []
            for x in c["dod"]:
                cid = x.get("id", "")
                if cid in wrongset:
                    extra = (" [TEST-REPAIR: the previous tests for this criterion were judged "
                             "to assert the WRONG expected output — re-derive expected values "
                             "strictly from the criterion text")
                    fb = feedback_by_cid.get(cid, "")
                    if fb:
                        extra += f". Judge feedback: {fb}"
                    extra += "]"
                    dod2.append(dict(x, verify_intent=(x.get("verify_intent", "") + extra)))
                else:
                    dod2.append(x)
            # Forward user ANSWERS so the designer sees corrections from a prior
            # HUMAN_REVIEW round (e.g. "use real datetime objects not string literals").
            # Without this, the redesign repeats the same mistake.
            rc = dict(c, dod=dod2)
            if user_answers:
                rc["_answers"] = user_answers
            m2 = make_designer(target)(rc)
            return m2, testgen.verify_cmd_for(testgen.invert(m2))

        audit_a = dispatch.test_auditor_via_ask(dispatch.JUDGE_A, target) if real_judges else None
        audit_b = dispatch.test_auditor_via_ask(dispatch.JUDGE_B, target) if real_judges else None
        overfit_a = dispatch.overfit_auditor_via_ask(dispatch.JUDGE_A, target) if real_judges else None
        overfit_b = dispatch.overfit_auditor_via_ask(dispatch.JUDGE_B, target) if real_judges else None
        scope_audit = dispatch.commit_scope_auditor_via_ask() if real_judges else None
        res = loop.run_v1(charter, design=lambda c: test_map, implement=make_implementer(target),
                          judge_a=judge_a, judge_b=judge_b, verify_cmd_for=verify, run_dir=run_dir,
                          cwd=target, redesign=_redesign, audit_a=audit_a, audit_b=audit_b,
                          overfit_a=overfit_a, overfit_b=overfit_b, scope_audit=scope_audit,
                          tiebreaker=_tiebreaker)
        return {"result": res, "worktree": wt, "charter": charter}
    except BaseException as e:
        # CRASH-FINALIZE (fix 2026-07-02): any exception once the worktree exists — a dispatch
        # error, a judge-thread crash, Ctrl-C — must not leak the checkout + branch (41 of each
        # had leaked at fix time). finalize keeps a branch only if it holds real work (committed
        # for review) and removes both otherwise; best-effort so cleanup never masks the error.
        # BaseException (not Exception): KeyboardInterrupt/SystemExit must clean up too, and the
        # re-raise below preserves fail-closed routing (call_guarded / the caller sees the error).
        try:
            loop._progress_crash(run_dir, "run_v1", e)
        except Exception:   # noqa: BLE001
            pass
        if not keep_worktree:
            try:
                worktree.finalize(wt, f"devloop CRASHED ({type(e).__name__}): {name}")
            except Exception:   # noqa: BLE001 — cleanup is best-effort, never a second failure
                pass
        raise
