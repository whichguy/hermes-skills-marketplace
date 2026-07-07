"""Deterministic tests for devloop_bridge (the pipeline.py <-> devloop seam). No LLM.

Covers the kill-switch default (ON; devloop is the engine), the scratch-by-default repo policy
(no repo / None / SCRATCH -> a fresh scratch workspace, NEVER the caller's cwd), and the result
translation (COMPLETE -> auto-merge; HUMAN_REVIEW -> needs-input; NO_TERMINATION -> error).
run_task is injected so no model is ever called.
"""
import io
import json
import os
import subprocess
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import devloop_bridge as br   # noqa: E402


def _git(repo, *a):
    subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)


# --- the kill-switch: devloop is the engine now, so DEVLOOP_ENABLED DEFAULTS ON (legacy retired) --
def test_devloop_enabled_toggle():
    for v, exp in [("1", True), ("true", True), ("ON", True), ("yes", True), ("", True),
                   ("0", False), ("no", False), ("off", False), ("false", False)]:
        os.environ["DEVLOOP_ENABLED"] = v
        assert br.devloop_enabled() is exp, v
    os.environ.pop("DEVLOOP_ENABLED", None)
    assert br.devloop_enabled() is True         # ABSENT -> ON (devloop is the SDLC engine)


# --- repo policy: scratch by default (no repo / None / SCRATCH), NEVER the caller's cwd -------
def test_scratch_repo_inits_and_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        orig = br._WRITE_SAFE
        br._WRITE_SAFE = d
        try:
            repo = br._scratch_repo("greenfield1")
            assert repo == os.path.join(d, "devloop-workspaces", "greenfield1")
            assert br._is_git_repo(repo)                    # git-init'd WITH a HEAD commit (worktree-able)
            assert br._scratch_repo("greenfield1") == repo  # idempotent (no re-init crash)
        finally:
            br._WRITE_SAFE = orig


def test_run_defaults_to_scratch_and_none_is_scratch_alias():
    # THE hazard killer at the bridge layer: with no repo (or the fail-safe None alias), _run must
    # resolve to _scratch_repo — the deleted cwd-if-git fallback walked UP and could target the
    # ~/.hermes DATA repo from an agent session. Mutants killed:
    #   `if repo is SCRATCH or repo is None:` -> `if repo is SCRATCH:` (None leaks through as the repo)
    #   `if repo is SCRATCH or repo is None:` -> `if False:` (the SCRATCH sentinel leaks through)
    for passed in ("default", None, br.SCRATCH):
        scratched, seen = [], []
        fake = lambda repo_, request, root_, name: (seen.append(repo_) or {
            "result": {"terminal": "HUMAN_REVIEW", "reason": "x"}, "worktree": {}, "charter": {}})
        orig_sr, orig_ws = br._scratch_repo, br._WRITE_SAFE
        with tempfile.TemporaryDirectory() as d:
            br._WRITE_SAFE = d
            br._scratch_repo = lambda name: scratched.append(name) or "/scratch/" + name
            try:
                kwargs = {} if passed == "default" else {"repo": passed}
                br._run("greenfield thing", "build-ns", run_task=fake, **kwargs)
            finally:
                br._scratch_repo, br._WRITE_SAFE = orig_sr, orig_ws
        assert scratched == ["build-ns"], (passed, scratched)   # scratch WAS consulted
        assert seen == ["/scratch/build-ns"], (passed, seen)    # and its result is the run's repo


def test_run_explicit_repo_used_verbatim_scratch_never_consulted():
    seen = []
    fake = lambda repo_, request, root_, name: (seen.append(repo_) or {
        "result": {"terminal": "HUMAN_REVIEW", "reason": "x"}, "worktree": {}, "charter": {}})
    orig_sr, orig_ws = br._scratch_repo, br._WRITE_SAFE

    def _trap(name):
        raise AssertionError("_scratch_repo must NOT be consulted for an explicit repo")

    with tempfile.TemporaryDirectory() as d:
        br._WRITE_SAFE = d
        br._scratch_repo = _trap
        try:
            br._run("modify thing", "build-ex", run_task=fake, repo="/some/explicit/repo")
        finally:
            br._scratch_repo, br._WRITE_SAFE = orig_sr, orig_ws
    assert seen == ["/some/explicit/repo"]


# --- result translation: COMPLETE -> no error + branch-for-review summary ---------------------
def _mk_repo(root):
    repo = os.path.join(root, "repo"); os.makedirs(repo)
    for a in (["init", "-q"], ["config", "user.email", "x@y.z"], ["config", "user.name", "x"]):
        _git(repo, *a)
    open(os.path.join(repo, "README"), "w").write("r\n")
    _git(repo, "add", "."); _git(repo, "commit", "-qm", "init")
    return repo


