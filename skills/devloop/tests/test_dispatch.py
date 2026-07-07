"""Deterministic tests for dispatch.py's pure parts (no LLM): JSON extraction + Charter wrap."""
import os
import sys

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import state      # noqa: E402
import dispatch   # noqa: E402


def test_extract_json_variants():
    assert dispatch._extract_json('intro ```json\n{"a": 1}\n``` outro')["a"] == 1
    assert dispatch._extract_json('blah {"b": 2, "c": [1, 2]} tail')["b"] == 2
    assert dispatch._extract_json("no json at all") is None
    assert dispatch._extract_json('{"unterminated": ') is None   # invalid -> None, not a crash


def test_wrap_charter_assigns_ids_and_is_valid():
    ch = dispatch._wrap_charter({
        "interpreted_intent": "do x",
        "dod": [{"criterion": "works", "verify_intent": "exit 0"},
                {"criterion": "also", "verify_intent": "no error"}],
        "assumptions": [{"text": "a", "confidence": 0.9}],
        "open_questions": [],
    })
    assert [c["id"] for c in ch["dod"]] == ["c1", "c2"]      # stable assigned ids
    assert state.validate_charter(ch) == []                  # a wrapped charter is structurally valid


def test_wrap_charter_empty_dod_is_failclosed():
    # the charter_via_ask fail-closed path: empty dod -> invalid -> ambiguity gate routes to human
    ch = dispatch._wrap_charter({"interpreted_intent": "x", "dod": [], "assumptions": [],
                                 "open_questions": [{"text": "q", "blocking": True}]})
    assert state.validate_charter(ch) != []


def test_is_yes_failclosed():
    assert dispatch._is_yes("YES") is True
    assert dispatch._is_yes("yes, it verifies the criterion") is True
    assert dispatch._is_yes("NO") is False
    assert dispatch._is_yes("no, it does not") is False
    assert dispatch._is_yes("maybe / unsure") is False        # no clear token -> fail-closed
    assert dispatch._is_yes("YES but actually no") is False    # ambiguous -> fail-closed
    assert dispatch._is_yes("") is False


def test_assert_distinct_models():
    dispatch.assert_distinct_models("coder", "designer", "judgeA", "judgeB")   # all distinct -> ok
    dispatch.assert_distinct_models("a", "b", None)                            # None ignored
    raised = False
    try:
        dispatch.assert_distinct_models("a", "b", "a")     # a model grading its own work
    except RuntimeError:
        raised = True
    assert raised


def test_judge_via_ask_reads_real_source_and_parses_failclosed():
    import tempfile
    import testgen  # noqa: F401  (ensures the import path is set up)
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "test_x.py"), "w").write(
            "def test_a():\n    # dod: c1\n    from norm import normalize\n    assert normalize('A') == 'a'\n")
        seen = {}
        orig = dispatch._chat
        dispatch._chat = lambda prompt, model, **kw: (seen.update(p=prompt) or ("YES", 0))
        try:
            judge = dispatch.judge_via_ask("judge-model", d)
            # collective contract: judge(criterion, [test_ids]); the prompt shows REAL source + criterion
            assert judge({"criterion": "lowercases input"}, ["test_x.py::test_a"])[0] is True
            assert "normalize('A')" in seen["p"] and "lowercases input" in seen["p"]   # saw REAL source + criterion
            dispatch._chat = lambda *a, **k: ("NO", 0)
            assert judge({"criterion": "x"}, ["test_x.py::test_a"])[0] is False
            assert judge({"criterion": "x"}, ["test_x.py::missing"])[0] is False    # no source -> fail-closed
            assert judge({"criterion": "x"}, [])[0] is False                        # no tests -> fail-closed
        finally:
            dispatch._chat = orig


