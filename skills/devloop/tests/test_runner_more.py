"""Deterministic coverage-gap tests for runner.run_task — closes confirmed surviving mutants the
main test_runner.py suite misses. Same posture as the exemplar: real git worktree, real pytest
collection where needed, NO LLM (charter/designer/implementer/judges are scripted or injected).

Each test below pins CURRENT (correct) behavior so the documented old->new mutant would FAIL:
  - designer RuntimeError -> HUMAN_REVIEW (mutant: COMPLETE) — false-complete on an env error.
  - real path calls assert_distinct_models(CODER, DESIGNER, JUDGE_A, JUDGE_B) BEFORE the worktree
    (mutant: assert_distinct_models(CODER) only) — the no-self-grading gate stops firing.
  - the STRUCTURED spec designer is THE default (mutant: default swapped for an empty-map stub) — every real
    run silently routes through the un-shadow-proven structured path.
"""
import os
import subprocess
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import config     # noqa: E402
import dispatch   # noqa: E402
import runner     # noqa: E402
import testgen    # noqa: E402
import worktree   # noqa: E402


def _has_pytest():
    try:
        return subprocess.run([sys.executable, "-m", "pytest", "--version"],
                              capture_output=True, timeout=30).returncode == 0
    except Exception:  # noqa: BLE001
        return False


_HAS_PYTEST = _has_pytest()


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True)