def test_run_complete_commits_branch_removes_worktree_and_preserves_trace():
    # Lifecycle contract (deep review 2026-07-01): the run's work survives as a COMMITTED branch
    # (the review artifact), the checkout is removed (no accretion), and the trace is copied to a
    # durable path BEFORE removal. Before this, NOTHING committed (the repo's fail-closed
    # .gitignore blinded porcelain), branches were empty, and worktrees leaked forever.
    # Mutants killed: finalize `if changed:` -> `if False:` (work destroyed, branch deleted).
    import worktree as wtmod
    with tempfile.TemporaryDirectory() as d:
        repo = _mk_repo(d)

        def fake(repo_, request, root_, name):
            wt = wtmod.create_worktree(repo_, name, root_)
            open(os.path.join(wt["path"], "built.py"), "w").write("x = 1\n")
            rd = os.path.join(wt["path"], ".devloop", "runs", name)
            os.makedirs(rd)
            tp = os.path.join(rd, "trace.jsonl")
            open(tp, "w").write('{"step": "terminal", "terminal": "COMPLETE"}\n')
            open(os.path.join(rd, "charter.json"), "w").write("{}")   # a stage artifact (C7)
            grounding = {"intent": "build a thing", "grounded": True, "regression_exit": 5,
                         "criteria": [{"criterion_id": "c1", "criterion": "it builds",
                                       "tests": ["t_c1"], "judges": {"a": True, "b": True},
                                       "evidence_passed": True}]}
            return {"result": {"terminal": "COMPLETE", "reason": "DoD-SATISFIED", "trace_path": tp,
                               "grounding": grounding},
                    "worktree": wt, "charter": {}}

        orig_r, orig_ws = br._scratch_repo, br._WRITE_SAFE
        br._scratch_repo = lambda name: repo
        br._WRITE_SAFE = d
        try:
            out = br._run("build a thing", "build-x", run_task=fake)
        finally:
            br._scratch_repo, br._WRITE_SAFE = orig_r, orig_ws
        assert out["error"] is None and out["pipeline_mode"] == "devloop"
        dr = out["devloop_result"]
        # AUTO-MERGE on COMPLETE: the work LANDS in the target repo; the branch is gone (the
        # merge commit is the artifact); code_path names the deliverable.
        assert dr["terminal"] == "COMPLETE" and dr["merged"] is True
        assert dr["synced"] is False          # tip == base: fast path, no conservative re-verify
        assert dr["branch"] is None and dr["code_path"] == repo
        assert "built.py" in dr["changed_files"]
        assert os.path.isfile(os.path.join(repo, "built.py"))             # code in the target tree
        assert dr["worktree"] is None                                     # checkout removed...
        assert not os.path.isdir(os.path.join(repo, ".worktrees", "build-x"))   # ...really gone (in-repo root)
        gone = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "devloop/build-x"],
                              capture_output=True, text=True)
        assert gone.returncode != 0                                       # branch deleted post-merge
        # C7: the WHOLE run_dir becomes the durable bundle — trace + every stage artifact.
        assert dr["trace_path"] == os.path.join(d, "devloop-traces", "build-x", "trace.jsonl")
        assert os.path.isfile(dr["trace_path"])                           # durable trace survives cleanup
        assert os.path.isfile(os.path.join(d, "devloop-traces", "build-x", "charter.json"))
        assert "merged into" in out["content"]
        # GROUNDING (user ask 2026-07-02): the COMPLETE ships its promise->proof chain, both as
        # data and in the human summary. Mutants killed: grounding not threaded; summary dropped.
        assert dr["grounding"]["grounded"] is True
        assert "grounding (promise -> proof):" in out["content"]
        assert "✓ c1: it builds — 1 test(s), judges 2/2, evidence PASS" in out["content"]


def test_run_human_review_is_needs_input_not_error():
    # HUMAN_REVIEW is the engine doing its JOB (routing a gap to a human) — surfaced as a
    # needs-input outcome with the blocking questions, NOT as an error string (the old shape).
    # Mutants killed: error tuple back to ("COMPLETE",) (HR reads as error);
    # needs_human -> False (the affordance flag vanishes).
    fake = lambda repo, request, root, name: {
        "result": {"terminal": "HUMAN_REVIEW", "reason": "blocking ambiguity: which datastore?"},
        "worktree": {"path": "/nope", "branch": "devloop/build-y", "repo": repo},
        "charter": {"open_questions": [{"text": "which datastore?", "blocking": True},
                                       {"text": "advisory nit", "blocking": False}]}}
    orig_r, orig_ws = br._scratch_repo, br._WRITE_SAFE
    br._scratch_repo = lambda name: "/fake/repo"
    with tempfile.TemporaryDirectory() as d:
        br._WRITE_SAFE = d
        try:
            out = br._run("vague", "build-y", run_task=fake)
        finally:
            br._scratch_repo, br._WRITE_SAFE = orig_r, orig_ws
    assert out["error"] is None                                           # needs-input, NOT an error
    assert "NEEDS YOUR INPUT" in out["content"]
    assert "which datastore?" in out["content"]                           # the blocking question surfaces
    assert "advisory nit" not in out["content"]                           # advisory noise does not
    dr = out["devloop_result"]
    assert dr["needs_human"] is True and dr["open_questions"] == ["which datastore?"]
    assert dr["terminal"] == "HUMAN_REVIEW" and dr["branch"] is None      # no artifact -> no branch
    assert dr["merged"] is False and dr["code_path"] is None              # HR NEVER merges


def test_run_no_termination_stays_error():
    fake = lambda repo, request, root, name: {
        "result": {"terminal": "NO_TERMINATION", "reason": "bug sentinel"},
        "worktree": {}, "charter": {}}
    orig_r, orig_ws = br._scratch_repo, br._WRITE_SAFE
    br._scratch_repo = lambda name: "/fake/repo"
    with tempfile.TemporaryDirectory() as d:
        br._WRITE_SAFE = d
        try:
            out = br._run("x", "build-z", run_task=fake)
        finally:
            br._scratch_repo, br._WRITE_SAFE = orig_r, orig_ws
    assert out["error"] == "bug sentinel"                                 # a real failure stays an error
    assert out["devloop_result"]["needs_human"] is False


