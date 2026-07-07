"""More deterministic tests for dispatch.py (no LLM): close confirmed coverage gaps in the
public planner/coder dispatchers, the snapshot-diff helpers, AND the `hermes chat` subprocess
seam itself (a real executable stub stands in for HERMES_BIN — the model boundary where a raw
reply becomes a charter/verdict is the primary false-COMPLETE injection surface)."""
import json
import os
import sys
import tempfile
import types

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import state      # noqa: E402
import dispatch   # noqa: E402


def test_charter_via_ask_failclosed_blocking_question():
    # charter_via_ask's documented fail-closed contract: unparseable OR empty-dod planner output
    # -> a Charter with empty dod carrying a BLOCKING "unparseable" open_question. Mutant flips
    # that blocking flag True->False (it would still validate-fail downstream, but the contract
    # the dispatcher PROMISES is the blocking signal).
    orig = dispatch._chat
    try:
        # 1) pure garbage (no JSON at all) -> fail-closed branch
        dispatch._chat = lambda p, m, **k: ("planner rambled, no JSON here", 0)
        ch = dispatch.charter_via_ask("build X")
        assert ch["dod"] == []
        assert any(q.get("blocking") and "unparseable" in q.get("text", "")
                   for q in ch["open_questions"])               # kills blocking True->False
        assert state.validate_charter(ch) != []                 # empty-dod charter is invalid (routing anchor)
        # 2) parseable-but-EMPTY dod hits the SAME fail-closed branch (`not data.get("dod")`)
        dispatch._chat = lambda p, m, **k: ('{"interpreted_intent":"x","dod":[]}', 0)
        ch2 = dispatch.charter_via_ask("X")
        assert ch2["dod"] == []
        assert any(q.get("blocking") for q in ch2["open_questions"])   # blocking flag still True
        # control: a GOOD planner output is passed through WITHOUT a synthetic blocking question,
        # proving the blocking flag is exclusive to the fail-closed branch (not asserted vacuously).
        dispatch._chat = lambda p, m, **k: (
            '{"interpreted_intent":"add","dod":[{"criterion":"add(a,b) returns a+b",'
            '"verify_intent":"add(2,3)==5"}],"assumptions":[],"open_questions":[]}', 0)
        good = dispatch.charter_via_ask("add(a,b)")
        assert good["dod"] and good["open_questions"] == []
    finally:
        dispatch._chat = orig


def test_implement_passes_through_real_exit_code():
    # The coder process's real returncode flows into result["exit_code"] -> drives loop.py's
    # dispatch-error fast-fail (`exit_code not in (0, None)`). A hardcoded 0 masks a crashed coder
    # as success, so the loop runs lint/tests on unchanged code and burns an attempt on a dead dispatch.
    charter = {"interpreted_intent": "i", "dod": [{"criterion": "c", "verify_intent": "v"}]}
    orig = dispatch._chat
    with tempfile.TemporaryDirectory() as d:
        try:
            dispatch._chat = lambda p, m, **k: ("boom\ntraceback", 7)   # coder PROCESS errored
            res = dispatch.implementer_via_ask(d)(charter, 1, None)
            assert res["exit_code"] == 7         # passthrough; the constant-0 mutant -> 7 != 0 fails
            dispatch._chat = lambda p, m, **k: ("ok", 0)               # control: clean exit passes 0
            assert dispatch.implementer_via_ask(d)(charter, 1, None)["exit_code"] == 0
        finally:
            dispatch._chat = orig


def test_implement_injects_last_failure_feedback():
    # `if last_failure:` folds the prior failure into the coder prompt so it learns WHY it failed.
    # `if False:` drops the feedback -> the coder repeats the same mistake until the backoff cap.
    charter = {"interpreted_intent": "i", "dod": [{"criterion": "c", "verify_intent": "v"}]}
    seen = {}
    orig = dispatch._chat
    with tempfile.TemporaryDirectory() as d:
        try:
            dispatch._chat = lambda p, m, **k: (seen.update(p=p) or ("ok", 0))
            dispatch.implementer_via_ask(d)(charter, 2, {"reason": "tests failed: AssertionError"})
            assert "previous attempt FAILED" in seen["p"]        # repair feedback injected (kills if-False)
            assert "tests failed: AssertionError" in seen["p"]   # the actual failure detail is shown
            dispatch.implementer_via_ask(d)(charter, 1, None)    # control: no prior failure
            assert "previous attempt FAILED" not in seen["p"]    # nothing injected -> clean prompt
        finally:
            dispatch._chat = orig


def test_count_changed_counts_deletions():
    # _count_changed must count a DELETED file (present in `before`, gone from `after`) as a change:
    # a coder whose only legit action is deleting an obsolete file still changed something. The mutant
    # zeroes the deletion term, so files_changed would read 0 -> a false "coder made no change" abort.
    assert dispatch._count_changed({"/a": (1, 1), "/b": (1, 1)}, {"/a": (1, 1)}) == 1   # /b deleted -> 1
    # controls (no deletions, so they pass with or without the term) pin modify+create and the no-op:
    assert dispatch._count_changed({"/a": (1, 1)}, {"/a": (2, 2), "/c": (3, 3)}) == 2   # modified + created
    assert dispatch._count_changed({"/a": (1, 1)}, {"/a": (1, 1)}) == 0                  # unchanged -> 0