def test_refiner_via_ask_refines_and_is_failsafe():
    draft = dispatch._wrap_charter({
        "interpreted_intent": "make add",
        "dod": [{"criterion": "calc.py exists and defines add and returns the sum", "verify_intent": "x"}],
        "assumptions": [], "open_questions": []})
    orig = dispatch._chat
    seen = {}
    # happy path: the refiner returns a cleaner charter -> it is re-wrapped (valid, stable ids)
    dispatch._chat = lambda p, m, **k: (seen.update(p=p) or (
        '{"interpreted_intent":"make add","dod":[{"criterion":"add(a,b) returns a+b",'
        '"verify_intent":"add(2,3)==5"}],"assumptions":[],"open_questions":[]}', 0))
    try:
        refined = dispatch.refiner_via_ask(draft, "create add(a,b)")
        assert [c["criterion"] for c in refined["dod"]] == ["add(a,b) returns a+b"]
        assert refined["dod"][0]["id"] == "c1" and state.validate_charter(refined) == []
        assert "exists and defines add" in seen["p"]          # the refiner SAW the draft to fix it
        # fail-safe: unparseable refiner output -> KEEP the (valid) draft, never discard it
        dispatch._chat = lambda p, m, **k: ("sorry, no json here", 0)
        assert dispatch.refiner_via_ask(draft, "create add(a,b)") is draft
    finally:
        dispatch._chat = orig


def test_advisor_via_ask_folds_blocking_concerns_and_failsafe():
    ch = {"dod": [{"criterion": "delegates to the sum helper"}], "open_questions": []}
    orig = dispatch._chat
    seen = {}
    dispatch._chat = lambda p, m, **k: (seen.update(p=p) or (
        '{"concerns":[{"text":"missing edge case","blocking":true},'
        '{"text":"minor nit","blocking":false}]}', 0))
    try:
        out = dispatch.advisor_via_ask(ch, "build the calculator")
        oqs = out["open_questions"]
        assert any(q.get("blocking") and "missing edge case" in q.get("text", "") for q in oqs)
        assert not any("minor nit" in q.get("text", "") for q in oqs)   # advisory concern NOT surfaced
        assert "delegates to the sum helper" in seen["p"] and "build the calculator" in seen["p"]  # saw DoD + request
        dispatch._chat = lambda p, m, **k: ('{"concerns":[]}', 0)
        assert dispatch.advisor_via_ask(ch, "do x") is ch               # no blocking gap -> unchanged
        dispatch._chat = lambda p, m, **k: ("not json", 0)
        assert dispatch.advisor_via_ask(ch, "do x") is ch               # garbage -> fail-safe
        # a blocking concern with NO text must NOT block a good plan (over-block garbage filtered)
        dispatch._chat = lambda p, m, **k: ('{"concerns":[{"blocking":true}]}', 0)
        assert dispatch.advisor_via_ask(ch, "do x") is ch
    finally:
        dispatch._chat = orig


def test_advisor_preserves_existing_blocking_questions_failclosed():
    # the load-bearing fail-closed property: folding the advisor's concern must NEVER drop a blocking
    # question the planner/refiner already raised. A regression that OVERWROTE open_questions would
    # silently un-block a charter that should route to a human -> a false PROCEED.
    ch = {"dod": [{"criterion": "x"}],
          "open_questions": [{"text": "planner: which datastore?", "blocking": True},
                             {"text": "refiner: idempotent?", "blocking": False}]}
    orig = dispatch._chat
    dispatch._chat = lambda p, m, **k: ('{"concerns":[{"text":"advisor gap","blocking":true}]}', 0)
    try:
        out = dispatch.advisor_via_ask(ch, "do x")
        texts = [q.get("text", "") for q in out["open_questions"]]
        assert any("planner: which datastore?" in t for t in texts)    # pre-existing blocking survives
        assert any("refiner: idempotent?" in t for t in texts)          # pre-existing advisory survives
        assert any("advisor gap" in t for t in texts)                   # advisor's concern appended
        assert ch["open_questions"] == [{"text": "planner: which datastore?", "blocking": True},
                                        {"text": "refiner: idempotent?", "blocking": False}]  # input not mutated
    finally:
        dispatch._chat = orig


def test_implementer_prompt_includes_handoff_style_and_dod():
    import tempfile
    # the coder prompt must carry the handoff-quality directives (breadcrumbs/docs + targeted
    # error-checking) BY CONSTRUCTION, framed as how-to (not new DoD), AND still carry the DoD/intent.
    charter = {"interpreted_intent": "build a thing",
               "dod": [{"id": "c1", "criterion": "add(a,b) returns a+b", "verify_intent": "add(2,3)==5"}]}
    orig = dispatch._chat
    seen = {}
    dispatch._chat = lambda p, m, **k: (seen.update(p=p) or ("done", 0))
    try:
        with tempfile.TemporaryDirectory() as d:
            res = dispatch.implementer_via_ask(d)(charter, 0, None)
        p = seen["p"]
        assert "BREADCRUMB" in p and "ERROR-CHECKING" in p            # handoff-quality directives present
        assert "NOT new requirements" in p                           # framed how-to, not extra scope
        assert "add(a,b) returns a+b" in p and "build a thing" in p   # still carries the DoD + intent
        assert res["exit_code"] == 0 and "changed_paths" in res       # loop-facing result shape preserved
    finally:
        dispatch._chat = orig


