"""Deterministic test of the FULL v1 pipeline (runner.run_task) — real git worktree, real pytest
collection, real per-criterion evidence. NO LLM (the charter/designer/implementer outputs are
scripted; everything else is real).

Proves end-to-end: worktree isolation -> design writes real collectable annotated tests ->
coverage derived from REAL nodes -> implement -> per-criterion pytest evidence -> COMPLETE. Plus
the legitimacy guard: a criterion with no real test fails closed -> HUMAN_REVIEW (no implement).
"""
import os
import subprocess
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import runner   # noqa: E402
import testgen  # noqa: E402


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


def test_full_v1_pipeline_completes_with_real_git_and_pytest():
    if not _HAS_PYTEST:
        print("SKIP test_full_v1_pipeline (pytest not available)"); return
    with tempfile.TemporaryDirectory() as root:
        repo = _init_repo(root)
        res = runner.run_task(repo, "normalize strings", os.path.join(root, "wts"), "t1",
                              judge_a=_YES, judge_b=_YES,
                              make_charter=lambda req: _charter(["c1", "c2"]),
                              make_designer=_designer_writes(_TESTS),
                              make_implementer=_implementer_writes(_IMPL))
        assert res["result"]["terminal"] == "COMPLETE", res["result"]
        wt = res["worktree"]["path"]
        assert os.path.exists(os.path.join(wt, "norm.py"))                 # code on the worktree branch
        assert not os.path.exists(os.path.join(repo, "norm.py"))           # original tree untouched


def test_full_v1_pipeline_failcloses_on_uncovered_criterion():
    if not _HAS_PYTEST:
        print("SKIP test_full_v1_pipeline_failclose (pytest not available)"); return
    with tempfile.TemporaryDirectory() as root:
        repo = _init_repo(root)
        built = []
        res = runner.run_task(repo, "normalize strings", os.path.join(root, "wts"), "t2",
                              judge_a=_YES, judge_b=_YES,
                              make_charter=lambda req: _charter(["c1", "c2", "c3"]),  # c3 unwritten
                              make_designer=_designer_writes(_TESTS),                  # only c1, c2
                              make_implementer=lambda target: (lambda *a: built.append(1)))
        assert res["result"]["terminal"] == "HUMAN_REVIEW"                 # coverage fails closed
        assert built == []                                                 # never implemented


def test_vague_charter_routes_human_without_designing():
    ch = _charter(["c1"])
    ch["open_questions"] = [{"text": "what exactly?", "blocking": True}]
    designed = []
    with tempfile.TemporaryDirectory() as root:
        repo = _init_repo(root)
        res = runner.run_task(repo, "do something", os.path.join(root, "wts"), "t3",
                              judge_a=_YES, judge_b=_YES,
                              make_charter=lambda req: ch,
                              make_designer=lambda target: (lambda c: designed.append(1)),
                              make_implementer=lambda target: (lambda *a: None))
        assert res["result"]["terminal"] == "HUMAN_REVIEW"
        assert designed == []                                              # never designed


def test_refiner_output_flows_to_ambiguity_gate():
    # the REFINE pass runs before the ambiguity gate, so the gate sees the REFINED charter: a
    # refiner that injects a blocking question must route to HUMAN_REVIEW without ever designing
    # (the draft alone would have PROCEEDed). Proves the refine pass is wired in the right place.
    designed = []
    with tempfile.TemporaryDirectory() as root:
        repo = _init_repo(root)
        res = runner.run_task(repo, "do x", os.path.join(root, "wts"), "tref",
                              judge_a=_YES, judge_b=_YES,
                              make_charter=lambda req: _charter(["c1"]),               # would PROCEED
                              make_refiner=lambda ch, req: {**ch, "open_questions": [{"text": "which file?", "blocking": True}]},
                              make_designer=lambda target: (lambda c: designed.append(1)),
                              make_implementer=lambda target: (lambda *a: None))
        assert res["result"]["terminal"] == "HUMAN_REVIEW"
        assert designed == []                                                          # never designed


def test_advisor_blocking_concern_routes_human():
    # the ADVISOR runs after refine, before the gate -> a blocking gap it adds reaches the gate and
    # routes to HUMAN_REVIEW without designing (the draft alone would have PROCEEDed).
    designed = []
    with tempfile.TemporaryDirectory() as root:
        repo = _init_repo(root)
        res = runner.run_task(repo, "do x", os.path.join(root, "wts"), "tadv",
                              judge_a=_YES, judge_b=_YES,
                              make_charter=lambda req: _charter(["c1"]),               # would PROCEED
                              make_advisor=lambda ch, req: {**ch, "open_questions": [{"text": "missing behavior", "blocking": True}]},
                              make_designer=lambda target: (lambda c: designed.append(1)),
                              make_implementer=lambda target: (lambda *a: None))
        assert res["result"]["terminal"] == "HUMAN_REVIEW"
        assert designed == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} runner tests run")
