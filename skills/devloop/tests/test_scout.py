"""Deterministic tests for scout.py + devloop_pipeline_cli — the SCOUT -> BUILD pipeline.
No LLM, no relentless-solve: the subprocess seam (`invoke`), the build drain (`run_project`)
and the bridge (`_bridge_mod`) are all injected.

Correctness properties pinned here (mutant-backed):
  * builds happen ONLY on a CONCLUDED scout (success + valid artifact) — never on failed /
    no-path / unconcluded / crashed-with-leftover-artifact scouts;
  * the artifact schema is fail-closed (any violation reads as scout failure);
  * a step is achieved ONLY when its devloop run COMPLETEd AND merged (MERGE_DEGRADED);
  * the slug is deterministic (resume) AND collision-proof (request hash);
  * the CLI's exit contract mirrors devloop_cli's honesty (0 = the asked-for outcome happened).
"""
import json
import os
import sys

import pytest

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)
sys.path.insert(0, os.path.join(_DIR, "scripts"))

import scout                          # noqa: E402
import devloop_pipeline_cli as pcli   # noqa: E402

VALID_STEPS = {"schema_version": 1, "steps": [
    {"purpose": "add a --verbose flag to cli.py", "success_criterion": "cli --verbose prints DEBUG lines"},
    {"purpose": "document the flag in README.md", "success_criterion": "README names --verbose"}]}
NO_PATH = {"schema_version": 1, "steps": [], "no_path": "the repo has no CLI to extend"}


class _Proc:
    def __init__(self, rc=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = rc, stdout, stderr


def _stdout(outcome):
    return "engine chatter\n" + json.dumps({"result": {"outcome": outcome}})


def _scout_env(monkeypatch, tmp_path):
    """Point HERMES_HOME at tmp and satisfy the script ladder with a placeholder file."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    fake_script = tmp_path / "relentless.py"
    fake_script.write_text("# placeholder — never executed (invoke is injected)\n")
    monkeypatch.setenv("DEVLOOP_RELENTLESS_SCRIPT", str(fake_script))


def _invoke_writing(doc, rc=0, outcome="success", calls=None):
    """An invoke fake that (like the live executor agent) writes the artifact, then returns.
    The artifact path is DERIVED the same way run_scout derives it (--slug + HERMES_HOME) —
    never scraped from the prompt prose, so intent rewording can't redden the whole suite."""
    def run(cmd, timeout):
        if calls is not None:
            calls.append((list(cmd), timeout))
        if doc is not None:
            slug = cmd[cmd.index("--slug") + 1]
            spath = os.path.join(os.environ["HERMES_HOME"], "relentless", slug,
                                 "scout-steps.json")
            os.makedirs(os.path.dirname(spath), exist_ok=True)
            with open(spath, "w", encoding="utf-8") as f:
                json.dump(doc, f)
        # stdout carries the outcome JSON even on failure exits — the returncode gate must
        # be what rejects a crashed scout, not an accidentally-empty stdout
        return _Proc(rc, _stdout(outcome), "boom" if rc else "")
    return run


# ---- slug -------------------------------------------------------------------------------------

def test_slug_deterministic_and_collision_proof():
    a = scout.scout_slug("add a --verbose flag to the CLI", "/repoA")
    assert a == scout.scout_slug("add a --verbose flag to the CLI", "/repoA")
    assert a.startswith("scout-add-a-verbose-flag")
    # two requests sharing the whole truncated kebab prefix must NOT share a state dir
    long_a = "x" * 40 + " variant one"
    long_b = "x" * 40 + " variant two"
    assert scout.scout_slug(long_a, "/repoA") != scout.scout_slug(long_b, "/repoA")


def test_slug_is_repo_scoped():
    """MUST-FIX regression (review 2026-07-03): the SAME request against a DIFFERENT repo
    must get fresh state — a shared slug would resume repo A's drained PLAN.json against
    repo B and exit 0 having built nothing."""
    req = "add structured logging to the auth module"
    assert scout.scout_slug(req, "/work/repoA") != scout.scout_slug(req, "/work/repoB")


def test_slug_uses_16_hex_fingerprint():
    slug = scout.scout_slug("req", "/repo")
    fingerprint = slug.rsplit("-", 1)[-1]
    assert len(fingerprint) == 16
    assert all(c in "0123456789abcdef" for c in fingerprint)


def test_pipeline_same_request_new_repo_actually_builds(monkeypatch, tmp_path):
    """End-to-end shape of the fail-open: drain state from repo A must not satisfy repo B."""
    _scout_env(monkeypatch, tmp_path)
    root = tmp_path / "ws"
    # simulate repo A's fully-drained PLAN.json under the OLD (request-only) slug layout —
    # and under repo A's correct slug; repo B must use NEITHER
    slug_a = scout.scout_slug("req", "/work/repoA")
    pa = root / "devloop-pipelines" / slug_a / ".devloop"
    pa.mkdir(parents=True)
    (pa / "PLAN.json").write_text('{"schema_version": 1, "items": [{"id": "p1", '
                                  '"purpose": "old", "status": "completed", "attempt_n": 1, '
                                  '"parent_id": null, "attempts": []}]}')
    rp = _spy_project()
    repo_b = _git_repo(tmp_path)
    res = scout.run_pipeline(repo_b, "req", root=str(root),
                             invoke=_invoke_writing(VALID_STEPS), run_project=rp,
                             step_run_task=lambda *a, **k: None)
    assert res["built"] is True and len(rp.calls) == 1
    assert res["slug"] != slug_a
    assert rp.calls[0]["project_dir"].endswith(res["slug"])


# ---- intent -----------------------------------------------------------------------------------

def test_intent_pins_discipline_and_schema():
    it = scout.scout_intent("goal text", "/repo", "/state/scout-steps.json")
    assert "READ-ONLY" in it and "do NOT implement" in it
    assert "/state/scout-steps.json" in it
    assert '"schema_version": 1' in it and '"no_path"' in it and "success_criterion" in it
    assert "goal text" in it and "/repo" in it
    # live-caught (2026-07-03): a 'write a test' step is self-referential inside devloop
    # (its judges refuse oracles that test a test) — the scout must not emit such steps
    assert "FUNCTIONAL/PRODUCT changes only" in it


# ---- script ladder ----------------------------------------------------------------------------

def test_hermes_home_defaults_to_user_hermes(monkeypatch):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    assert scout._hermes_home() == os.path.expanduser("~/.hermes")


def test_hermes_home_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert scout._hermes_home() == str(tmp_path)


def test_scout_unavailable_is_structured_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))       # ladder candidates won't exist
    monkeypatch.delenv("DEVLOOP_RELENTLESS_SCRIPT", raising=False)
    r = scout.run_scout("req", str(tmp_path))              # real _invoke — must not be reached
    assert r["ok"] is False
    assert r["reason"].startswith("scout unavailable")
    assert "relentless-solve" in r["reason"]