def test_implementer_prompt_carries_assumptions_as_guidance():
    import tempfile
    # Behavior-not-structure moves "use module Y" preferences OUT of the DoD into assumptions —
    # so the coder must SEE them (deep review 2026-07-01: they were write-only before). Framed as
    # guidance, never as new requirements. Mutant killed: assump forced to "" (plumb-through cut).
    charter = {"interpreted_intent": "build a thing",
               "dod": [{"id": "c1", "criterion": "primes(nums) returns the primes", "verify_intent": "primes([2,3,4])==[2,3]"}],
               "assumptions": [{"text": "reuse mathutils.is_prime rather than reimplementing", "confidence": 0.9},
                               "not-a-dict-slips-through-safely"]}
    orig = dispatch._chat
    seen = {}
    dispatch._chat = lambda p, m, **k: (seen.update(p=p) or ("done", 0))
    try:
        with tempfile.TemporaryDirectory() as d:
            dispatch.implementer_via_ask(d)(charter, 0, None)
        p1 = seen["p"]
        assert "reuse mathutils.is_prime" in p1                      # the recorded preference reaches the coder
        assert "NOT new requirements" in p1                          # guidance framing, no scope inflation
        assert "not-a-dict" not in p1                                # malformed entries filtered, not crashed
    finally:
        dispatch._chat = orig


def test_implementer_prompt_omits_assumptions_block_when_empty():
    import tempfile
    charter = {"interpreted_intent": "x",
               "dod": [{"id": "c1", "criterion": "c", "verify_intent": "v"}], "assumptions": []}
    orig = dispatch._chat
    seen = {}
    dispatch._chat = lambda p, m, **k: (seen.update(p=p) or ("done", 0))
    try:
        with tempfile.TemporaryDirectory() as d:
            dispatch.implementer_via_ask(d)(charter, 0, None)
        assert "Assumptions (context" not in seen["p"]               # no empty boilerplate block
    finally:
        dispatch._chat = orig


def test_dispatch_timeout_floor_is_raise_only():
    # The per-call ceiling can be RAISED via DEVLOOP_DISPATCH_TIMEOUT_S but NEVER lowered
    # (max() clamp; project policy: never shorten timeouts to "fix" a slow model).
    # Mutant killed: max( -> min( (a 600s env would silently shorten every model call).
    orig = os.environ.pop("DEVLOOP_DISPATCH_TIMEOUT_S", None)
    try:
        assert dispatch._dispatch_timeout() == dispatch.DISPATCH_TIMEOUT_S       # unset -> floor
        os.environ["DEVLOOP_DISPATCH_TIMEOUT_S"] = "600"
        assert dispatch._dispatch_timeout() == dispatch.DISPATCH_TIMEOUT_S       # lower -> clamped UP
        os.environ["DEVLOOP_DISPATCH_TIMEOUT_S"] = "7200"
        assert dispatch._dispatch_timeout() == 7200                              # higher -> honored
        os.environ["DEVLOOP_DISPATCH_TIMEOUT_S"] = "garbage"
        assert dispatch._dispatch_timeout() == dispatch.DISPATCH_TIMEOUT_S       # junk -> floor
    finally:
        if orig is None:
            os.environ.pop("DEVLOOP_DISPATCH_TIMEOUT_S", None)
        else:
            os.environ["DEVLOOP_DISPATCH_TIMEOUT_S"] = orig


# --- #36: per-phase dispatch retry on a transient (empty/refusal/error) result ----------------
def test_chat_retries_refusal_then_succeeds():
    calls = {"n": 0}
    def flaky(prompt, model, **k):   # refuse twice, then a real answer
        calls["n"] += 1
        return ("As an AI, I cannot do that.", 0) if calls["n"] <= 2 else ("def add(a, b): return a + b", 0)
    orig_raw, orig_sleep = dispatch._chat_raw, dispatch._sleep
    dispatch._chat_raw = flaky; dispatch._sleep = lambda *_: None
    try:
        out, code = dispatch._chat("p", "m", retries=3)
        assert out.startswith("def add") and code == 0 and calls["n"] == 3   # refusal retried -> recovered
    finally:
        dispatch._chat_raw, dispatch._sleep = orig_raw, orig_sleep


