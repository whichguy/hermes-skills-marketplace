"""testgen.py — intersect the renderer's PLANNED test map with REAL collected pytest nodes.

The legitimacy guard for the v1 oracle: a criterion is "covered" ONLY if its rendered canonical
test actually pytest-COLLECTS — never the model's self-report (collect_spec_map). A planned-but-
uncollectable test is dropped, coverage fails closed, and run_v1 routes to HUMAN_REVIEW.
(The legacy free-form annotation parser — `# dod:<id>` comments/docstrings over designer-written
files — was DELETED 2026-07-01: zero passing-spike evidence and five parser accommodations; the
structured designer + render.py make node ids known BY CONSTRUCTION.)

Note: rendered tests import the implementation INSIDE the test function (not at module level),
so they are collectable BEFORE the implementation exists.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys

_TESTFN = (ast.FunctionDef, ast.AsyncFunctionDef)


def pytest_available():
    """True iff `sys.executable -m pytest` works — devloop's runtime MUST have pytest (the model
    writes pytest tests and the loop runs them). See SETUP.md."""
    try:
        return subprocess.run([sys.executable, "-m", "pytest", "--version"],
                              capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


_PYTEST_MISSING = ("pytest is unavailable to the devloop runtime (sys.executable -m pytest failed), "
                   "but tests exist — cannot verify coverage. Install pytest in the runtime "
                   "(e.g. `uv run --with pytest ...`). See SETUP.md.")


def _collected_node_ids(target_dir, timeout=120):
    """The set of REAL pytest node ids in target_dir (the legitimacy ground truth)."""
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "."],
                           capture_output=True, text=True, cwd=target_dir, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {line.strip().split(" ")[0] for line in r.stdout.splitlines() if "::" in line.strip()}


def _covered(nid, collected):
    """A node `f` is covered if it collects exactly OR as parametrized instances `f[..]`
    (running `pytest f` bare still executes every @pytest.mark.parametrize case)."""
    return nid in collected or any(c.startswith(nid + "[") for c in collected)


def collect_spec_map(target_dir, planned, timeout=120):
    """Intersect the renderer's PLANNED {node_id: criterion_id} (render.render_spec) with REAL
    pytest collection — so a planned test that does not actually collect is DROPPED (fail-closed;
    the renderer can never fabricate coverage).
    Raises if planned tests exist but pytest is unavailable."""
    if not planned:
        return {}
    if not pytest_available():
        raise RuntimeError(_PYTEST_MISSING)
    collected = _collected_node_ids(target_dir, timeout)
    return {nid: cid for nid, cid in planned.items() if _covered(nid, collected)}


def node_source(target_dir, node_id):
    """Return the source of the test named by node_id (<relpath>::<qualname>, where qualname may be
    a Class::method path), or '' — so the assertion judge sees what was ACTUALLY written, not a
    model's paraphrase. Walks the exact class/func path so same-named methods in different classes
    don't collide."""
    if "::" not in node_id:
        return ""
    parts = node_id.split("::")
    rel, path = parts[0], parts[1:]
    try:
        src = open(os.path.join(target_dir, rel)).read()
        node = ast.parse(src)
    except (OSError, SyntaxError):
        return ""
    for name in path:                      # descend Class::...::func exactly
        nxt = next((c for c in ast.iter_child_nodes(node)
                    if isinstance(c, (*_TESTFN, ast.ClassDef)) and c.name == name), None)
        if nxt is None:
            return ""
        node = nxt
    if not isinstance(node, _TESTFN):
        return ""
    lines = src.splitlines()
    start = node.lineno
    if node.decorator_list:                # include @pytest.mark.parametrize so the judge sees cases
        start = min(start, min(d.lineno for d in node.decorator_list))
    return "\n".join(lines[start - 1:getattr(node, "end_lineno", node.lineno)])


def invert(node_to_criterion):
    """{criterion_id: [node_id, ...]} — for per-criterion verify commands."""
    inv = {}
    for nid, cid in node_to_criterion.items():
        inv.setdefault(cid, []).append(nid)
    return inv


def verify_cmd_for(criterion_to_nodes):
    """Return a verify_cmd_for(criterion) that runs JUST that criterion's pytest node(s). A
    criterion with no node returns a command that FAILS (fail-closed — never silently green)."""
    def f(cid):
        nodes = criterion_to_nodes.get(cid, [])
        if not nodes:
            return [sys.executable, "-c", "import sys; sys.exit(1)"]
        return [sys.executable, "-m", "pytest", "-q", *nodes]
    return f