def test_env_override_wins_the_ladder(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    seen = []
    r = scout.run_scout("req", str(tmp_path), invoke=_invoke_writing(VALID_STEPS, calls=seen))
    assert r["ok"] is True
    assert seen[0][0][1] == str(tmp_path / "relentless.py")


# ---- run_scout gating -------------------------------------------------------------------------

def test_success_with_steps(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    calls = []
    r = scout.run_scout("req", "/target", invoke=_invoke_writing(VALID_STEPS, calls=calls))
    assert r["ok"] and r["outcome"] == "success" and not r["unconcluded"]
    assert [s["purpose"] for s in r["steps"]] == [s["purpose"] for s in VALID_STEPS["steps"]]
    cmd = calls[0][0]
    assert cmd[cmd.index("--answer-cwd") + 1] == "/target"          # clarify pinned to the repo
    assert cmd[cmd.index("--capability") + 1] == "read"             # scout never touches the world
    assert calls[0][1] == scout.DEFAULT_WALLCLOCK_S + scout.SUBPROCESS_PAD_S


def test_success_no_path_is_a_valid_conclusion(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    r = scout.run_scout("req", "/t", invoke=_invoke_writing(NO_PATH, outcome="success"))
    assert r["ok"] and r["no_path"] and r["steps"] == [] and not r["unconcluded"]


def test_information_dry_no_path_is_a_valid_conclusion(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    r = scout.run_scout("req", "/t", invoke=_invoke_writing(NO_PATH, outcome="information-dry"))
    assert r["ok"] and r["no_path"] and not r["unconcluded"]


def test_capped_run_with_steps_is_unconcluded(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    for outcome in ("information-dry", "max-cycles", "wallclock"):
        r = scout.run_scout(f"req {outcome}", "/t",
                            invoke=_invoke_writing(VALID_STEPS, outcome=outcome))
        assert r["ok"] and r["unconcluded"] is True, outcome
        assert r["steps"], outcome


def test_capped_no_path_is_unconcluded(monkeypatch, tmp_path):
    """A no-path note from a CAPPED run is not a verdict — only success/information-dry
    runs may conclude 'no viable path'."""
    _scout_env(monkeypatch, tmp_path)
    r = scout.run_scout("req", "/t", invoke=_invoke_writing(NO_PATH, outcome="max-cycles"))
    assert r["ok"] and r["unconcluded"] is True and r["no_path"]
    # ...and the report both flags UNCONCLUDED and still surfaces the no-path note
    rep = scout.render_report({"request": "req", "scout": r, "built": False,
                               "project": None, "scout_only": False})
    assert "UNCONCLUDED" in rep and "no-path note" in rep


def test_nonzero_exit_fails_even_with_valid_artifact(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    # the artifact lands AND stdout claims success — but the process died: fail-closed
    r = scout.run_scout("req", "/t", invoke=_invoke_writing(VALID_STEPS, rc=1))
    assert r["ok"] is False and "scout failed" in r["reason"]


def test_timeout_reports_resumable(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    r = scout.run_scout("req", "/t", invoke=_invoke_writing(None, rc=124))
    assert r["ok"] is False and "resumable" in r["reason"]


def test_unknown_outcome_fails(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    r = scout.run_scout("req", "/t", invoke=_invoke_writing(VALID_STEPS, outcome="weird"))
    assert r["ok"] is False


def test_missing_artifact_fails(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    r = scout.run_scout("req", "/t", invoke=_invoke_writing(None, outcome="success"))
    assert r["ok"] is False and "no valid" in r["reason"]


def test_prior_artifact_reused_on_resumed_success(monkeypatch, tmp_path):
    """Deliberate resume semantics: a replayed relentless run does NOT re-execute the agent
    that wrote the artifact, so a same-slug artifact + a success outcome is THE finding."""
    _scout_env(monkeypatch, tmp_path)
    slug = scout.scout_slug("req", "/t")
    sdir = tmp_path / "relentless" / slug
    sdir.mkdir(parents=True)
    (sdir / "scout-steps.json").write_text(json.dumps(VALID_STEPS))
    r = scout.run_scout("req", "/t", invoke=lambda c, t: _Proc(0, _stdout("success")))
    assert r["ok"] and r["steps"]


def test_fresh_clears_prior_state(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    slug = scout.scout_slug("req", "/t")
    sdir = tmp_path / "relentless" / slug
    sdir.mkdir(parents=True)
    (sdir / "scout-steps.json").write_text(json.dumps(VALID_STEPS))
    (sdir / "ledger.jsonl").write_text("old\n")
    r = scout.run_scout("req", "/t", fresh=True,
                        invoke=lambda c, t: _Proc(0, _stdout("success")))
    assert not (sdir / "ledger.jsonl").exists()      # state really cleared
    assert r["ok"] is False                          # fake wrote nothing back -> no artifact


def test_fresh_run_scout_fails_closed_when_rmtree_ineffective(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    slug = scout.scout_slug("req", "/t")
    sdir = tmp_path / "relentless" / slug
    sdir.mkdir(parents=True)
    (sdir / "ledger.jsonl").write_text("old\n")
    monkeypatch.setattr(scout.shutil, "rmtree", lambda *a, **k: None)
    calls = []
    r = scout.run_scout("req", "/t", fresh=True,
                        invoke=_invoke_writing(VALID_STEPS, calls=calls))
    assert r["ok"] is False and "--fresh" in r["reason"] and "resume" in r["reason"]
    assert calls == []


def test_timeout_flags_passed_through(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    calls = []
    scout.run_scout("req", "/t", plan_timeout=300, task_timeout=900,
                    invoke=_invoke_writing(VALID_STEPS, calls=calls))
    cmd = calls[0][0]
    assert cmd[cmd.index("--plan-timeout") + 1] == "300"
    assert cmd[cmd.index("--task-timeout") + 1] == "900"


def test_timeout_flags_absent_when_unset(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    calls = []
    scout.run_scout("req2", "/t", invoke=_invoke_writing(VALID_STEPS, calls=calls))
    cmd = calls[0][0]
    assert "--plan-timeout" not in cmd and "--task-timeout" not in cmd


def test_real_invoke_timeout_becomes_rc124_with_partial_output():
    """The oneshot.py lesson, actually exercised: a TimeoutExpired must become a rc-124
    CompletedProcess carrying whatever partial output existed — never a raised exception
    (relentless runs are journal-resumable; the caller reports and moves on)."""
    r = scout._invoke([sys.executable, "-u", "-c",
                       "import time; print('partial', flush=True); time.sleep(30)"], 1)
    assert r.returncode == 124
    assert "partial" in (r.stdout or "")


def test_invoke_replaces_undecodable_bytes():
    r = scout._invoke([sys.executable, "-c",
                       "import sys; sys.stdout.buffer.write(b'\\xff'); "
                       "sys.stdout.buffer.flush()"], 10)
    assert r.returncode == 0
    assert isinstance(r.stdout, str)
    assert "\ufffd" in r.stdout


def test_parse_outcome_shapes():
    j = lambda o: json.dumps({"result": {"outcome": o}})
    # last JSON object wins over earlier ones and over chatter
    assert scout._parse_outcome(f"noise\n{j('wallclock')}\nmore\n{j('success')}") == "success"
    # whole-stdout (pretty-printed, multi-line) fallback
    pretty = json.dumps({"result": {"outcome": "information-dry"}}, indent=2)
    assert scout._parse_outcome(pretty) == "information-dry"
    # fail-closed shapes -> None
    assert scout._parse_outcome("") is None
    assert scout._parse_outcome(None) is None
    assert scout._parse_outcome("pure garbage {not json") is None
    assert scout._parse_outcome(json.dumps({"result": "not-a-dict"})) is None
    assert scout._parse_outcome(json.dumps({"result": {"no_outcome_key": 1}})) is None


# ---- load_steps (fail-closed schema) ----------------------------------------------------------

def _write(tmp_path, doc):
    p = tmp_path / "scout-steps.json"
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    return str(p)


def test_load_steps_valid(tmp_path):
    d = scout.load_steps(_write(tmp_path, VALID_STEPS))
    assert d["no_path"] is None and len(d["steps"]) == 2
    assert d["steps"][0]["purpose"].startswith("add a --verbose")


def test_load_steps_rejects_surrogate_in_purpose(tmp_path):
    doc = ('{"schema_version": 1, "steps": [{"purpose": "bad \\ud800 surrogate", '
           '"success_criterion": "c"}]}')
    assert scout.load_steps(_write(tmp_path, doc)) is None


def test_load_steps_rejects_bool_schema_version(tmp_path):
    doc = {"schema_version": True, "steps": [
        {"purpose": "p", "success_criterion": "c"}]}
    assert scout.load_steps(_write(tmp_path, doc)) is None


def test_load_steps_rejects_all_violations(tmp_path):
    bad = [
        "not json {",
        [1, 2],                                                     # not a dict
        {"schema_version": 2, "steps": [                             # wrong version
            {"purpose": "p", "success_criterion": "c"}]},            # (otherwise valid)
        {"schema_version": 1, "steps": {}},                          # steps not a list
        {"schema_version": 1, "steps": [{"purpose": "p"}]},          # missing criterion
        {"schema_version": 1, "steps": [{"purpose": "  ", "success_criterion": "c"}]},
        {"schema_version": 1, "steps": [{"purpose": "p", "success_criterion": ""}]},
        {"schema_version": 1, "steps": ["not-a-dict"]},
        {"schema_version": 1, "steps": []},                          # empty w/o no_path
        {"schema_version": 1, "steps": [], "no_path": "   "},        # blank no_path
        {"schema_version": 1, "steps": [], "no_path": 7},            # non-str no_path
        {"schema_version": 1,                                        # contradictory finding
         "steps": [{"purpose": "p", "success_criterion": "c"}], "no_path": "also no path"},
        {"schema_version": 1, "steps": [                             # over the sanity cap
            {"purpose": f"p{i}", "success_criterion": "c"} for i in range(scout.MAX_STEPS + 1)]},
    ]
    for doc in bad:
        assert scout.load_steps(_write(tmp_path, doc)) is None, doc
    assert scout.load_steps(str(tmp_path / "missing.json")) is None


# ---- purposes ---------------------------------------------------------------------------------

def test_steps_to_purposes_carries_the_criterion():
    ps = scout.steps_to_purposes(VALID_STEPS["steps"])
    assert len(ps) == 2
    assert "Success criterion: cli --verbose prints DEBUG lines" in ps[0]
    assert ps[0].startswith("add a --verbose flag")


# ---- bridge step adapter ----------------------------------------------------------------------

class _FakeBridge:
    def __init__(self, dr, content="summary"):
        self.dr, self.content, self.calls = dr, content, []

    def call_guarded(self, fn, *a, **k):
        self.calls.append((a, k))
        return {"content": self.content, "devloop_result": self.dr}

    def _run(self, *a, **k):
        raise AssertionError("must go through call_guarded")


def _with_bridge(monkeypatch, dr):
    fb = _FakeBridge(dr)
    monkeypatch.setattr(scout, "_bridge_mod", lambda: fb)
    return fb


def test_adapter_complete_and_merged_passes_through(monkeypatch):
    fb = _with_bridge(monkeypatch, {"terminal": "COMPLETE", "merged": True, "reason": "",
                                    "retryable": None, "charter": {"dod": [{"id": "c1"}]}})
    res = scout.bridge_step_run_task("/repo", "purpose", "/root", "p1-a1")
    assert res["result"]["terminal"] == "COMPLETE"
    assert res["charter"]["dod"]
    assert fb.calls[0][0][0] == "purpose" and fb.calls[0][1]["repo"] == "/repo"


def test_adapter_downgrades_unmerged_complete(monkeypatch):
    """'achieved' must mean the code ARRIVED: a COMPLETE whose auto-merge degraded to
    branch-for-review must not let the drain mark the step done and build the next step
    on code that never landed."""
    _with_bridge(monkeypatch, {"terminal": "COMPLETE", "merged": False,
                               "merge_reason": "dirty tree", "reason": "", "charter": {}})
    res = scout.bridge_step_run_task("/repo", "p", "/root", "n")
    assert res["result"]["terminal"] == "MERGE_DEGRADED"
    assert "dirty tree" in res["result"]["reason"]


def test_adapter_forwards_retryable_for_escalation(monkeypatch):
    _with_bridge(monkeypatch, {"terminal": "HUMAN_REVIEW", "merged": False, "reason": "vague",
                               "retryable": False, "charter": {}})
    res = scout.bridge_step_run_task("/repo", "p", "/root", "n")
    assert res["result"]["retryable"] is False
    assert res["result"]["terminal"] == "HUMAN_REVIEW"


def test_bridge_run_exposes_retryable_and_charter(tmp_path):
    """The real bridge must FORWARD retryable + charter into devloop_result — the adapter's
    escalate-vs-reattempt fidelity depends on it."""
    import devloop_bridge as br
    fake_rt = lambda repo, request, root, name: {
        "result": {"terminal": "HUMAN_REVIEW", "reason": "r", "retryable": False},
        "worktree": {}, "charter": {"dod": [{"id": "c1"}], "open_questions": []}}
    out = br._run("req", "n-scout-test", run_task=fake_rt, repo=str(tmp_path))
    dr = out["devloop_result"]
    assert dr["retryable"] is False
    assert dr["charter"]["dod"][0]["id"] == "c1"


def test_bridge_finalize_commit_failure_degrades_scout_result(monkeypatch, tmp_path):
    import functools
    import devloop_bridge as br
    import worktree
    repo = _git_repo(tmp_path)
    hook = os.path.join(repo, ".git", "hooks", "pre-commit")
    open(hook, "w").write("#!/bin/sh\nexit 1\n")
    os.chmod(hook, 0o755)
    made = {}

    def complete_with_work(repo_, request, root, name):
        wt = worktree.create_worktree(repo_, name, root)
        open(os.path.join(wt["path"], "built.py"), "w").write("built = True\n")
        made.update(wt)
        return {"result": {"terminal": "COMPLETE", "reason": "done"},
                "worktree": wt, "charter": {}}

    merge_calls = []

    def observe_merge(*args, **kwargs):
        merge_calls.append((args, kwargs))
        return {"merged": False, "reason": "must not be called", "target": None}

    monkeypatch.setattr(worktree, "merge_branch", observe_merge)
    original_run = br._run
    monkeypatch.setattr(br, "_run", functools.partial(original_run, run_task=complete_with_work))
    result = scout.bridge_step_run_task(repo, "build it", os.path.join(repo, ".worktrees"),
                                        "commit-failure-scout")
    assert result["result"]["terminal"] == "MERGE_DEGRADED"
    assert "finalize commit failed" in result["result"]["reason"]
    dr = result["devloop_result"]
    assert dr["merged"] is False and dr["branch"] == made["branch"]
    assert os.path.isdir(made["path"])
    assert merge_calls == []


def test_bridge_keep_branch_does_not_bless_failed_finalize_commit(tmp_path):
    import devloop_bridge as br
    import worktree
    repo = _git_repo(tmp_path)
    hook = os.path.join(repo, ".git", "hooks", "pre-commit")
    open(hook, "w").write("#!/bin/sh\nexit 1\n")
    os.chmod(hook, 0o755)

    def complete_with_work(repo_, request, root, name):
        wt = worktree.create_worktree(repo_, name, root)
        open(os.path.join(wt["path"], "built.py"), "w").write("built = True\n")
        return {"result": {"terminal": "COMPLETE", "reason": "done"},
                "worktree": wt, "charter": {}}

    out = br._run("build it", "commit-failure-kept", run_task=complete_with_work,
                  repo=repo, keep_branch=True)
    assert out["devloop_result"]["kept_branch"] is False
    assert out["devloop_result"]["merged"] is False
    assert "finalize commit failed" in out["devloop_result"]["merge_reason"]


def test_bridge_surfaces_leaked_branch_after_successful_merge(monkeypatch, tmp_path):
    import devloop_bridge as br
    import worktree
    repo = _git_repo(tmp_path)
    orig_git = worktree._git

    def skip_branch_delete(repo_arg, *args, **kw):
        if len(args) >= 3 and args[:2] == ("branch", "-D"):
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        return orig_git(repo_arg, *args, **kw)

    def complete_with_work(repo_, request, root, name):
        wt = worktree.create_worktree(repo_, name, root)
        open(os.path.join(wt["path"], "built.py"), "w").write("built = True\n")
        return {"result": {"terminal": "COMPLETE", "reason": "done"},
                "worktree": wt, "charter": {}}

    monkeypatch.setattr(worktree, "_git", skip_branch_delete)
    out = br._run("build it", "leaked-branch", run_task=complete_with_work, repo=repo)
    dr = out["devloop_result"]
    assert dr["merged"] is True and dr["branch"] == "devloop/leaked-branch"
    assert "merged but branch deletion failed: devloop/leaked-branch" in out["content"]


def test_bridge_boundary_guard_restores_agent_debris(tmp_path):
    """A run_task whose agent phases escape the worktree and touch the target repo's main
    working tree (live-caught: a tracked test file deleted mid-run) must leave the repo
    exactly as dirty as it was before the run — newly dirty paths are restored/deleted."""
    import devloop_bridge as br
    repo = _git_repo(tmp_path)
    pre_existing = os.path.join(repo, "user_wip.txt")          # user's uncommitted work
    with open(pre_existing, "w") as f:
        f.write("keep me\n")

    def escaping_rt(repo_, request, root, name):
        os.remove(os.path.join(repo_, "seed.py"))              # deletes a tracked file
        with open(os.path.join(repo_, "debris.tmp"), "w") as f:
            f.write("junk\n")
        return {"result": {"terminal": "HUMAN_REVIEW", "reason": "r"}, "worktree": {},
                "charter": {}}

    out = br._run("req", "n-boundary-test", run_task=escaping_rt, repo=repo)
    dr = out["devloop_result"]
    assert dr["boundary_restored"] == ["debris.tmp", "seed.py"]
    assert os.path.exists(os.path.join(repo, "seed.py"))       # tracked file back
    assert not os.path.exists(os.path.join(repo, "debris.tmp"))
    assert os.path.exists(pre_existing)                        # user work untouched
    assert "worktree-boundary breach" in out["content"]


def test_bridge_boundary_guard_handles_weird_names_and_shapes(tmp_path):
    """Review 2026-07-03: default porcelain quoting hid non-ASCII/space names from the guard,
    staged-adds survived, and renames lost their old side. All four shapes must restore."""
    import subprocess as sp
    import devloop_bridge as br
    repo = _git_repo(tmp_path)
    (open(os.path.join(repo, "café file.txt"), "w")).write("x")     # untracked, space+non-ASCII
    os.makedirs(os.path.join(repo, "debris dir"))
    open(os.path.join(repo, "debris dir", "f.txt"), "w").write("x")  # untracked directory
    open(os.path.join(repo, "staged.txt"), "w").write("x")
    sp.run(["git", "add", "staged.txt"], cwd=repo, check=True, capture_output=True)
    sp.run(["git", "mv", "seed.py", "renamed.py"], cwd=repo, check=True, capture_output=True)
    restored, failed = br._restore_boundary_breach(repo, {})
    assert failed == []
    assert "café file.txt" in restored and "staged.txt" in restored
    assert any(p.startswith("debris dir") for p in restored)
    assert "seed.py" in restored                                    # rename's OLD side back
    assert os.path.exists(os.path.join(repo, "seed.py"))
    assert not os.path.exists(os.path.join(repo, "renamed.py"))
    assert br._repo_status(repo) == {}                              # tree fully clean


def test_bridge_boundary_guard_reports_failed_restores_honestly(monkeypatch, tmp_path):
    """A restore that didn't take must land in `failed`, never in `restored` — the earlier
    per-path bookkeeping trusted its own actions and could report a failed restore as done."""
    import devloop_bridge as br
    repo = _git_repo(tmp_path)
    open(os.path.join(repo, "stuck.txt"), "w").write("x")
    monkeypatch.setattr(os, "remove", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    restored, failed = br._restore_boundary_breach(repo, {})
    assert "stuck.txt" in failed and "stuck.txt" not in restored


def test_bridge_boundary_guard_status_failure_reports_all_unverified(monkeypatch, tmp_path):
    import devloop_bridge as br
    repo = _git_repo(tmp_path)
    paths = {"debris-a.tmp": "??", "debris-b.tmp": "??"}
    for path in paths:
        open(os.path.join(repo, path), "w").write("junk\n")
    statuses = iter([paths, None])
    monkeypatch.setattr(br, "_repo_status", lambda repo_: next(statuses))
    restored, failed = br._restore_boundary_breach(repo, {})
    assert restored == []
    assert failed == sorted(paths)


def test_bridge_boundary_guard_inert_on_non_git(tmp_path):
    import devloop_bridge as br
    d = tmp_path / "plain"
    d.mkdir()
    assert br._repo_status(str(d)) is None
    assert br._restore_boundary_breach(str(d), {}) == ([], [])
    assert br._restore_boundary_breach(str(d), None) == ([], [])


def test_bridge_run_surfaces_failed_boundary_restore(monkeypatch, tmp_path):
    import devloop_bridge as br
    repo = _git_repo(tmp_path)

    def escaping_rt(repo_, request, root, name):
        with open(os.path.join(repo_, "stuck.txt"), "w") as f:
            f.write("junk\n")
        return {"result": {"terminal": "HUMAN_REVIEW", "reason": "r"}, "worktree": {},
                "charter": {}}

    monkeypatch.setattr(os, "remove", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    out = br._run("req", "n-bfail-test", run_task=escaping_rt, repo=repo)
    dr = out["devloop_result"]
    assert dr["boundary_restore_failed"] == ["stuck.txt"]
    assert "restore FAILED" in out["content"]


def test_bridge_boundary_guard_noop_on_clean_run(tmp_path):
    import devloop_bridge as br
    repo = _git_repo(tmp_path)
    rt = lambda repo_, request, root, name: {
        "result": {"terminal": "HUMAN_REVIEW", "reason": "r"}, "worktree": {}, "charter": {}}
    out = br._run("req", "n-clean-test", run_task=rt, repo=repo)
    assert out["devloop_result"]["boundary_restored"] == []
    assert "boundary" not in out["content"]


def test_bridge_failure_result_is_non_retryable():
    import devloop_bridge as br
    dr = br.failure_result("boom")["devloop_result"]
    assert dr["retryable"] is False and dr["charter"] == {}


# ---- run_pipeline gating ----------------------------------------------------------------------

def _spy_project(result=None):
    calls = []

    def rp(repo, root, purposes, **kw):
        calls.append({"repo": repo, "root": root, "purposes": purposes, **kw})
        return result or {"achieved": ["p1", "p2"], "blocked": [], "items": [
            {"id": "p1", "status": "completed"}, {"id": "p2", "status": "completed"}],
            "report": "# Project report — built fine"}
    rp.calls = calls
    return rp


def _pipeline(monkeypatch, tmp_path, doc, outcome="success", rc=0, **kw):
    _scout_env(monkeypatch, tmp_path)
    rp = _spy_project(kw.pop("project_result", None))
    repo = _git_repo(tmp_path)
    res = scout.run_pipeline(repo, "req", root=str(tmp_path / "ws"),
                             invoke=_invoke_writing(doc, rc=rc, outcome=outcome),
                             run_project=rp, step_run_task=lambda *a, **k: None, **kw)
    return res, rp


def test_pipeline_builds_on_concluded_steps(monkeypatch, tmp_path):
    res, rp = _pipeline(monkeypatch, tmp_path, VALID_STEPS)
    assert res["built"] is True and len(rp.calls) == 1
    call = rp.calls[0]
    assert "Success criterion:" in call["purposes"][0]
    assert call["project_dir"].endswith(os.path.join("devloop-pipelines", res["slug"]))
    assert "built fine" in res["report"]


def test_pipeline_scout_failure_never_builds(monkeypatch, tmp_path):
    res, rp = _pipeline(monkeypatch, tmp_path, VALID_STEPS, rc=1)
    assert res["built"] is False and rp.calls == []
    assert "SCOUT FAILED" in res["report"]


def test_pipeline_scout_only_never_builds(monkeypatch, tmp_path):
    res, rp = _pipeline(monkeypatch, tmp_path, VALID_STEPS, scout_only=True)
    assert res["built"] is False and rp.calls == []
    assert "scout-only" in res["report"]


def test_pipeline_no_path_never_builds(monkeypatch, tmp_path):
    res, rp = _pipeline(monkeypatch, tmp_path, NO_PATH)
    assert res["built"] is False and rp.calls == []
    assert "NO VIABLE PATH" in res["report"]


def test_pipeline_unconcluded_never_builds(monkeypatch, tmp_path):
    res, rp = _pipeline(monkeypatch, tmp_path, VALID_STEPS, outcome="max-cycles")
    assert res["built"] is False and rp.calls == []
    assert "UNCONCLUDED" in res["report"]
    # the partial finding IS surfaced for review
    assert "add a --verbose flag" in res["report"]


def test_pipeline_bundle_lands(monkeypatch, tmp_path):
    res, _ = _pipeline(monkeypatch, tmp_path, VALID_STEPS)
    bundle = res["bundle"]
    assert bundle and os.path.isdir(bundle)
    assert os.path.exists(os.path.join(bundle, "report.md"))
    assert json.load(open(os.path.join(bundle, "scout-steps.json")))["schema_version"] == 1


def test_pipeline_fresh_clears_drain_state(monkeypatch, tmp_path):
    """--fresh restarts the WHOLE pipeline: a PLAN.json full of blocked items from a prior
    (e.g. environmental) failure must not resume as an instant no-op re-report."""
    _scout_env(monkeypatch, tmp_path)
    root = tmp_path / "ws"
    repo = _git_repo(tmp_path)
    slug = scout.scout_slug("req", repo)
    pdir = root / "devloop-pipelines" / slug / ".devloop"
    pdir.mkdir(parents=True)
    (pdir / "PLAN.json").write_text('{"items": []}')
    res, _ = None, None
    rp = _spy_project()
    res = scout.run_pipeline(repo, "req", root=str(root), fresh=True,
                             invoke=_invoke_writing(VALID_STEPS), run_project=rp,
                             step_run_task=lambda *a, **k: None)
    assert not pdir.exists()                    # stale drain state cleared
    assert res["built"] is True                 # and the pipeline ran through


def test_fresh_pipeline_fails_closed_when_rmtree_ineffective(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    repo = _git_repo(tmp_path)
    root = tmp_path / "ws"
    slug = scout.scout_slug("req", repo)
    pdir = root / "devloop-pipelines" / slug
    pdir.mkdir(parents=True)
    (pdir / "PLAN.json").write_text('{"items": []}')
    monkeypatch.setattr(scout.shutil, "rmtree", lambda *a, **k: None)
    calls = []
    rp = _spy_project()
    res = scout.run_pipeline(repo, "req", root=str(root), fresh=True,
                             invoke=_invoke_writing(VALID_STEPS, calls=calls),
                             run_project=rp, step_run_task=lambda *a, **k: None)
    assert res["scout"]["ok"] is False
    assert "--fresh" in res["scout"]["reason"] and "resume" in res["scout"]["reason"]
    assert calls == [] and rp.calls == []


# ---- read-only discipline as a CODE gate (live-caught 2026-07-03) ------------------------------

import subprocess


def _git_repo(tmp_path):
    r = tmp_path / "target"
    r.mkdir()
    (r / "seed.py").write_text("x = 1\n")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed"]):
        subprocess.run(cmd, cwd=r, check=True, capture_output=True)
    return str(r)


def test_pipeline_refuses_dirty_repo(monkeypatch, tmp_path):
    """Precondition: the pipeline merges into this repo AND the debris scrub needs a clean
    baseline — uncommitted changes are a structured refusal, not a scout run."""
    _scout_env(monkeypatch, tmp_path)
    repo = _git_repo(tmp_path)
    with open(os.path.join(repo, "seed.py"), "a") as f:
        f.write("y = 2\n")
    rp = _spy_project()
    invoked = []
    res = scout.run_pipeline(repo, "req", root=str(tmp_path / "ws"),
                             invoke=lambda c, t: invoked.append(1) or _Proc(0, _stdout("success")),
                             run_project=rp, step_run_task=lambda *a, **k: None)
    assert res["scout"]["ok"] is False and "uncommitted changes" in res["scout"]["reason"]
    assert invoked == [] and rp.calls == []


def test_git_status_none_fails_closed_in_pipeline(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    repo = _git_repo(tmp_path)
    monkeypatch.setattr(scout, "_git_status", lambda r: None)
    invoked = []
    rp = _spy_project()
    res = scout.run_pipeline(repo, "req", root=str(tmp_path / "ws"),
                             invoke=lambda c, t: invoked.append(1), run_project=rp,
                             step_run_task=lambda *a, **k: None)
    assert res["scout"]["ok"] is False
    assert "fail closed" in res["scout"]["reason"]
    assert invoked == [] and rp.calls == []


def test_scrub_debris_returns_none_when_status_unreadable(monkeypatch, tmp_path):
    repo = _git_repo(tmp_path)
    monkeypatch.setattr(scout, "_git_status", lambda r: None)
    assert scout._scrub_scout_debris(repo) is None


def test_scrub_debris_returns_none_when_post_status_unreadable(monkeypatch, tmp_path):
    repo = _git_repo(tmp_path)
    statuses = iter([[" M seed.py"], None])
    monkeypatch.setattr(scout, "_git_status", lambda r: next(statuses))
    assert scout._scrub_scout_debris(repo) is None


def test_pipeline_scrubs_scout_debris_and_reports(monkeypatch, tmp_path):
    """A scout that modifies the repo (agent overreach — the live-caught trial-implementation)
    gets its debris hard-restored; the breach is visible in the result + report."""
    _scout_env(monkeypatch, tmp_path)
    repo = _git_repo(tmp_path)
    base = _invoke_writing(VALID_STEPS)

    def dirtying(cmd, timeout):
        with open(os.path.join(repo, "seed.py"), "a") as f:
            f.write("y = 2  # scout debris\n")
        with open(os.path.join(repo, "junk.py"), "w") as f:
            f.write("tmp\n")
        return base(cmd, timeout)

    rp = _spy_project()
    res = scout.run_pipeline(repo, "req", root=str(tmp_path / "ws"),
                             invoke=dirtying, run_project=rp,
                             step_run_task=lambda *a, **k: None)
    assert scout._git_status(repo) == []                       # repo byte-restored
    assert sorted(res["scout"]["scrubbed"]) == ["junk.py", "seed.py"]
    assert "RESTORED clean" in res["report"]
    assert res["built"] is True                                 # the finding itself still builds


def test_pipeline_fails_closed_when_scrub_fails(monkeypatch, tmp_path):
    _scout_env(monkeypatch, tmp_path)
    repo = _git_repo(tmp_path)
    monkeypatch.setattr(scout, "_scrub_scout_debris", lambda r: None)
    rp = _spy_project()
    res = scout.run_pipeline(repo, "req", root=str(tmp_path / "ws"),
                             invoke=_invoke_writing(VALID_STEPS), run_project=rp,
                             step_run_task=lambda *a, **k: None)
    assert res["scout"]["ok"] is False and "restore FAILED" in res["scout"]["reason"]
    assert rp.calls == []


def test_intent_warns_changes_are_discarded():
    it = scout.scout_intent("g", "/r", "/s/scout-steps.json")
    assert "will be detected and discarded" in it and "COPY outside the repository" in it


# ---- CLI exit contract ------------------------------------------------------------------------

def _cli(argv, res, refusal=None):
    seen = {}

    def pipeline(repo, request, **kw):
        seen.update(repo=repo, request=request, **kw)
        return res

    def validate(path, ws):
        return (None, refusal) if refusal else (path, None)

    rc = pcli.main(argv, pipeline=pipeline, validate=validate, write_safe="/ws")
    return rc, seen


def _res(ok=True, built=False, unconcluded=False, no_path=None, blocked=(), pending=0):
    items = [{"id": "p1", "status": "completed"}] + \
            [{"id": f"b{i}", "status": "blocked"} for i in range(len(blocked))] + \
            [{"id": f"q{i}", "status": "pending"} for i in range(pending)]
    return {"scout": {"ok": ok, "unconcluded": unconcluded, "no_path": no_path},
            "built": built, "report": "rpt",
            "project": {"blocked": list(blocked), "items": items} if built else None}


def test_cli_refusal_exits_2(capsys):
    rc, _ = _cli(["req", "--repo", "/x"], _res(), refusal="bad repo")
    assert rc == 2


def test_cli_scout_failure_exits_2():
    rc, _ = _cli(["req", "--repo", "/x"], _res(ok=False))
    assert rc == 2


def test_cli_scout_only_exits_0():
    rc, seen = _cli(["req", "--repo", "/x", "--scout-only", "--fresh"], _res())
    assert rc == 0
    assert seen["scout_only"] is True and seen["fresh"] is True


def test_cli_no_path_exits_0():
    rc, _ = _cli(["req", "--repo", "/x"], _res(no_path="none exists"))
    assert rc == 0


def test_cli_unconcluded_exits_1():
    rc, _ = _cli(["req", "--repo", "/x"], _res(unconcluded=True))
    assert rc == 1


def test_cli_drained_build_exits_0():
    rc, _ = _cli(["req", "--repo", "/x"], _res(built=True))
    assert rc == 0


def test_cli_blocked_build_exits_1():
    rc, _ = _cli(["req", "--repo", "/x"], _res(built=True, blocked=["b0"]))
    assert rc == 1


def test_cli_pending_leftovers_exit_1():
    rc, _ = _cli(["req", "--repo", "/x"], _res(built=True, pending=1))
    assert rc == 1


def test_cli_in_progress_leftovers_exit_1():
    res = _res(built=True)
    res["project"]["items"][0]["status"] = "in_progress"
    rc, _ = _cli(["req", "--repo", "/x"], res)
    assert rc == 1


def test_cli_empty_items_exit_1():
    res = _res(built=True)
    res["project"]["items"] = []
    rc, _ = _cli(["req", "--repo", "/x"], res)
    assert rc == 1


def test_cli_zero_values_honored_and_flags_thread():
    """Review: `or defaults` treated an explicit 0 as unset — `is not None` must honor it."""
    rc, seen = _cli(["req", "--repo", "/x", "--max-cycles", "0", "--wallclock", "0",
                     "--plan-timeout", "60", "--task-timeout", "120", "--scout-only"], _res())
    assert rc == 0
    assert seen["max_cycles"] == 0 and seen["wallclock"] == 0
    assert seen["plan_timeout"] == 60 and seen["task_timeout"] == 120


def test_cli_defaults_when_flags_unset():
    _, seen = _cli(["req", "--repo", "/x", "--scout-only"], _res())
    assert seen["max_cycles"] == 3 and seen["wallclock"] == 1800
    assert seen["plan_timeout"] is None and seen["task_timeout"] is None


def test_cli_json_mode(capsys):
    rc, _ = _cli(["req", "--repo", "/x", "--scout-only", "--json"], _res())
    assert rc == 0
    d = json.loads(capsys.readouterr().out)
    assert d["report"] == "rpt" and d["built"] is False


# ---- seam contract (RelentlessContract) --------------------------------------------------------
# scout.py encodes knowledge of relentless-solve's interface. The family doctrine (PlanContract,
# EngineContract, OneshotContract, HarvestContract) pins every such cross-skill assumption so
# drift becomes a NAMED test failure instead of a silent runtime "scout failed". SKIPs when the
# counterpart skill is absent (host runs), pins in-container where relentless is deployed.

_RELENTLESS = scout._relentless_script()[0]
_needs_relentless = pytest.mark.skipif(
    _RELENTLESS is None, reason="relentless-solve not deployed — seam contract not checkable")


@_needs_relentless
def test_contract_run_cli_accepts_every_flag_scout_passes():
    """Every flag run_scout builds into its argv must exist on relentless's `run` command —
    a rename/removal there must fail HERE, not as a live rc-2 mystery."""
    import subprocess
    r = subprocess.run([sys.executable, _RELENTLESS, "run", "--help"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-300:]
    for flag in ("--slug", "--answer-cwd", "--prompt", "--capability",
                 "--max-cycles", "--wallclock", "--plan-timeout", "--task-timeout"):
        assert flag in r.stdout, f"relentless `run` no longer documents {flag}"
    assert "read" in r.stdout                      # --capability read is the scout's mode


@_needs_relentless
def test_contract_outcome_vocabulary_matches():
    """scout gates on _TERMINAL_OUTCOMES read from relentless's final stdout JSON — every
    one of those quoted strings must still exist in relentless's source. This is a cheap
    literal tripwire plus result-writer anchor, not an execution-path proof."""
    src = open(_RELENTLESS, encoding="utf-8").read()
    assignments = {
        "success": 'outcome = "success"',
        "information-dry": 'outcome, detail = "information-dry"',
        "max-cycles": 'outcome, detail = "max-cycles"',
        "wallclock": 'outcome, detail = "wallclock"',
    }
    for outcome in scout._TERMINAL_OUTCOMES:
        assert assignments[outcome] in src, \
            f"relentless source no longer assigns outcome {outcome!r}"
    assert "def write_solve_json(" in src and '"outcome": outcome' in src


@_needs_relentless
def test_contract_state_dir_layout():
    """steps_path is derived as $HERMES_HOME/relentless/<slug>/ — relentless must still keep
    its run state under that convention (the intent names the artifact path inside it)."""
    src = open(_RELENTLESS, encoding="utf-8").read()
    assert 'os.path.join(_HOME, "relentless"' in src, \
        "relentless no longer roots its state under <HERMES_HOME>/relentless/"


@_needs_relentless
def test_contract_hermes_home_default_matches():
    """Protect against upstream drift silently disagreeing with scout's mirrored default."""
    src = open(_RELENTLESS, encoding="utf-8").read()
    assert ('_HOME = os.environ.get("HERMES_HOME", '
            'os.path.expanduser("~/.hermes"))') in src


if __name__ == "__main__":
    # mutants.py's guard runs each test file as a script; this suite uses pytest fixtures
    # (monkeypatch/tmp_path), so self-running delegates to pytest instead of a fn-loop
    raise SystemExit(pytest.main([__file__, "-q"]))
