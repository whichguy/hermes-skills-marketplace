"""Mutation-killing tests for dod_oracle.py (the DoD-as-test-oracle trust kernel).

Each test closes a confirmed coverage gap (a surviving mutant) that the existing
test_smoke.py suite does NOT catch. Every assertion pins CURRENT (correct) behavior so
the hypothetical mutant (old->new) would make it FAIL. Deterministic, no LLM: judges are
plain in-process lambdas (exactly as the smoke suite injects them).

Run: cd ~/.hermes/skills/software-development/devloop && python3 -m pytest tests/test_dod_oracle.py -q
(or: python3 tests/test_dod_oracle.py for a dependency-free run)
"""
import os
import sys

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import dod_oracle      # noqa: E402


# --- judge_assertions: one verdict per criterion, test_ids COMBINED ----------------
def test_judge_assertions_groups_multiple_tests_per_criterion():
    # A good designer splits one criterion across several focused tests. The `if cid not in
    # by_crit` guard de-dups so the criterion yields ONE verdict over the whole set. Mutant
    # `if True` re-inits the bucket each row -> verdicts fragment/duplicate, test_ids truncate.
    tests = [{"test_id": "t1", "criterion_id": "c1"},
             {"test_id": "t2", "criterion_id": "c1"}]
    by_id = {"c1": {"id": "c1", "verify_intent": "x"}}
    out = dod_oracle.judge_assertions(tests, by_id, lambda c, t: True, lambda c, t: True)
    assert len(out) == 1                          # one criterion -> one verdict
    assert out[0]["criterion_id"] == "c1"
    assert out[0]["test_ids"] == ["t1", "t2"]     # both tests grouped, in order


# --- judge_assertions: encodes = a AND b (2-model agreement) ----------------------
def test_judge_assertions_reject_by_a_accept_by_b_not_trusted():
    # The (a=False, b=True) ordering the suite never exercises. `encodes = a and b` means
    # EITHER judge's veto blocks trust; mutant `encodes = b` silently drops judge_a's veto.
    out = dod_oracle.judge_assertions(
        [{"test_id": "t1", "criterion_id": "c1"}],
        {"c1": {"id": "c1", "verify_intent": "x"}},
        lambda c, t: False,        # judge_a REJECTS
        lambda c, t: True)         # judge_b accepts
    assert out[0]["encodes"] is False     # one veto -> not trusted (mutant would say True)
    assert out[0]["escalate"] is True     # judges disagree -> escalate
    # CONTROL: unanimous accept is the trusted case, so this is no constant-False return.
    ok = dod_oracle.judge_assertions(
        [{"test_id": "t1", "criterion_id": "c1"}],
        {"c1": {"id": "c1", "verify_intent": "x"}},
        lambda c, t: True, lambda c, t: True)
    assert ok[0]["encodes"] is True and ok[0]["escalate"] is False


# --- judge_assertions: judges receive the FULL test set, not a truncated one -------
def test_judge_assertions_passes_full_test_set_to_judges():
    # Both judges must SEE all of a criterion's tests together (so a compound criterion's
    # missing sub-test is caught). Mutant truncates judge_a's arg to by_crit[cid][:1] ->
    # judge_a sees 1 test, returns False, encodes = False and True = False.
    tests = [{"test_id": "t1", "criterion_id": "c1"},
             {"test_id": "t2", "criterion_id": "c1"}]
    by_id = {"c1": {"id": "c1", "verify_intent": "x"}}
    saw_both = lambda crit, test_ids: len(test_ids) == 2   # only True if it got the full set
    out = dod_oracle.judge_assertions(tests, by_id, saw_both, saw_both)
    assert out[0]["encodes"] is True      # both judges saw both tests -> trusted
    assert out[0]["escalate"] is False    # CONTROL: agreement, not a fragmented disagreement


# --- check_structural_coverage: `if c.get("id")` skips id-less criteria gracefully -
def test_structural_coverage_skips_idless_criterion_without_crashing():
    # An id-less/empty-id criterion must be skipped, not indexed. Mutant `if True` evaluates
    # c["id"] on the id-less dict -> KeyError (test errors -> mutant killed).
    ok, uncovered = dod_oracle.check_structural_coverage(
        [{"id": "c1"}, {"verify_intent": "no-id"}], {"t1": "c1"})
    assert ok is True            # only the id'd criterion is required, and it is covered
    assert uncovered == []
    # CONTROL: a genuinely-uncovered id'd criterion still fails closed (not a constant-True).
    ok2, unc2 = dod_oracle.check_structural_coverage(
        [{"id": "c1"}, {"id": "c2"}], {"t1": "c1"})
    assert ok2 is False and unc2 == ["c2"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