def test_honor_timeout_is_raise_only():
    # A caller timeout can only LIFT the per-call ceiling (project policy: never shorten
    # timeouts): below-floor values must NOT set the env; garbage is ignored.
    orig = os.environ.pop("DEVLOOP_DISPATCH_TIMEOUT_S", None)
    try:
        br._honor_timeout(300)                                            # pipeline default; below floor
        assert "DEVLOOP_DISPATCH_TIMEOUT_S" not in os.environ
        br._honor_timeout(7200)
        assert os.environ["DEVLOOP_DISPATCH_TIMEOUT_S"] == "7200"         # above floor -> lifts ceiling
        br._honor_timeout("junk")
        assert os.environ["DEVLOOP_DISPATCH_TIMEOUT_S"] == "7200"         # garbage ignored
    finally:
        if orig is None:
            os.environ.pop("DEVLOOP_DISPATCH_TIMEOUT_S", None)
        else:
            os.environ["DEVLOOP_DISPATCH_TIMEOUT_S"] = orig


# --- entrypoints: build passes the message; debug folds code+error into the request -----------
def test_run_build_passes_message_and_names():
    captured = {}
    orig = br._run
    br._run = lambda request, name, **k: captured.update(request=request, name=name) or {}
    try:
        br.run_build("build a REST API")
        assert captured["request"] == "build a REST API" and captured["name"].startswith("build-")
    finally:
        br._run = orig


def test_run_debug_folds_code_and_error_into_request():
    captured = {}
    orig = br._run
    br._run = lambda request, name, **k: captured.update(request=request, name=name) or {}
    try:
        br.run_debug("fix the bug", code="def f(): pass", error_feedback="AssertionError: x")
        req = captured["request"]
        assert "fix the bug" in req
        assert "CURRENT CODE:" in req and "def f(): pass" in req
        assert "ERROR" in req and "AssertionError: x" in req
        assert captured["name"].startswith("debug-")
    finally:
        br._run = orig


def test_run_complete_merge_conflict_falls_back_to_branch_for_review():
    # A conflicting target advance mid-run, with the LLM resolver DECLINING -> the auto-merge
    # fails SAFELY: branch kept for review, target tree clean, content says why. The resolver
    # and fixer are stubbed (returning False) so no real dispatch fires — the live LLM path is
    # covered by worktree tests with stub resolvers. Mutant killed: degrade path pinned.
    import worktree as wtmod
    with tempfile.TemporaryDirectory() as d:
        repo = _mk_repo(d)

        def fake(repo_, request, root_, name):
            wt = wtmod.create_worktree(repo_, name, root_)
            open(os.path.join(wt["path"], "c.py"), "w").write("v = 1\n")
            # conflicting advance on the TARGET after the fork
            open(os.path.join(repo_, "c.py"), "w").write("v = 999\n")
            _git(repo_, "add", "."); _git(repo_, "commit", "-qm", "conflicting advance")
            return {"result": {"terminal": "COMPLETE", "reason": "DoD-SATISFIED", "trace_path": None},
                    "worktree": wt, "charter": {}}

        orig_r, orig_ws = br._scratch_repo, br._WRITE_SAFE
        orig_res, orig_fix = br._conflict_resolver, br._merge_fixer
        br._scratch_repo = lambda name: repo
        br._WRITE_SAFE = d
        br._conflict_resolver = lambda path, conflicted: False            # LLM declines -> degrade
        br._merge_fixer = lambda path, why: False
        try:
            out = br._run("build c", "build-cf", run_task=fake)
        finally:
            br._scratch_repo, br._WRITE_SAFE = orig_r, orig_ws
            br._conflict_resolver, br._merge_fixer = orig_res, orig_fix
        dr = out["devloop_result"]
        assert dr["merged"] is False and dr["branch"] == "devloop/build-cf"   # kept for review
        assert dr["code_path"] is None
        assert "auto-merge failed" in out["content"]
        porcelain = subprocess.run(["git", "-C", repo, "status", "--porcelain"],
                                   capture_output=True, text=True).stdout.strip()
        assert porcelain == ""                                            # never a conflicted tree
        assert open(os.path.join(repo, "c.py")).read() == "v = 999\n"     # target untouched


def test_run_build_and_debug_thread_repo():
    captured = {}
    orig = br._run
    br._run = lambda request, name, **k: captured.update(request=request, name=name, **k) or {}
    try:
        br.run_build("build it", repo="/some/repo")
        assert captured["repo"] == "/some/repo"
        br.run_debug("fix it", repo=br.SCRATCH)
        assert captured["repo"] is br.SCRATCH
        br.run_build("build default")                       # no repo -> the SCRATCH default
        assert captured["repo"] is br.SCRATCH
        br.run_debug("debug default")
        assert captured["repo"] is br.SCRATCH
    finally:
        br._run = orig


def test_scratch_repo_inits_own_git_inside_enclosing_repo():
    # THE live acceptance-run catch (2026-07-01): the write-safe root sits INSIDE the ~/.hermes
    # data repo, so _is_git_repo's upward walk made _scratch_repo a silent no-op — every
    # "scratch workspace" resolved to the DATA repo and run branches were cut off it. The scratch
    # builder must create its OWN .git even when nested in an enclosing repository.
    # Mutant killed: own-.git check -> _is_git_repo (upward walk resurrected).
    with tempfile.TemporaryDirectory() as d:
        _git(d, "init", "-q")                                   # the enclosing "data repo"
        orig_ws = br._WRITE_SAFE
        br._WRITE_SAFE = os.path.join(d, "write-safe")          # nested inside it
        try:
            repo = br._scratch_repo("greenfield-nested")
        finally:
            br._WRITE_SAFE = orig_ws
        top = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True).stdout.strip()
        assert os.path.realpath(top) == os.path.realpath(repo)  # its OWN repo, not the enclosing one
        head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                              capture_output=True, text=True)
        assert head.returncode == 0                             # has a HEAD (worktree-able)