def test_implement_surfaces_changed_paths():
    # implement must SURFACE the files the coder actually touched (changed_paths) -- loop._lint_gate
    # short-circuits to ok when changed_paths is empty, so a constant [] silently disables the lint gate.
    charter = {"interpreted_intent": "i", "dod": [{"criterion": "c", "verify_intent": "v"}]}
    orig = dispatch._chat
    with tempfile.TemporaryDirectory() as d:
        impl = os.path.join(d, "impl.py")
        try:
            def writes(p, m, **k):
                open(impl, "w").write("def f():\n    return 1\n")
                return ("done", 0)
            dispatch._chat = writes
            res = dispatch.implementer_via_ask(d)(charter, 1, None)
            assert impl in res["changed_paths"]    # the touched file IS surfaced; constant [] fails here
            assert res["files_changed"] == 1
            # control: a coder that writes NOTHING surfaces an EMPTY list (not a constant non-empty),
            # so the membership assert above is genuinely tracking reality. impl.py now exists+unchanged.
            dispatch._chat = lambda p, m, **k: ("noop", 0)
            res2 = dispatch.implementer_via_ask(d)(charter, 1, None)
            assert res2["changed_paths"] == []
        finally:
            dispatch._chat = orig


# --- the `hermes chat` subprocess seam itself (T1, 2026-07-02 audit) ---------------------------
def test_chat_raw_argv_contract_and_extraction_via_real_stub():
    # A REAL executable stands in for HERMES_BIN: it records its argv and prints a noisy,
    # real-shaped reply with a fenced JSON charter. Pins (a) the exact argv contract
    # (`chat -q <prompt> -m <model> -Q --yolo [+ -t <toolsets>]`) and (b) the end-to-end
    # noisy-reply -> _extract_json -> _wrap_charter path through charter_via_ask.
    reply = ("let me think about this...\n"
             "Here is the charter:\n"
             "```json\n"
             '{"interpreted_intent": "add two numbers",\n'
             ' "dod": [{"criterion": "add(a,b) returns a+b", "verify_intent": "add(2,3)==5"}],\n'
             ' "assumptions": [{"text": "ints", "confidence": 0.9}], "open_questions": []}\n'
             "```\n"
             "hope that helps!\n")
    with tempfile.TemporaryDirectory() as d:
        argv_log = os.path.join(d, "argv.json")
        stub = os.path.join(d, "hermes")
        open(stub, "w").write("#!/usr/bin/env python3\n"
                              "import json, sys\n"
                              f"json.dump(sys.argv[1:], open({argv_log!r}, 'w'))\n"
                              f"sys.stdout.write({reply!r})\n")
        os.chmod(stub, 0o755)
        orig = dispatch.HERMES_BIN
        dispatch.HERMES_BIN = stub
        try:
            ch = dispatch.charter_via_ask("add(a,b)")
            argv = json.load(open(argv_log))
            assert argv[0:2] == ["chat", "-q"]
            assert argv[2].endswith("add(a,b)")                    # prompt = charter prompt + request
            assert argv[3] == "-m" and argv[4] == dispatch.PLANNER  # the configured planner model
            assert argv[5:] == ["-Q", "--yolo"]                    # toolsets="" -> no -t appended
            # the noisy reply parsed into a REAL charter, not the fail-closed unparseable branch
            assert ch["dod"] and ch["dod"][0]["id"] == "c1"
            assert ch["dod"][0]["criterion"] == "add(a,b) returns a+b"
            assert ch["open_questions"] == []
            # toolsets append the -t flag (the coder path)
            out, code = dispatch._chat_raw("hi", "some-model", toolsets="file,terminal")
            argv = json.load(open(argv_log))
            assert argv == ["chat", "-q", "hi", "-m", "some-model", "-Q", "--yolo",
                            "-t", "file,terminal"]
            assert code == 0 and "hope that helps" in out
        finally:
            dispatch.HERMES_BIN = orig


def test_chat_raw_wires_the_dispatch_timeout_floor():
    # The subprocess ceiling must be `timeout or _dispatch_timeout()`: an unset caller timeout
    # gets the >=1800s floor, NEVER None (an unbounded hang on a wedged model call). Mutant
    # killed: `timeout=timeout or _dispatch_timeout()` -> `timeout=timeout`.
    seen = {}

    def fake_run(cmd, **kw):
        seen.clear(); seen.update(kw, cmd=cmd)
        return types.SimpleNamespace(stdout="ok", stderr="", returncode=0)

    orig = dispatch.subprocess
    dispatch.subprocess = types.SimpleNamespace(run=fake_run)
    try:
        dispatch._chat_raw("p", "m")
        assert seen["timeout"] == dispatch._dispatch_timeout()     # floor applied when unset
        assert seen["timeout"] >= dispatch.DISPATCH_TIMEOUT_S      # and never below the floor
        dispatch._chat_raw("p", "m", timeout=7200)
        assert seen["timeout"] == 7200                             # explicit value passes through
    finally:
        dispatch.subprocess = orig


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} dispatch tests passed")