def test_chat_failcloses_after_retries_exhausted():
    def always_refuse(prompt, model, **k):
        return ("I cannot assist with that.", 0)
    orig_raw, orig_sleep = dispatch._chat_raw, dispatch._sleep
    dispatch._chat_raw = always_refuse; dispatch._sleep = lambda *_: None
    try:
        out, _ = dispatch._chat("p", "m", retries=2)
        assert "cannot assist" in out   # fail-closed: hand back the LAST (bad) result, never fabricate success
    finally:
        dispatch._chat_raw, dispatch._sleep = orig_raw, orig_sleep


def test_chat_raised_transport_error_is_retryable_and_failclosed():
    def boom(prompt, model, **k):
        raise OSError("connection reset")
    orig_raw, orig_sleep = dispatch._chat_raw, dispatch._sleep
    dispatch._chat_raw = boom; dispatch._sleep = lambda *_: None
    try:
        out, code = dispatch._chat("p", "m", retries=1)
        assert code == 1 and "dispatch error" in out and "connection reset" in out   # transport error -> result, not crash
    finally:
        dispatch._chat_raw, dispatch._sleep = orig_raw, orig_sleep


# --- #35: debug cascade — a stronger diagnoser escalates on a REPEAT failure ------------------
def test_implementer_escalates_diagnosis_on_repeat_failure():
    import tempfile
    charter = {"interpreted_intent": "x",
               "dod": [{"id": "c1", "criterion": "add works", "verify_intent": "add(2,3)==5"}]}
    captured = []
    orig = dispatch._chat
    dispatch._chat = lambda p, m, **k: (captured.append((m, p)) or ("diagnosis: off-by-one in add", 0))
    try:
        with tempfile.TemporaryDirectory() as d:
            impl = dispatch.implementer_via_ask(d)
            # attempt 0 (first build, no failure): NO diagnoser, just the coder
            captured.clear(); impl(charter, 0, None)
            assert [m for m, _ in captured] == [dispatch.CODER]
            assert "ROOT-CAUSE DIAGNOSIS" not in captured[0][1]
            # attempt 1 (a repeat): the escalated diagnoser runs and its guidance reaches the coder prompt
            captured.clear(); impl(charter, 1, {"c1": "AssertionError: add(2,3)==6"})
            assert dispatch.DIAGNOSER in [m for m, _ in captured]                 # escalation fired
            coder_prompt = [p for m, p in captured if m == dispatch.CODER][-1]
            assert "ROOT-CAUSE DIAGNOSIS" in coder_prompt and "off-by-one" in coder_prompt
    finally:
        dispatch._chat = orig


def test_diagnose_via_ask_failsafe_on_dispatch_error():
    orig = dispatch._chat
    dispatch._chat = lambda p, m, **k: ("dispatch error: timeout", 1)
    try:
        # a dispatch-error reply yields NO guidance (coder proceeds on the basic failure feedback)
        assert dispatch.diagnose_via_ask({"dod": [{"criterion": "x"}]}, {"c1": "fail"}, "/tmp") == ""
        dispatch._chat = lambda p, m, **k: ("root cause: missing return", 0)
        assert dispatch.diagnose_via_ask({"dod": [{"criterion": "x"}]}, {"c1": "fail"}, "/tmp") == "root cause: missing return"
    finally:
        dispatch._chat = orig


# --- determinism debiasing: judge + advisor MAJORITY vote (spike robustness round) ------------
def test_judge_majority_vote_damps_a_flaky_no():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "test_x.py"), "w").write(
            "def test_a():\n    # dod: c1\n    from m import f\n    assert f() == 1\n")
        orig = dispatch._chat
        try:
            seq = iter(["YES", "YES", "NO"])                 # 2/3 YES -> majority -> trusted
            dispatch._chat = lambda p, m, **k: (next(seq, "NO"), 0)
            judge = dispatch.judge_via_ask("jm", d)
            assert judge({"criterion": "x"}, ["test_x.py::test_a"])[0] is True   # a flaky single NO no longer sinks it
            seq2 = iter(["NO", "NO", "YES"])                 # 1/3 YES -> minority -> NOT trusted (fail-closed)
            dispatch._chat = lambda p, m, **k: (next(seq2, "NO"), 0)
            assert judge({"criterion": "x"}, ["test_x.py::test_a"])[0] is False
        finally:
            dispatch._chat = orig


