"""Self-tests for the mutation guard's registry integrity and spot-kill path."""
import os
import sys
import tempfile

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_DIR, "tests"))

import mutants  # noqa: E402


def _registry(file, old, new, desc="probe"):
    return [(file, old, new, desc)]


def test_registry_rejects_ambiguous_old_text():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "source.py"), "w") as f:
            f.write("target\ntarget\n")
        problems = mutants._check_registry(d, _registry("source.py", "target", "changed"))
    assert problems and "AMBIGUOUS" in problems[0] and "2 occurrences" in problems[0]


def test_registry_rejects_equivalent_mutant():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "source.py"), "w") as f:
            f.write("target\n")
        problems = mutants._check_registry(d, _registry("source.py", "target", "target"))
    assert problems and "EQUIVALENT" in problems[0]


def test_registry_accepts_unique_effective_mutant():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "source.py"), "w") as f:
            f.write("before target after\n")
        problems = mutants._check_registry(d, _registry("source.py", "target", "changed"))
    assert problems == []


def test_only_selects_case_insensitively_and_run_reverts_bytes():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "source.py")
        with open(path, "wb") as f:
            f.write(b"before target after\n")
        registry = [
            ("source.py", "target", "changed", "Unique Spot Probe"),
            ("source.py", "before", "earlier", "different mutant"),
        ]
        selected = mutants._select_mutants("spot PROBE", registry)
        assert selected == [registry[0]]
        assert mutants._select_mutants("TARGET", registry) == [registry[0]]
        before = open(path, "rb").read()

        def killer(root, files):
            assert open(os.path.join(root, "source.py"), "rb").read() == b"before changed after\n"
            return False

        assert mutants._run_mutants(d, selected, killer) == (1, 0, 0)
        assert open(path, "rb").read() == before


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