# --- fail-closed guard: failure_result / call_guarded (deep review 2026-07-01) -----------------
def test_failure_result_is_human_review_shaped_with_error():
    # Mutants killed: failure_result terminal -> "COMPLETE" (a broken engine reads as success)
    # and error -> None (the failure vanishes from pipeline_status).
    out = br.failure_result("kaboom")
    assert out["devloop_result"]["terminal"] == "HUMAN_REVIEW"
    assert out["error"] == "kaboom"
    assert "FAILED CLOSED" in out["content"]
    assert out["devloop_result"]["changed_files"] == []


def test_failure_result_shape_matches_run_shape():
    # ONE HUMAN_REVIEW dialect: failure_result must expose the same devloop_result keys as _run
    # (a consumer indexing needs_human/open_questions must never KeyError on a crash result), and
    # needs_human must be False — an engine CRASH is a failure (CLI exit 1), not a needs-input
    # outcome (exit 2). Mutant killed: `"needs_human": False` -> True (crash masquerades as
    # needs-input at the shell boundary).
    fake = lambda repo_, request, root_, name: {
        "result": {"terminal": "HUMAN_REVIEW", "reason": "x"}, "worktree": {}, "charter": {}}
    orig_sr, orig_ws = br._scratch_repo, br._WRITE_SAFE
    br._scratch_repo = lambda name: "/fake/repo"
    with tempfile.TemporaryDirectory() as d:
        br._WRITE_SAFE = d
        try:
            run_shape = br._run("x", "shape-probe", run_task=fake)["devloop_result"]
        finally:
            br._scratch_repo, br._WRITE_SAFE = orig_sr, orig_ws
    crash_shape = br.failure_result("kaboom")["devloop_result"]
    assert set(crash_shape) == set(run_shape), (set(crash_shape) ^ set(run_shape))
    assert crash_shape["needs_human"] is False and crash_shape["open_questions"] == []


def test_call_guarded_passthrough_and_fail_closed():
    ok = {"content": "fine", "error": None}
    assert br.call_guarded(lambda m, timeout=None: ok, "msg", timeout=3) is ok   # passthrough
    def _boom(m, timeout=None):
        raise RuntimeError("engine exploded")
    out = br.call_guarded(_boom, "msg", timeout=3)
    assert out["error"].startswith("devloop runtime error: RuntimeError")
    assert out["devloop_result"]["terminal"] == "HUMAN_REVIEW"                   # fail-closed, never success


# --- pipeline.py seam: the three-way split (import-broke / kill-switch / live-guarded) ---------
def _import_pipeline():
    ask_scripts = os.path.normpath(os.path.join(_DIR, "..", "..", "productivity", "ask", "scripts"))
    if not os.path.isfile(os.path.join(ask_scripts, "pipeline.py")):
        return None
    if ask_scripts not in sys.path:
        sys.path.insert(0, ask_scripts)
    try:
        import pipeline
        return pipeline
    except Exception:      # missing ask-side deps (host run) -> skip, the container run covers it
        return None


def _run_pipeline_with(pl, *, bridge, import_error=None, env_enabled=None, run_build=None):
    """Drive run_pipeline with scripted triage/routing (no LLM, no network) and a trapped
    dispatch_single; returns (result, single_dispatch_calls)."""
    calls = []
    orig = (pl.devloop_bridge, getattr(pl, "DEVLOOP_IMPORT_ERROR", None), pl.dispatch_single,
            pl.triage.classify, pl.routing.route, os.environ.get("DEVLOOP_ENABLED"),
            br.run_build)
    pl.devloop_bridge = bridge
    pl.DEVLOOP_IMPORT_ERROR = import_error
    pl.dispatch_single = lambda *a, **k: (calls.append(1) or
                                          {"content": "single", "error": None, "session_id": None, "elapsed": 0.0})
    pl.triage.classify = lambda message, timeout=None: {
        "category": "build_code", "confidence": "high", "raw_output": "t", "tokens": 0,
        "elapsed": 0, "elapsed_first": 0.0, "elapsed_retry": 0.0}
    pl.routing.route = lambda tr, user_context=None: {
        "skill": "dev", "model": "kimi", "thinking": None, "toolsets": "file",
        "role": "coder", "pipeline": "test_first"}
    if env_enabled is None:
        os.environ.pop("DEVLOOP_ENABLED", None)
    else:
        os.environ["DEVLOOP_ENABLED"] = env_enabled
    if run_build is not None:
        br.run_build = run_build
    try:
        out = pl.run_pipeline("build the widget", dry_run=False)
    finally:
        (pl.devloop_bridge, pl.DEVLOOP_IMPORT_ERROR, pl.dispatch_single,
         pl.triage.classify, pl.routing.route) = orig[0], orig[1], orig[2], orig[3], orig[4]
        if orig[5] is None:
            os.environ.pop("DEVLOOP_ENABLED", None)
        else:
            os.environ["DEVLOOP_ENABLED"] = orig[5]
        br.run_build = orig[6]
    return out, calls


def test_pipeline_import_broke_fails_closed_not_single_shot():
    # The former behavior (import-broke -> silent single dispatch labeled pipeline_success) was a
    # live 0-false-complete violation. Now: FAILED dispatch, HUMAN_REVIEW-shaped, single-shot
    # dispatch NEVER runs.
    pl = _import_pipeline()
    if pl is None:
        print("SKIP test_pipeline_import_broke_fails_closed_not_single_shot (ask pipeline unavailable)"); return
    out, calls = _run_pipeline_with(pl, bridge=None, import_error="ImportError: boom")
    assert calls == []                                          # never degraded to single-shot
    assert out["pipeline_success"] is False
    assert out["pipeline_status"] == "dispatch_failed"
    assert "devloop unavailable" in (out.get("error") or out["dispatch_result"]["error"])
    assert out["dispatch_result"]["devloop_result"]["terminal"] == "HUMAN_REVIEW"