def _init_repo(root):
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "x@y.z")
    _git(repo, "config", "user.name", "x")
    open(os.path.join(repo, "README"), "w").write("repo\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


def _charter(ids):
    return {
        "interpreted_intent": "normalize strings", "purpose": "demo",
        "dod": [{"id": i, "criterion": f"crit {i}", "verify_intent": f"v{i}", "kind": "shown"} for i in ids],
        "assumptions": [{"text": "a", "confidence": 0.9}], "open_questions": [],
        "happy_path": "x", "blast_radius": {"files": ["norm.py"], "order": ["norm.py"]},
        "backoff_map": [{"trigger": "t", "directional_response": "r"}],
        "advisors_verdict": "ok", "ambiguity_decision": {"decision": "PROCEED", "reason": "ok"},
    }


def _map_from_src(target, fname="test_norm.py"):
    # Minimal FIXTURE map builder (the production annotation parser was deleted with the
    # free-form designer, 2026-07-01): '# dod: cN' lines in the authored fixture -> planned
    # {relpath::fn: cN}, intersected with REAL collection via collect_spec_map (the live pivot).
    import re as _re
    src = open(os.path.join(target, fname)).read()
    planned, fn = {}, None
    for line in src.splitlines():
        m = _re.match(r"def (test\w+)", line)
        if m:
            fn = m.group(1)
        m2 = _re.search(r"dod:\s*(\w+)", line)
        if m2 and fn:
            planned[f"{fname}::{fn}"] = m2.group(1)
    return testgen.collect_spec_map(target, planned)


def _designer_writes(tests_src):
    def make_designer(target):
        def design(charter):
            open(os.path.join(target, "test_norm.py"), "w").write(tests_src)
            return _map_from_src(target)
        return design
    return make_designer


def _implementer_writes(impl_src):
    def make_implementer(target):
        def implement(charter, attempt, last_failure):
            open(os.path.join(target, "norm.py"), "w").write(impl_src)
            return {"exit_code": 0, "files_changed": 1, "summary": "wrote norm.py"}
        return implement
    return make_implementer


_YES = (lambda t, c: True)   # injected fake judges keep the runner tests deterministic (no LLM)

_TESTS = (
    "def test_lower():\n    # dod: c1\n    from norm import normalize\n    assert normalize('AbC') == 'abc'\n\n"
    "def test_strip():\n    # dod: c2\n    from norm import normalize\n    assert normalize('a-b.c') == 'abc'\n")
_IMPL = "import re\n\n\ndef normalize(s):\n    return re.sub(r'[^a-z0-9]', '', s.lower())\n"


def test_designer_runtimeerror_routes_human_review():
    # A designer raising RuntimeError (e.g. testgen.collect_spec_map when pytest is missing) is an
    # ENVIRONMENT error -> graceful HUMAN_REVIEW, never COMPLETE, never implement. Fully
    # deterministic with just real git: the designer raises before any collection (no pytest/LLM).
    # Mutant flips the terminal in this except arm to COMPLETE -> a FALSE COMPLETE on zero written
    # code -> the terminal assertion fails -> killed.
    built = []

    def _designer_raises(target):
        def design(charter):
            raise RuntimeError("pytest unavailable")
        return design

    with tempfile.TemporaryDirectory() as root:
        repo = _init_repo(root)
        res = runner.run_task(repo, "x", os.path.join(root, "wts"), "traise",
                              judge_a=_YES, judge_b=_YES,
                              make_charter=lambda req: _charter(["c1"]),
                              make_designer=_designer_raises,
                              make_implementer=lambda target: (lambda *a: built.append(1)))
        assert res["result"]["terminal"] == "HUMAN_REVIEW", res["result"]   # mutant -> COMPLETE fails here
        assert "pytest unavailable" in res["result"]["reason"]              # the env error is surfaced
        assert built == []                                                  # never implemented


def test_real_path_enforces_distinct_models_before_worktree():
    # Force a model collision (DESIGNER == CODER). The real path (judge_a/judge_b both None) must call
    # dispatch.assert_distinct_models(CODER, DESIGNER, JUDGE_A, JUDGE_B) and RAISE RuntimeError BEFORE
    # worktree.create_worktree and BEFORE make_charter -> no git/LLM touched. The mutant only passes
    # CODER (a single id is trivially distinct) so it never raises and falls through to the worktree.
    orig_designer, orig_create = dispatch.DESIGNER, worktree.create_worktree
    reached = []

    class _Reached(Exception):
        pass

    def _trap(*a, **k):
        reached.append(1)
        raise _Reached()

    worktree.create_worktree = _trap
    dispatch.DESIGNER = dispatch.CODER          # coder == designer collision
    try:
        raised = False
        try:
            runner.run_task("repo", "req", "root", "n", judge_a=None, judge_b=None)
        except RuntimeError as e:
            raised = True
            assert "distinct" in str(e)         # the no-self-grading gate fired
        assert raised                           # gate raised on the real path...
        assert reached == []                    # ...before any worktree creation (and before charter/LLM)
    finally:
        dispatch.DESIGNER = orig_designer
        worktree.create_worktree = orig_create
    # Mutant (single CODER arg): no dup -> no RuntimeError -> reaches _trap -> reached==[1] and the
    # _Reached (not RuntimeError) propagates out -> this test fails/errors. Killed.


def test_default_designer_is_the_structured_spec_designer():
    # Do NOT inject make_designer -> exercises the default selection. The STRUCTURED
    # dispatch.designer_spec_via_ask is THE designer (the free-form path + its env switch were
    # DELETED 2026-07-01). Swap the module attr for a tagged fake and assert it is chosen.
    # Mutant killed: runner default swapped for an empty-map stub (coverage fails instead).
    if not _HAS_PYTEST:
        print("SKIP test_default_designer_is_the_structured_spec_designer (pytest not available)"); return
    orig_spec = dispatch.designer_spec_via_ask
    picked = []

    def _fake_spec(target):
        def design(charter):
            open(os.path.join(target, "test_z.py"), "w").write(
                "def test_z():\n    assert True\n")
            picked.append("spec")
            return testgen.collect_spec_map(target, {"test_z.py::test_z": "c1"})
        return design

    dispatch.designer_spec_via_ask = _fake_spec
    try:
        with tempfile.TemporaryDirectory() as root:
            repo = _init_repo(root)
            runner.run_task(repo, "x", os.path.join(root, "wts"), "tmode",
                            judge_a=_YES, judge_b=_YES,
                            make_charter=lambda req: _charter(["c1"]),
                            make_implementer=_implementer_writes("x = 1\n"))
        assert picked == ["spec"], picked   # the structured designer IS the default
    finally:
        dispatch.designer_spec_via_ask = orig_spec


def test_non_python_request_fails_closed_via_coverage():
    # SKILL.md guarantee pinned (T2, 2026-07-02 audit): devloop's oracle is pytest-only, so a
    # non-Python request must fail CLOSED (coverage gate -> HUMAN_REVIEW), never COMPLETE on
    # vacuous evidence. A Go request's real designer collection yields {} (nothing
    # pytest-collectable) — modeled by a designer returning an empty map; the implementer and
    # judges are spies that must never fire.
    built, judged = [], []

    def judge_spy(t, c):
        judged.append(1)
        return True

    with tempfile.TemporaryDirectory() as root:
        repo = _init_repo(root)
        res = runner.run_task(repo, "write a Go package with a Sum(a, b int) function",
                              os.path.join(root, "wts"), "tgo",
                              judge_a=judge_spy, judge_b=judge_spy,
                              make_charter=lambda req: _charter(["c1"]),
                              make_designer=lambda target: (lambda charter: {}),
                              make_implementer=lambda target: (lambda *a: built.append(1)))
        assert res["result"]["terminal"] == "HUMAN_REVIEW", res["result"]
        assert "no covering test" in res["result"]["reason"]
        assert built == [] and judged == []                     # never implemented, never judged


def test_vague_block_is_non_retryable_but_ambiguity_block_is_retryable():
    # A vague-goal HUMAN_REVIEW is deterministic on the request TEXT — a re-attempt reproduces
    # it — so run_task marks it retryable=False (the project loop escalates instead of burning
    # its cap). An ambiguity HR (low confidence) is model-drafted and stays retryable.
    # Mutant killed: `"retryable": not vague` -> `"retryable": True`.
    with tempfile.TemporaryDirectory() as root:
        repo = _init_repo(root)
        res = runner.run_task(repo, "make the app faster", os.path.join(root, "w1"), "tvague",
                              judge_a=_YES, judge_b=_YES,
                              make_charter=lambda req: _charter(["c1"]))
        assert res["result"]["terminal"] == "HUMAN_REVIEW"
        assert "vague quality goal" in res["result"]["reason"]
        assert res["result"]["retryable"] is False               # deterministic -> escalate upstream

        low_conf = _charter(["c1"])
        low_conf["assumptions"] = [{"text": "a", "confidence": 0.2}]
        res = runner.run_task(repo, "add a widget", os.path.join(root, "w2"), "tamb",
                              judge_a=_YES, judge_b=_YES,
                              make_charter=lambda req: low_conf)
        assert res["result"]["terminal"] == "HUMAN_REVIEW"
        assert "confidence" in res["result"]["reason"]
        assert res["result"]["retryable"] is True                # model-drafted -> lessons can help


def test_folded_lessons_never_reach_the_vague_goal_gate():
    # E4: the project loop folds lesson lines (which carry markers + numbers: "FASTER",
    # "changed 3 file(s)") under config.LESSONS_HEADER. run_task must gate on the text BEFORE
    # that header only — proven here by a concrete request + marker-laden lessons flowing PAST
    # both gates into the designer (which raises a recognizable env error). With the strip
    # mutant, the vague gate fires first and the reason is a vague-goal message instead.
    # Mutant killed: `goal_text = request.split(config.LESSONS_HEADER, 1)[0]` -> `request`.
    def _designer_env_error(target):
        def design(charter):
            raise RuntimeError("pytest unavailable")
        return design

    request = ("add a normalize function\n\n" + config.LESSONS_HEADER + "\n"
               "- HUMAN_REVIEW: make it FASTER — changed 3 file(s); reason: too slow")
    with tempfile.TemporaryDirectory() as root:
        repo = _init_repo(root)
        res = runner.run_task(repo, request, os.path.join(root, "wts"), "tlessons",
                              judge_a=_YES, judge_b=_YES,
                              make_charter=lambda req: _charter(["c1"]),
                              make_designer=_designer_env_error)
        assert res["result"]["terminal"] == "HUMAN_REVIEW"
        assert res["result"]["reason"] == "pytest unavailable", res["result"]   # PAST the gates


def _branch_exists(repo, branch):
    return subprocess.run(["git", "-C", repo, "rev-parse", "--verify", f"refs/heads/{branch}"],
                          capture_output=True).returncode == 0


def test_crash_before_any_work_leaks_nothing():
    # CRASH-FINALIZE (fix 2026-07-02): an exception once the worktree exists (here: the charter
    # dispatcher crashing) must still propagate (fail-closed via call_guarded upstream) but may
    # NOT leak the checkout or the devloop/<name> branch — 41 of each had leaked via this path.
    # No work was produced -> "no artifact, no branch": BOTH are removed.
    # Mutant killed: the crash-handler's finalize -> `pass` (the leak resurrected).
    def _charter_raises(req):
        raise ValueError("planner exploded")

    with tempfile.TemporaryDirectory() as root:
        repo = _init_repo(root)
        wts = os.path.join(root, "wts")
        raised = False
        try:
            runner.run_task(repo, "x", wts, "tcrash", judge_a=_YES, judge_b=_YES,
                            make_charter=_charter_raises)
        except ValueError:
            raised = True
        assert raised                                            # the error still propagates
        assert not os.path.isdir(os.path.join(wts, "tcrash"))    # checkout removed
        assert not _branch_exists(repo, "devloop/tcrash")        # empty branch removed


def test_crash_after_real_work_keeps_committed_branch_removes_checkout():
    # A crash AFTER real work exists (here: the designer writes a file then dies) keeps the
    # branch-for-review semantics: the work is committed onto devloop/<name> (the crash is named
    # in the commit subject), the branch survives, the checkout is still removed.
    def _designer_writes_then_dies(target):
        def design(charter):
            open(os.path.join(target, "partial.py"), "w").write("x = 1\n")
            raise ValueError("designer exploded")   # NOT RuntimeError (that routes to HR gracefully)
        return design

    with tempfile.TemporaryDirectory() as root:
        repo = _init_repo(root)
        wts = os.path.join(root, "wts")
        raised = False
        try:
            runner.run_task(repo, "x", wts, "tcrash2", judge_a=_YES, judge_b=_YES,
                            make_charter=lambda req: _charter(["c1"]),
                            make_designer=_designer_writes_then_dies)
        except ValueError:
            raised = True
        assert raised
        assert not os.path.isdir(os.path.join(wts, "tcrash2"))   # checkout removed
        assert _branch_exists(repo, "devloop/tcrash2")           # ...but the work survives
        show = subprocess.run(["git", "-C", repo, "show", "devloop/tcrash2:partial.py"],
                              capture_output=True, text=True)
        assert show.stdout == "x = 1\n"                          # committed, reviewable
        subject = subprocess.run(["git", "-C", repo, "log", "-1", "--format=%s", "devloop/tcrash2"],
                                 capture_output=True, text=True).stdout
        assert "CRASHED (ValueError)" in subject                 # the crash is named in provenance


def test_default_charter_is_environment_aware():
    # user ask 2026-07-02: the DEFAULT charter stage must receive the run's target checkout so
    # its prompt can carry the environment survey (investigate what exists BEFORE solving).
    # Trap the module attr and capture target_dir; run_task's crash-finalize re-raises the trap.
    # Mutant killed: runner binds target_dir=None (repo-blind interpretation resurrected).
    orig = dispatch.charter_via_ask
    seen = {}

    class _Reached(Exception):
        pass

    def _trap(request, planner=None, target_dir=None):
        seen["target_dir"] = target_dir
        raise _Reached()

    dispatch.charter_via_ask = _trap
    try:
        with tempfile.TemporaryDirectory() as root:
            repo = _init_repo(root)
            raised = False
            try:
                runner.run_task(repo, "req", os.path.join(root, "wts"), "envaware")
            except _Reached:
                raised = True
            assert raised                                            # the default path was taken
            assert seen["target_dir"] and "envaware" in seen["target_dir"]   # = the run's checkout
    finally:
        dispatch.charter_via_ask = orig


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} runner tests run")