def test_advisor_majority_vote_damps_a_flaky_block():
    ch = {"dod": [{"criterion": "x"}], "open_questions": []}
    orig = dispatch._chat
    try:
        seq = iter(['{"concerns":[{"text":"gap A","blocking":true}]}',
                    '{"concerns":[{"text":"gap A","blocking":true}]}', '{"concerns":[]}'])
        dispatch._chat = lambda p, m, **k: (next(seq, '{"concerns":[]}'), 0)   # 2/3 block -> majority -> blocks
        out = dispatch.advisor_via_ask(ch, "do x")
        assert any(q.get("blocking") and "gap A" in q.get("text", "") for q in out["open_questions"])
        seq2 = iter(['{"concerns":[{"text":"gap B","blocking":true}]}',
                     '{"concerns":[]}', '{"concerns":[]}'])                     # 1/3 block -> minority -> proceed
        dispatch._chat = lambda p, m, **k: (next(seq2, '{"concerns":[]}'), 0)
        assert dispatch.advisor_via_ask(ch, "do x") is ch
    finally:
        dispatch._chat = orig


# --- modify-task fix: designer gets the repo's real module->symbol map (never invent a module) ---
def test_repo_symbols_and_modules_hint():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "textutil.py"), "w").write(
            "import re\ndef normalize(s):\n    return s\ndef _private():\n    pass\n")
        open(os.path.join(d, "app.py"), "w").write(
            "from textutil import normalize\ndef make_key(l):\n    return l\n")
        open(os.path.join(d, "test_x.py"), "w").write("def test_a():\n    pass\n")   # tests must be excluded
        syms = dispatch._repo_symbols(d)
        assert syms == {"textutil": ["normalize"], "app": ["make_key"]}   # test_x + _private excluded
        hint = dispatch._existing_modules_hint(d)
        assert "textutil (normalize)" in hint and "app (make_key)" in hint and "NEVER invent" in hint
        with tempfile.TemporaryDirectory() as empty:
            assert dispatch._existing_modules_hint(empty) == ""           # greenfield -> no directive


def test_charter_and_refiner_prompts_carry_environment_survey():
    # ENVIRONMENT SURVEY (user ask 2026-07-02): interpretation must investigate what already
    # exists BEFORE building a solve — the charter/refine prompts (which run with NO file tools)
    # carry the target repo's modules + public symbols with an align-and-reuse directive that
    # never overrides the request; a greenfield target stays survey-free.
    # Mutants killed: survey dropped from the charter prompt / from the refine prompt.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "util.py"), "w").write("def helper():\n    return 1\n")
        seen = {}
        orig = dispatch._chat
        dispatch._chat = lambda p, m, **k: (seen.update(p=p) or (
            '{"interpreted_intent":"x","dod":[{"criterion":"c","verify_intent":"v"}],'
            '"assumptions":[],"open_questions":[]}', 0))
        try:
            dispatch.charter_via_ask("do the thing", target_dir=d)
            assert "EXISTING ENVIRONMENT" in seen["p"]
            assert "util" in seen["p"] and "helper" in seen["p"]     # the survey names real symbols
            assert "do the thing" in seen["p"]                       # the request is never displaced
            # anti-drift directive (live quick-spike catch: the survey induced unencodable
            # "preserves current output" criteria — preservation is the regression gate's job)
            assert "Do NOT write criteria about preserving" in seen["p"]

            ch = dispatch._wrap_charter({"interpreted_intent": "x",
                                         "dod": [{"criterion": "c", "verify_intent": "v"}],
                                         "assumptions": [], "open_questions": []})
            seen.clear()
            dispatch.refiner_via_ask(ch, "do the thing", target_dir=d)
            assert "EXISTING ENVIRONMENT" in seen["p"] and "helper" in seen["p"]

            seen.clear()
            dispatch.charter_via_ask("do the thing")                 # greenfield/no target
            assert "EXISTING ENVIRONMENT" not in seen["p"]
        finally:
            dispatch._chat = orig