def test_pipeline_kill_switch_is_the_one_intentional_fallback():
    pl = _import_pipeline()
    if pl is None:
        print("SKIP test_pipeline_kill_switch_is_the_one_intentional_fallback (ask pipeline unavailable)"); return
    out, calls = _run_pipeline_with(pl, bridge=br, env_enabled="0")
    assert calls == [1]                                         # operator-disabled -> single dispatch ran
    assert out["pipeline_success"] is True
    assert out["dispatch_result"]["content"] == "single"


def test_pipeline_passes_scratch_repo_explicitly():
    # The chat seam is the surface where an implicit repo default would be most dangerous (the
    # pipeline's cwd can be inside the ~/.hermes data repo). pipeline.py must pass the SCRATCH
    # sentinel EXPLICITLY — defense in depth over the bridge-side default.
    pl = _import_pipeline()
    if pl is None:
        print("SKIP test_pipeline_passes_scratch_repo_explicitly (ask pipeline unavailable)"); return
    seen = {}

    def _capture(message, timeout=None, repo="MISSING", **k):
        seen["repo"] = repo
        return {"content": "devloop COMPLETE — x", "error": None, "session_id": None,
                "elapsed": 0.0, "devloop_result": {"terminal": "COMPLETE"},
                "pipeline_mode": "devloop"}

    out, calls = _run_pipeline_with(pl, bridge=br, run_build=_capture)
    assert calls == []                                          # devloop handled it, no single-shot
    assert seen["repo"] is br.SCRATCH                           # explicit sentinel, not None/missing
    assert out["pipeline_success"] is True


def test_pipeline_bridge_runtime_error_fails_closed():
    pl = _import_pipeline()
    if pl is None:
        print("SKIP test_pipeline_bridge_runtime_error_fails_closed (ask pipeline unavailable)"); return
    def _boom(message, timeout=None, **k):
        raise RuntimeError("HERMES_BIN missing")
    out, calls = _run_pipeline_with(pl, bridge=br, run_build=_boom)
    assert calls == []                                          # no silent single-shot on a runtime error
    assert out["pipeline_success"] is False
    assert out["pipeline_status"] == "dispatch_failed"
    assert "devloop runtime error" in out["dispatch_result"]["error"]
    assert out["dispatch_result"]["devloop_result"]["terminal"] == "HUMAN_REVIEW"


def test_summary_shows_excluded_scratch():
    # P2: the human summary names what the commit-scope gate excluded.
    out = br._summary("COMPLETE", {"branch": None}, "", [], None,
                      {"merged": True, "target": "master"}, None,
                      scope_dropped=["notes.md"])
    assert "excluded 1 scratch file(s) from the commit: notes.md" in out


def test_summary_renders_partial_grounding_on_human_review():
    # C8: the ✗ rows on a failed terminal say exactly which promises were left unproven.
    # Mutant killed: grounding block re-gated to COMPLETE-only.
    g = {"grounded": False, "criteria": [
        {"criterion_id": "c1", "criterion": "does X", "tests": [],
         "judges": {"a": False, "b": True}, "evidence_passed": False}]}
    out = br._summary("HUMAN_REVIEW", {"branch": None}, "stuck", [], None, None, g)
    assert "grounding (promise -> proof):" in out
    assert "✗ c1: does X — 0 test(s), judges 1/2, evidence FAIL" in out


def test_run_complete_keep_branch_skips_merge_keeps_branch():
    # C5: keep_branch=True on a COMPLETE run — the auto-merge is NOT attempted, the verified
    # branch survives, kept_branch is reported, and the summary prints the manual merge command.
    # Mutant killed: keep_branch no longer skips the merge.
    import worktree as wtmod
    with tempfile.TemporaryDirectory() as d:
        repo = _mk_repo(d)

        def fake(repo_, request, root_, name):
            wt = wtmod.create_worktree(repo_, name, root_)
            open(os.path.join(wt["path"], "c.py"), "w").write("v = 1\n")
            return {"result": {"terminal": "COMPLETE", "reason": "DoD-SATISFIED", "trace_path": None},
                    "worktree": wt, "charter": {}}

        orig_r, orig_ws = br._scratch_repo, br._WRITE_SAFE
        br._scratch_repo = lambda name: repo
        br._WRITE_SAFE = d
        try:
            out = br._run("build c", "build-kb", run_task=fake, keep_branch=True)
        finally:
            br._scratch_repo, br._WRITE_SAFE = orig_r, orig_ws
        dr = out["devloop_result"]
        assert dr["kept_branch"] is True and dr["merged"] is False
        assert dr["branch"] == "devloop/build-kb"                # the branch IS the deliverable
        assert out["error"] is None
        assert "kept as requested" in out["content"] and "merge --squash" in out["content"]
        assert not os.path.exists(os.path.join(repo, "c.py"))    # target untouched
        merges = subprocess.run(["git", "-C", repo, "log", "--merges", "--oneline"],
                                capture_output=True, text=True).stdout.strip()
        assert merges == ""                                      # no merge commit was created


