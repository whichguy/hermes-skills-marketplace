"""Mutation-kill tests for state.py (atomic checkpoint + Charter validation store).

Each test closes ONE confirmed surviving mutant in the devloop state kernel: it pins the
CURRENT (correct) behavior so the documented old->new bug would make it FAIL. Companion to
test_smoke.py's state coverage — these target the fail-OPEN / fail-loud edges that the
happy-path suite never exercises (single-missing dod field, torn checkpoint, {}-as-required-
key, and the unserializable-object raise).

Run: cd ~/.hermes/skills/software-development/devloop && python3 -m pytest tests/test_state.py -q
(or: python3 tests/test_state.py for a dependency-free run)
"""
import json
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import state           # noqa: E402


def _charter(min_conf=0.9, blocking=False, assumptions=None, open_questions=None):
    """A VALID charter (validate_charter -> []); each test mutates one field locally."""
    return {
        "interpreted_intent": "x", "purpose": "y",
        "dod": [{"id": "c1", "criterion": "returns 200", "verify_intent": "status==200", "kind": "shown"}],
        "assumptions": [{"text": "a", "confidence": min_conf}] if assumptions is None else assumptions,
        "open_questions": [{"text": "q", "blocking": blocking}] if open_questions is None else open_questions,
        "happy_path": "do it", "blast_radius": {"files": ["a.py"], "order": ["a.py"]},
        "backoff_map": [{"trigger": "x", "directional_response": "y"}],
        "advisors_verdict": "ok", "ambiguity_decision": {"decision": "PROCEED", "reason": "ok"},
    }


# --- validate_charter: per-criterion checkability `or` (state.py:128) --------------
def test_charter_dod_single_missing_field_rejected():
    # `not c.get("id") or not c.get("verify_intent")` (mutant: `and`). A criterion missing
    # EITHER field is unverifiable and must be flagged. The `and` mutant only rejects when
    # BOTH are missing, so a single-missing criterion (the realistic LLM slip) slips through
    # into the loop spine and is later "satisfied" with no real check -> false-complete.
    ch = _charter(); ch["dod"] = [{"id": "c1", "criterion": "x"}]            # verify_intent MISSING
    assert any("id or verify_intent" in e for e in state.validate_charter(ch))
    ch2 = _charter(); ch2["dod"] = [{"verify_intent": "exit 0", "criterion": "x"}]  # id MISSING
    assert any("id or verify_intent" in e for e in state.validate_charter(ch2))
    # CONTROL: a fully-specified criterion must NOT raise this error (kills a constant-non-empty
    # mutant and proves the assertions above are discriminating, not always-true).
    ch3 = _charter(); ch3["dod"] = [{"id": "c1", "verify_intent": "exit 0", "criterion": "x"}]
    assert not any("id or verify_intent" in e for e in state.validate_charter(ch3))


# --- load_checkpoint: torn-write fail-safe (state.py:102) --------------------------
def test_load_checkpoint_torn_write_returns_none():
    # `except (json.JSONDecodeError, OSError):` (mutant: `except OSError:`). A torn/truncated
    # checkpoint — the exact failure atomic-write exists to survive — must resolve to None
    # ("never resume garbage"), not crash the resume. The mutant lets JSONDecodeError propagate.
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ITERATION_STATE.json")
        with open(p, "w") as f:
            f.write('{"charter": {"interpreted')        # truncated -> unparseable JSON
        assert state.load_checkpoint(d) is None
        # CONTROL: a well-formed checkpoint with a charter still loads (not a constant-None).
        state.save_checkpoint(d, state.new_run_state(_charter()))
        assert state.load_checkpoint(d) is not None


# --- validate_charter: empty-value sentinel includes {} (state.py:125) -------------
def test_charter_required_key_empty_dict_rejected():
    # `charter[k] in (None, "", [], {})` (mutant drops `{}`). An LLM emitting an empty object
    # for a required key (dod={} == zero criteria; intent={} == no intent) must be caught as
    # missing/empty. The mutant treats {} as present and slips a spine-less charter past CHARTER.
    ch = _charter(); ch["dod"] = {}                       # object instead of a list of criteria
    assert state.validate_charter(ch) != []
    ch2 = _charter(); ch2["interpreted_intent"] = {}
    assert state.validate_charter(ch2) != []
    # CONTROL: an untouched valid charter still passes clean (kills a constant-non-empty mutant).
    assert state.validate_charter(_charter()) == []


# --- _json_default: fail-loud raise on unserializable (state.py:66) ----------------
def test_json_default_raises_on_unserializable():
    # `raise TypeError(...)` for a non-to_dict object (mutant: `return None`). A silent None
    # would let json.dump persist a `null` where real state belonged -> silent checkpoint
    # corruption that load_checkpoint later mis-rehydrates. Manual raise-check keeps the file
    # runnable dependency-free (mirrors test_smoke.test_generate_tests_stub_raises_not_silent).
    with tempfile.TemporaryDirectory() as d:
        raised = False
        try:
            state.atomic_write_json(os.path.join(d, "x.json"), {"o": object()})
        except TypeError:
            raised = True
        assert raised, "atomic_write_json must raise TypeError on an unserializable object"
        # CONTROL: a serializable payload writes and round-trips (proves the write path itself
        # works, so the kill above is the raise — not an unrelated failure).
        state.atomic_write_json(os.path.join(d, "ok.json"), {"o": 123})
        with open(os.path.join(d, "ok.json")) as f:
            assert json.load(f) == {"o": 123}


# --- validate_charter: non-dict dod entry fails closed, never crashes (state.py fix) ----------
def test_charter_dod_non_dict_entries_fail_closed():
    # an LLM emitting a list-of-strings dod (`["c1","c2"]`) must yield a structured validation
    # error, NOT an AttributeError that aborts the CHARTER->PLAN gate ungracefully. Guard:
    # `if not isinstance(c, dict): errs.append(...); continue` before the .get() calls.
    ch = _charter(); ch["dod"] = ["c1", "c2"]                 # malformed: strings, not criteria dicts
    errs = state.validate_charter(ch)                         # must NOT raise
    assert any("not an object" in e for e in errs)
    # CONTROL: a valid dict criterion still validates clean (the guard didn't break the happy path).
    assert state.validate_charter(_charter()) == []


# --- read_learnings: parseable-but-non-dict lines are filtered (state.py fix) ------------------
def test_read_learnings_filters_non_dict_lines():
    # `if isinstance(obj, dict): out.append(obj)`. A stray non-object JSON line (42, "str", [1,2])
    # must be dropped, not injected into the lessons->back-off builder where entry.get(...) would
    # crash the project outer loop. The journal is normally dict-per-line; this hardens the read.
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "L.jsonl")
        with open(p, "w") as f:
            f.write('42\n"str"\n[1, 2]\n' + json.dumps({"n": 1}) + "\n")
        assert state.read_learnings(p, 20) == [{"n": 1}]      # only the dict survives
        # CONTROL: a journal of all dicts is returned intact (filter doesn't drop valid entries).
        with open(p, "w") as f:
            f.write(json.dumps({"a": 1}) + "\n" + json.dumps({"b": 2}) + "\n")
        assert state.read_learnings(p, 20) == [{"a": 1}, {"b": 2}]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