def test_tier_scoping_reaches_every_seam():
    """Test-tier scoping (user ask 2026-07-03: small validate -> larger validate -> full
    validate): the charter scopes each criterion unit|integration, the designer gets the
    tier + the mock-isolation/no-mock-integration discipline, and the survey requires an
    integration criterion when modifying existing code. Mutants killed: tier allowlist
    dropped; survey integration directive gutted; designer TIER discipline gutted."""
    import tempfile
    # charter prompt declares the tier field; designer prompt carries the discipline
    assert '"tier": "unit"|"integration"' in dispatch._CHARTER_PROMPT
    assert "TIER discipline" in dispatch._DESIGN_SPEC_PROMPT
    assert "NEVER mock the function under test" in dispatch._DESIGN_SPEC_PROMPT
    # _wrap_charter: allowlisted tier threads through; unknown/missing fail-safe to unit
    ch = dispatch._wrap_charter({"interpreted_intent": "x", "dod": [
        {"criterion": "a", "verify_intent": "v", "tier": "integration"},
        {"criterion": "b", "verify_intent": "v", "tier": "bogus"},
        {"criterion": "c", "verify_intent": "v"}],
        "assumptions": [], "open_questions": []})
    assert [c["tier"] for c in ch["dod"]] == ["integration", "unit", "unit"]
    assert state.validate_charter(ch) == []
    # the environment survey (existing repos only) requires an integration-tier criterion
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "mod.py"), "w") as f:
            f.write("def helper():\n    return 1\n")
        s = dispatch._environment_survey(d)
        assert "integration-tier criterion" in s
    # the designer receives each criterion's tier
    seen = {}
    orig_chat, orig_collect = dispatch._chat, dispatch.testgen.collect_spec_map
    dispatch._chat = lambda p, m, **k: seen.update(p=p) or ("{}", 0)
    dispatch.testgen.collect_spec_map = lambda d, planned: planned
    try:
        with tempfile.TemporaryDirectory() as d:
            dispatch.designer_spec_via_ask(d)({"dod": [
                {"id": "c1", "criterion": "x", "verify_intent": "v", "tier": "integration"}]})
            assert '"tier": "integration"' in seen["p"]
    finally:
        dispatch._chat, dispatch.testgen.collect_spec_map = orig_chat, orig_collect


def test_debug_capture_gated_by_env():
    """C7: DEVLOOP_DEBUG=1 persists each model call's full prompt + raw reply into
    $DEVLOOP_DEBUG_DIR/dispatch/ for post-run diagnosis; OFF (the default) captures nothing.
    Mutant killed: debug gate inverted (captures when off)."""
    import tempfile
    saved = {k: os.environ.pop(k, None) for k in ("DEVLOOP_DEBUG", "DEVLOOP_DEBUG_DIR")}
    try:
        with tempfile.TemporaryDirectory() as d:
            os.environ["DEVLOOP_DEBUG_DIR"] = d
            dispatch._capture_debug("PROMPT-X", "model:x", "REPLY-Y")     # DEBUG off
            assert not os.path.isdir(os.path.join(d, "dispatch"))         # nothing captured
            os.environ["DEVLOOP_DEBUG"] = "1"
            dispatch._capture_debug("PROMPT-X", "model:x", "REPLY-Y")
            files = os.listdir(os.path.join(d, "dispatch"))
            assert len(files) == 1
            body = open(os.path.join(d, "dispatch", files[0])).read()
            assert "PROMPT-X" in body and "REPLY-Y" in body and "model:x" in body
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_coder_prompt_carries_harness_etiquette():
    """C6: shipped code must not reference the harness (live catch: the coder wrote
    'See test_devloop_dod.py:dod:c1' into production code), and must not spawn venvs
    (live catch: one coder .venv = 992 junk files)."""
    import tempfile
    seen = {}
    orig = dispatch._chat
    dispatch._chat = lambda p, m, **k: seen.update(p=p) or ("done", 0)
    try:
        with tempfile.TemporaryDirectory() as d:
            ch = {"interpreted_intent": "x",
                  "dod": [{"id": "c1", "criterion": "c", "verify_intent": "v"}],
                  "assumptions": []}
            dispatch.implementer_via_ask(d)(ch, 0, None)
            assert "as if the tests did not exist" in seen["p"]
            assert "test expectations," in seen["p"]              # narrating test totals is banned too
            assert "Do NOT create virtualenvs" in seen["p"]
            # anti-overfit (run-3 live catch: the coder special-cased summary() to mirror a
            # wrong test's arithmetic instead of letting it fail into the repair path)
            assert "NEVER overfit a wrong test" in seen["p"]
            assert "let that test fail" in seen["p"]
    finally:
        dispatch._chat = orig