def test_run_complete_refuses_merge_when_target_switched_branches_mid_run():
    # C3: the bridge threads wt["start_branch"] into merge_branch(expected_branch=...) — if the
    # user's checkout switched branches while the run was in flight, the COMPLETE work must stay
    # on its devloop/ branch instead of landing on the wrong branch. Mutant killed:
    # expected_branch threading dropped (merge would land on 'hotfix' and report merged=True).
    import worktree as wtmod
    with tempfile.TemporaryDirectory() as d:
        repo = _mk_repo(d)

        def fake(repo_, request, root_, name):
            wt = wtmod.create_worktree(repo_, name, root_)
            open(os.path.join(wt["path"], "c.py"), "w").write("v = 1\n")
            _git(repo_, "checkout", "-qb", "hotfix")        # user switches branches mid-run
            return {"result": {"terminal": "COMPLETE", "reason": "DoD-SATISFIED", "trace_path": None},
                    "worktree": wt, "charter": {}}

        orig_r, orig_ws = br._scratch_repo, br._WRITE_SAFE
        br._scratch_repo = lambda name: repo
        br._WRITE_SAFE = d
        try:
            out = br._run("build c", "build-sw", run_task=fake)
        finally:
            br._scratch_repo, br._WRITE_SAFE = orig_r, orig_ws
        dr = out["devloop_result"]
        assert dr["merged"] is False and dr["branch"] == "devloop/build-sw"   # kept for review
        assert "switched" in out["content"]
        assert not os.path.exists(os.path.join(repo, "c.py"))    # nothing landed on 'hotfix'


def test_run_persists_schema_diagnostic_event_stream():
    import worktree as wtmod
    with tempfile.TemporaryDirectory() as d:
        repo = _mk_repo(d)

        def fake(repo_, request, root_, name):
            wt = wtmod.create_worktree(repo_, name, root_)
            open(os.path.join(wt["path"], "built.py"), "w").write("x = 1\n")
            return {"result": {"terminal": "COMPLETE", "reason": "DoD-SATISFIED",
                               "trace_path": None},
                    "worktree": wt, "charter": {}}

        orig_r, orig_ws = br._scratch_repo, br._WRITE_SAFE
        br._scratch_repo = lambda name: repo
        br._WRITE_SAFE = d
        try:
            br._run("build a thing", "build-events", run_task=fake)
        finally:
            br._scratch_repo, br._WRITE_SAFE = orig_r, orig_ws
        events_path = os.path.join(d, "devloop-traces", "build-events", "events.jsonl")
        assert os.path.isfile(events_path)
        entries = [json.loads(line) for line in open(events_path) if line.strip()]
        assert entries
        assert [entry["seq"] for entry in entries] == list(range(len(entries)))
        required = {"ts", "seq", "run", "phase", "step", "level", "rc", "detail", "outcome"}
        assert all(required <= set(entry) for entry in entries)
        assert all(entry["run"] == "build-events" for entry in entries)


def _run_refused_merge_with_debug(debug):
    import worktree as wtmod
    with tempfile.TemporaryDirectory() as d:
        repo = _mk_repo(d)

        def fake(repo_, request, root_, name):
            wt = wtmod.create_worktree(repo_, name, root_)
            open(os.path.join(wt["path"], "c.py"), "w").write("v = 1\n")
            _git(repo_, "checkout", "-qb", "hotfix")
            return {"result": {"terminal": "COMPLETE", "reason": "DoD-SATISFIED",
                               "trace_path": None},
                    "worktree": wt, "charter": {}}

        orig_r, orig_ws, orig_stderr = br._scratch_repo, br._WRITE_SAFE, sys.stderr
        prior_debug = os.environ.get("DEVLOOP_DEBUG")
        br._scratch_repo = lambda name: repo
        br._WRITE_SAFE = d
        captured = io.StringIO()
        sys.stderr = captured
        if debug:
            os.environ["DEVLOOP_DEBUG"] = "1"
        else:
            os.environ.pop("DEVLOOP_DEBUG", None)
        try:
            br._run("build c", "build-debug", run_task=fake)
        finally:
            br._scratch_repo, br._WRITE_SAFE, sys.stderr = orig_r, orig_ws, orig_stderr
            if prior_debug is None:
                os.environ.pop("DEVLOOP_DEBUG", None)
            else:
                os.environ["DEVLOOP_DEBUG"] = prior_debug
        return captured.getvalue()


def test_run_debug_echoes_warning_events_to_stderr():
    stderr = _run_refused_merge_with_debug(True)
    assert "[devloop:build-debug] WARN merge/branch-switched:" in stderr


def test_run_without_debug_keeps_diagnostic_stderr_quiet():
    assert _run_refused_merge_with_debug(False) == ""


# --- rich learnings journaling (user ask 2026-07-05) ----------------------------------------

def test_extract_commit_section_finds_learnings():
    msg = (
        "devloop COMPLETE: build-x\n\n"
        "INTENTION:\n  Build a calendar API\n\n"
        "THESIS:\n  All gates passed\n\n"
        "LEARNINGS:\n"
        "  - External integration tests must hit the REAL binary\n"
        "  AVOID: mocking subprocess wrappers hides real failures\n\n"
        "REFERENCES:\n"
        "  Trace: /tmp/trace.jsonl\n"
        "  Prior: abc1234\n"
    )
    learnings = br._extract_commit_section(msg, "LEARNINGS")
    assert "External integration tests" in learnings
    assert "AVOID:" in learnings
    # Must NOT bleed into the next section
    assert "REFERENCES" not in learnings
    assert "Trace:" not in learnings


def test_extract_commit_section_finds_references():
    msg = (
        "devloop COMPLETE: build-x\n\n"
        "INTENTION:\n  Build a thing\n\n"
        "REFERENCES:\n"
        "  Trace: /tmp/t.jsonl\n"
        "  Prior: abc1234\n"
    )
    refs = br._extract_commit_section(msg, "REFERENCES")
    assert "abc1234" in refs
    assert "Trace:" in refs


def test_extract_commit_section_missing_returns_empty():
    assert br._extract_commit_section("no sections here", "LEARNINGS") == ""
    assert br._extract_commit_section("", "LEARNINGS") == ""


def test_extract_commit_section_case_insensitive():
    msg = "learnings:\n  - did a thing\n"
    assert "did a thing" in br._extract_commit_section(msg, "LEARNINGS")


def test_extract_failure_conditions_from_avoid_lines():
    # P1-3: only lines starting with AVOID: or DO NOT are extracted — not substring matches
    learnings = (
        "  - AVOID: mocking subprocess hides real failures\n"
        "  - Integration tests should hit real binaries\n"
        "  - DO NOT skip the regression gate\n"
        "  - Happy path works fine\n"
        "  - The judge correctly rejected weak substring assertions\n"
    )
    fcs = br._extract_failure_conditions(learnings, "COMPLETE", "")
    assert any("mocking subprocess" in fc for fc in fcs)
    assert any("regression" in fc.lower() for fc in fcs)
    # P1-3: positive observations should NOT be captured even if they contain
    # failure-signal words like "rejected"
    assert not any("judge correctly rejected" in fc for fc in fcs)
    assert not any("Happy path" in fc for fc in fcs)
    # Non-prefixed "Integration tests should hit real binaries" is NOT a failure condition
    assert not any("Integration tests should" in fc for fc in fcs)


def test_extract_failure_conditions_includes_reason_on_failure():
    fcs = br._extract_failure_conditions("", "NO_TERMINATION",
                                          "subprocess timeout — the binary hung")
    assert any("subprocess timeout" in fc for fc in fcs)
    assert all(fc.startswith("DO NOT repeat:") for fc in fcs)


def test_extract_failure_conditions_empty_on_success_with_no_failure_lines():
    fcs = br._extract_failure_conditions(
        "  - All tests passed\n  - Clean build\n", "COMPLETE", "")
    assert fcs == []


def test_append_run_learning_journals_rich_fields():
    """The journal entry must carry learnings_text, references, and failure_conditions
    when a commit message is provided — not just the mechanical status line."""
    with tempfile.TemporaryDirectory() as d:
        orig_ws = br._WRITE_SAFE
        br._WRITE_SAFE = d
        try:
            commit_msg = (
                "devloop COMPLETE: build-rich\n\n"
                "INTENTION:\n  Build a calendar API\n\n"
                "THESIS:\n  All gates passed\n\n"
                "LEARNINGS:\n"
                "  - Integration tests must hit real binaries\n"
                "  AVOID: mocking subprocess hides failures\n\n"
                "REFERENCES:\n"
                "  Trace: /tmp/trace.jsonl\n"
                "  Prior: abc1234\n"
            )
            result = {"grounding": {"criteria": [{"judges": {"a": True, "b": True}}]},
                      "rebuilds": 0}
            br._append_run_learning("build-rich", "Build a calendar API", result,
                                    "COMPLETE", "DoD-SATISFIED", commit_msg=commit_msg)
            # Read back the journal
            import state as _state
            lj = os.path.join(d, "devloop-traces", "LEARNINGS.jsonl")
            entries = _state.read_learnings(lj, last_n=10)
            assert len(entries) == 1
            e = entries[0]
            # Mechanical status fields (in their own fields, NOT the lesson)
            assert e["terminal"] == "COMPLETE"
            assert e["n_trusted"] == 1
            # The lesson field is now DESIGN content, not a status line.
            # With rich learnings_text, the lesson IS the learnings content.
            assert "Integration tests" in e["lesson"]
            assert "[COMPLETE]" not in e["lesson"]     # NOT a status line
            # Rich fields
            assert "Integration tests" in e["learnings_text"]
            assert "abc1234" in e["references"]
            assert any("mocking subprocess" in fc for fc in e["failure_conditions"])
        finally:
            br._WRITE_SAFE = orig_ws


def test_append_run_learning_without_commit_msg_still_journals_failure_from_reason():
    """Even without a commit message, a failed run's reason is journaled as a failure condition."""
    with tempfile.TemporaryDirectory() as d:
        orig_ws = br._WRITE_SAFE
        br._WRITE_SAFE = d
        try:
            result = {"grounding": {}, "rebuilds": 2}
            br._append_run_learning("build-fail", "Build it", result,
                                    "NO_TERMINATION", "subprocess hung on timeout")
            import state as _state
            lj = os.path.join(d, "devloop-traces", "LEARNINGS.jsonl")
            entries = _state.read_learnings(lj, last_n=10)
            assert len(entries) == 1
            e = entries[0]
            assert e["learnings_text"] == ""       # no commit msg -> empty
            assert e["references"] == ""
            assert any("subprocess hung" in fc for fc in e["failure_conditions"])
            # The lesson field is design-oriented: a failure records a REFUTED THESIS
            assert "REFUTED THESIS" in e["lesson"]
            assert "subprocess hung" in e["lesson"]
        finally:
            br._WRITE_SAFE = orig_ws


def test_append_run_learning_back_compat_no_crash_without_commit_msg():
    """Old callers that don't pass commit_msg must still work (no crash, mechanical fields only)."""
    with tempfile.TemporaryDirectory() as d:
        orig_ws = br._WRITE_SAFE
        br._WRITE_SAFE = d
        try:
            result = {"grounding": {}, "rebuilds": 0}
            br._append_run_learning("build-old", "Build it", result, "COMPLETE", "")
            import state as _state
            lj = os.path.join(d, "devloop-traces", "LEARNINGS.jsonl")
            entries = _state.read_learnings(lj, last_n=10)
            assert len(entries) == 1
            e = entries[0]
            assert "lesson" in e                    # design-oriented lesson present
            assert "Confirmed approach" in e["lesson"]   # NOT a status line
            # P1-5: no status metrics (rebuilds) in the lesson field
            assert "rebuild" not in e["lesson"].lower()
            assert e["learnings_text"] == ""        # rich fields default to empty
            assert e["failure_conditions"] == []
        finally:
            br._WRITE_SAFE = orig_ws