def test_judge_prompt_requires_value_recompute():
    """P1a (run-3 live catch): the judges approved a test asserting words=4/chars=19 where the
    honest values were 3/18 — the prompt only asked 'do the tests verify the criterion?'. It now
    requires RECOMPUTING each asserted value from the criterion's semantics.
    Mutant killed: recompute directive gutted."""
    import tempfile
    seen = {}
    orig = dispatch._chat
    dispatch._chat = lambda p, m, **k: seen.update(p=p) or ("YES", 0)
    try:
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "test_x.py"), "w") as f:
                f.write("def test_x():\n    assert True\n")
            verdict = dispatch.judge_via_ask("m", d)({"criterion": "c"}, ["test_x.py::test_x"])
            assert verdict[0] is True                                # mocked YES majority
            assert "RECOMPUTE each asserted expected value" in seen["p"]
            assert "WRONG test" in seen["p"]
    finally:
        dispatch._chat = orig


def test_designer_spec_threads_run_name_into_oracle_filename():
    """C2: the rendered oracle filename embeds the worktree basename — per-run files, so
    re-runs accumulate DoD protection and concurrent runs never merge-conflict on the oracle."""
    import tempfile
    orig_chat, orig_collect = dispatch._chat, dispatch.testgen.collect_spec_map
    spec = ('{"schema_version": 1, "tests": [{"criterion_id": "c1", "oracle": "raw", '
            '"raw_test": "def test_c1():\\n    assert True\\n"}]}')
    dispatch._chat = lambda *a, **k: (spec, 0)
    dispatch.testgen.collect_spec_map = lambda d, planned: planned   # no real pytest collection
    try:
        with tempfile.TemporaryDirectory() as d:
            wt = os.path.join(d, "Build-77-RUN")                     # mixed case proves slugging
            os.makedirs(wt)
            ch = {"dod": [{"id": "c1", "criterion": "x", "verify_intent": "y"}]}
            m = dispatch.designer_spec_via_ask(wt)(ch)
            assert list(m) == ["test_devloop_dod_build_77_run.py::test_c1"]
    finally:
        dispatch._chat, dispatch.testgen.collect_spec_map = orig_chat, orig_collect


def test_snapshot_and_changed_paths_ignore_junk():
    """C1: the coder-change snapshot prunes junk (venvs, caches, .git) so the lint gate never
    scans third-party files (learn-accept live catch: one coder .venv -> 852 files linted; a
    single py2-era file in any dependency would have false-blocked the pass)."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "real.py"), "w") as f:
            f.write("x = 1\n")
        before = dispatch._snapshot(d)
        assert any(k.endswith("real.py") for k in before)
        # coder "work": a venv + a cache + one genuine edit
        os.makedirs(os.path.join(d, ".venv", "lib"))
        with open(os.path.join(d, ".venv", "lib", "third_party.py"), "w") as f:
            f.write("this is not even python (\n")
        os.makedirs(os.path.join(d, "__pycache__"))
        with open(os.path.join(d, "__pycache__", "real.pyc"), "w") as f:
            f.write("x")
        with open(os.path.join(d, "real.py"), "w") as f:
            f.write("x = 2\n")
        after = dispatch._snapshot(d)
        changed = dispatch._changed_paths(before, after)
        assert [os.path.basename(p) for p in changed] == ["real.py"]   # junk never reaches lint
        assert dispatch._count_changed(before, after) == 1             # honest telemetry


def test_snapshot_junk_only_attempt_counts_as_noop():
    """C1: an attempt that only spawned a venv/caches is NO progress — files_changed must be 0
    so the loop's dispatch-error fast route fires instead of burning evidence passes."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        before = dispatch._snapshot(d)
        os.makedirs(os.path.join(d, "node_modules", "pkg"))
        with open(os.path.join(d, "node_modules", "pkg", "index.js"), "w") as f:
            f.write("x")
        os.makedirs(os.path.join(d, ".pytest_cache"))
        with open(os.path.join(d, ".pytest_cache", "CACHEDIR.TAG"), "w") as f:
            f.write("x")
        after = dispatch._snapshot(d)
        assert dispatch._count_changed(before, after) == 0
        assert dispatch._changed_paths(before, after) == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} dispatch tests passed")