def test_rich_journaling_reorder_commit_msg_built_before_append():
    """Integration: _run must build the commit message BEFORE appending the learning,
    so the rich fields are populated. We verify by checking the journal after a COMPLETE run."""
    import worktree as wtmod
    with tempfile.TemporaryDirectory() as d:
        repo = _mk_repo(d)

        def fake(repo_, request, root_, name):
            wt = wtmod.create_worktree(repo_, name, root_)
            open(os.path.join(wt["path"], "built.py"), "w").write("x = 1\n")
            rd = os.path.join(wt["path"], ".devloop", "runs", name)
            os.makedirs(rd)
            tp = os.path.join(rd, "trace.jsonl")
            open(tp, "w").write('{"step": "terminal", "terminal": "COMPLETE"}\n')
            grounding = {"criteria": [{"criterion_id": "c1", "criterion": "it builds",
                          "tests": ["t_c1"], "judges": {"a": True, "b": True},
                          "evidence_passed": True}]}
            return {"result": {"terminal": "COMPLETE", "reason": "DoD-SATISFIED",
                               "trace_path": tp, "grounding": grounding},
                    "worktree": wt, "charter": {}}

        orig_r, orig_ws = br._scratch_repo, br._WRITE_SAFE
        orig_no_commit = os.environ.get("DEVLOOP_NO_COMMIT_LLM")
        br._scratch_repo = lambda name: repo
        br._WRITE_SAFE = d
        os.environ["DEVLOOP_NO_COMMIT_LLM"] = "1"   # skip real LLM, use template fallback
        try:
            br._run("build a thing", "build-rich-run", run_task=fake)
        finally:
            br._scratch_repo, br._WRITE_SAFE = orig_r, orig_ws
            if orig_no_commit is None:
                os.environ.pop("DEVLOOP_NO_COMMIT_LLM", None)
            else:
                os.environ["DEVLOOP_NO_COMMIT_LLM"] = orig_no_commit
        # The journal should have an entry with rich fields populated from the template
        # fallback commit message (which has LEARNINGS: and REFERENCES: sections).
        import state as _state
        lj = os.path.join(d, "devloop-traces", "LEARNINGS.jsonl")
        entries = _state.read_learnings(lj, last_n=10)
        assert len(entries) >= 1
        e = entries[-1]
        assert e["terminal"] == "COMPLETE"
        assert e["learnings_text"] != "" or e["references"] != ""


# --- P0/P1 fix tests (advisor review 2026-07-05) ---------------------------------------------

def test_mechanical_fallback_includes_journal_content():
    """P0-2: the mechanical fallback must include journal content, not drop it."""
    import dispatch as _dispatch
    raw_commits = [
        "=== COMMIT abc123 ===\n"
        "LEARNINGS:\n"
        "  - Integration tests must hit real binaries\n"
        "  AVOID: mocking subprocess hides failures\n"
    ]
    journal = (
        "summary: [COMPLETE] build: 3/5 trusted\n"
        "learnings: Regex parsing is insufficient for nested expressions\n"
        "AVOID: using regex for complex time parsing\n"
        "---\n"
        "summary: [COMPLETE] build2: 5/5 trusted\n"
        "AVOID: retrying the same approach after 2+ failures\n"
    )
    with tempfile.TemporaryDirectory() as d:
        result = _dispatch._mechanical_learnings_fallback(raw_commits, d,
                                                           learnings_journal=journal)
    # Must include git commit learnings
    assert "Integration tests" in result
    # P0-2: Must include journal AVOID lines
    assert "AVOID: using regex" in result or "using regex for complex" in result
    assert "AVOID: retrying the same" in result or "retrying the same approach" in result


def test_mechanical_fallback_dedup_latest_wins():
    """P1-6: the mechanical fallback should dedup — latest occurrence wins."""
    import dispatch as _dispatch
    raw_commits = [
        "=== COMMIT aaa111 ===\n"
        "LEARNINGS:\n"
        "  - Integration tests must hit real binaries\n",
        "=== COMMIT bbb222 ===\n"
        "LEARNINGS:\n"
        "  - Integration tests must hit real binaries\n"
        "  - Use subprocess.run for external binaries\n",
    ]
    with tempfile.TemporaryDirectory() as d:
        result = _dispatch._mechanical_learnings_fallback(raw_commits, d)
    # The duplicate line should appear only once
    assert result.count("Integration tests must hit real binaries") == 1
    # The second commit's unique line should be present
    assert "subprocess.run" in result


def test_failure_conditions_no_false_positives_from_keywords():
    """P1-3: lines with failure-signal words but no AVOID:/DO NOT prefix are NOT captured."""
    learnings = (
        "  - The integration test failed on first attempt but passed after a fix\n"
        "  - We discovered the wrong assumption about the API\n"
        "  - We never saw this edge case in testing\n"
        "  - The judge correctly rejected weak assertions\n"
    )
    fcs = br._extract_failure_conditions(learnings, "COMPLETE", "")
    # None of these should be captured — they're observations, not failure conditions
    assert fcs == [], f"Expected no false positives, got: {fcs}"


def test_failure_conditions_catches_do_not_prefix():
    """P1-3: lines starting with 'DO NOT' are correctly captured."""
    learnings = (
        "  - DO NOT use regex for nested time expressions\n"
        "  - do not skip the regression gate\n"
    )
    fcs = br._extract_failure_conditions(learnings, "COMPLETE", "")
    assert len(fcs) == 2
    assert any("regex" in fc.lower() for fc in fcs)
    assert any("regression" in fc.lower() for fc in fcs)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} bridge tests passed")
