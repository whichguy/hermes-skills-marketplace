"""render.py — render a STRUCTURED test spec into ONE canonical pytest file.

The designer returns a JSON spec (per criterion: module/call + cases of expected/raises/approx, or an
oracle:"raw" escape-hatch test) instead of writing free-form pytest. We render exactly one function
per criterion, named test_<criterion_id>, into canonical_file(run_name) — so node ids are known BY CONSTRUCTION
(coverage is DERIVED, never parsed) and there is exactly one test style (ending the free-form
matching brittleness).

Fail-closed by SKIPPING: any entry that fails validation is dropped (never rendered), so its
criterion gets no node -> coverage fails closed downstream. The renderer can NEVER fabricate
coverage: testgen.collect_spec_map intersects this manifest with a REAL `pytest --collect-only`.
Every literal is rendered via repr() (a safe Python literal, no code injection); module / call /
mock target / exception are regex/allowlist constrained so no arbitrary expression reaches the file.
"""
from __future__ import annotations

import ast
import os
import re

CANONICAL_FILE = "test_devloop_dod.py"     # namespaced -> won't clobber a target repo's own test_*.py
_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def canonical_file(run_name=None):
    """Per-run oracle filename: test_devloop_dod_<slug>.py. Distinct runs get distinct files so
    (a) re-runs on the same repo ACCUMULATE DoD protection instead of overwriting the prior
    run's oracle, and (b) concurrent runs never collide on this file at merge (test-file
    conflicts are code-guarded to never reach the LLM resolver — a shared name would send every
    second concurrent run to branch-for-review). Slug is sanitize-not-trust: lowercased,
    non-[a-z0-9_] collapsed, capped — it lands in a filesystem path and pytest node ids.
    No/empty run_name -> the bare CANONICAL_FILE (fixtures, greenfield tests)."""
    slug = _SLUG_RE.sub("_", str(run_name or "").lower()).strip("_")[:40]
    return f"test_devloop_dod_{slug}.py" if slug else CANONICAL_FILE
_IDENT = re.compile(r"^[A-Za-z_]\w*$")
_DOTTED = re.compile(r"^[A-Za-z_][\w.]*$")
_ALLOWED_EXC = frozenset({
    "Exception", "BaseException", "ValueError", "TypeError", "KeyError", "IndexError",
    "AttributeError", "RuntimeError", "ZeroDivisionError", "AssertionError", "NotImplementedError",
    "StopIteration", "OverflowError", "ArithmeticError", "LookupError", "FileNotFoundError",
    "OSError", "IOError", "NameError", "ImportError", "RecursionError", "TimeoutError",
})


import datetime as _dt


def _lit(v):
    """Render a JSON scalar/list/dict as a safe Python literal.

    Special-cases datetime/date/time/timedelta so the designer can use real
    temporal objects instead of string literals (which judges reject because
    '2026-07-06T12:00:00' != datetime(2026,7,6,12,0)).
    """
    if isinstance(v, _dt.datetime):
        parts = [v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond]
        # Trim trailing zeros for readability (but keep at least Y,M,D,H,M)
        while len(parts) > 6 and parts[-1] == 0:
            parts.pop()
        if len(parts) > 6 and parts[-1] == 0:
            parts.pop()  # microseconds
        if len(parts) > 5 and parts[-1] == 0:
            parts.pop()  # seconds
        return f"datetime({', '.join(str(p) for p in parts)})"
    if isinstance(v, _dt.date):
        return f"date({v.year}, {v.month}, {v.day})"
    if isinstance(v, _dt.time):
        parts = [v.hour, v.minute, v.second, v.microsecond]
        while len(parts) > 2 and parts[-1] == 0:
            parts.pop()
        return f"time({', '.join(str(p) for p in parts)})"
    if isinstance(v, _dt.timedelta):
        kw = []
        if v.days: kw.append(f"days={v.days}")
        if v.seconds: kw.append(f"seconds={v.seconds}")
        if v.microseconds: kw.append(f"microseconds={v.microseconds}")
        return f"timedelta({', '.join(kw)})" if kw else "timedelta(0)"
    # Recursively render lists and tuples so datetime elements inside them
    # also get the special-case treatment (otherwise repr(tuple) calls
    # repr(datetime) → 'datetime.datetime(...)' instead of 'datetime(...)')
    if isinstance(v, list):
        return "[" + ", ".join(_lit(x) for x in v) + "]"
    if isinstance(v, tuple):
        return "(" + ", ".join(_lit(x) for x in v) + ("," if len(v) == 1 else "") + ")"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_lit(k)}: {_lit(val)}" for k, val in v.items()) + "}"
    return repr(v)   # json scalars -> a safe Python literal


def _indent(lines, n=1):
    pad = "    " * n
    return [pad + ln for ln in lines]


def _render_case(call, case):
    """One case -> source lines (relative indent), or None if malformed (-> skip the whole entry)."""
    if not isinstance(case, dict):
        return None
    args, kwargs = case.get("args", []), case.get("kwargs", {})
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        return None
    if not all(isinstance(k, str) and _IDENT.match(k) for k in kwargs):
        return None
    has_expected, has_raises = "expected" in case, "raises" in case
    if has_expected == has_raises:        # exactly one of expected / raises
        return None
    callargs = ", ".join([_lit(a) for a in args] + [f"{k}={_lit(v)}" for k, v in kwargs.items()])
    if has_raises:
        exc = case["raises"]
        if exc not in _ALLOWED_EXC:
            return None
        return [f"with pytest.raises({exc}):", f"    {call}({callargs})"]
    rhs = _lit(case["expected"])
    if case.get("approx"):
        return [f"assert {call}({callargs}) == pytest.approx({rhs})"]
    return [f"assert {call}({callargs}) == {rhs}"]


def _mock_with(m, idx=0):
    """A mock entry -> (with_line, post_lines) or None if malformed.

    Returns a tuple: the `with mock.patch(...):` line and any post-call assertion
    lines (e.g. assert_called_with). The caller indents post_lines into the body
    after the case assertions.
    """
    if not isinstance(m, dict):
        return None
    target = m.get("target")
    if not isinstance(target, str) or not _DOTTED.match(target):
        return None
    as_name = f"_m{idx}"
    parts = [f"mock.patch({_lit(target)}"]
    if "return_value" in m:
        parts.append(f", return_value={_lit(m['return_value'])}")
    if "side_effect" in m:
        if m["side_effect"] not in _ALLOWED_EXC:
            return None
        parts.append(f", side_effect={m['side_effect']}")
    parts.append(f") as {as_name}")
    with_line = "with " + "".join(parts) + ":"
    post = []
    # assert_called_once: verify the mock was called exactly once
    if m.get("assert_called_once"):
        post.append(f"{as_name}.assert_called_once()")
    # assert_call_arg: inspect a specific positional/keyword arg of the call
    aca = m.get("assert_call_arg")
    if isinstance(aca, list) and len(aca) == 3:
        pos, key, expected = aca
        if isinstance(pos, int) and pos >= 0:
            key_repr = _lit(key) if isinstance(key, str) else str(key)
            post.append(f"assert {as_name}.call_args[{pos}][{key_repr}] == {_lit(expected)}")
    # assert_called_with: verify exact call arguments
    acw = m.get("assert_called_with")
    if isinstance(acw, list) and len(acw) == 2:
        a_args, a_kwargs = acw
        if isinstance(a_args, list) and isinstance(a_kwargs, dict):
            cargs = ", ".join([_lit(a) for a in a_args]
                              + [f"{k}={_lit(v)}" for k, v in a_kwargs.items()])
            post.append(f"{as_name}.assert_called_with({cargs})")
    return (with_line, post)


def _valid_raw(raw, fn):
    """An oracle:'raw' test must parse AND be exactly one top-level function literally named fn
    (so the node id is predictable) with no top-level class — else no credited node (fail-closed)."""
    if not isinstance(raw, str):
        return False
    try:
        tree = ast.parse(raw)
    except SyntaxError:
        return False
    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    return len(funcs) == 1 and funcs[0].name == fn and not classes


def _render_entry(t):
    """One spec entry -> (node_id, criterion_id, source) or None (skip -> fail-closed)."""
    cid = t.get("criterion_id")
    if not isinstance(cid, str) or not _IDENT.match(cid):
        return None
    fn = f"test_{cid}"

    if t.get("oracle") == "raw":
        raw = t.get("raw_test")
        if not _valid_raw(raw, fn):
            return None
        return fn, cid, raw if raw.endswith("\n") else raw + "\n"

    module, call = t.get("module"), t.get("call")
    if not (isinstance(module, str) and _DOTTED.match(module)
            and isinstance(call, str) and _IDENT.match(call)):
        return None
    cases = t.get("cases")
    if not isinstance(cases, list) or not cases:
        return None
    body = []
    for case in cases:
        lines = _render_case(call, case)
        if lines is None:
            return None
        body += lines
    for i, m_entry in enumerate(reversed(t.get("mocks") or [])):     # wrap body innermost-out
        result = _mock_with(m_entry, idx=i)
        if result is None:
            return None
        withline, post = result
        body = [withline] + _indent(body, 1) + _indent(post, 1)
    src = [f"# dod:{cid}", f"def {fn}():", f"    from {module} import {call}"] + _indent(body, 1)
    return fn, cid, "\n".join(src) + "\n"


def render_spec(spec, target_dir, run_name=None):
    """Render `spec` into target_dir/canonical_file(run_name); return the PLANNED
    {node_id: criterion_id} for entries actually rendered. Fail-closed: a non-dict /
    wrong-version / empty spec renders nothing (-> empty manifest -> coverage fails ->
    HUMAN_REVIEW, exactly like an empty collect_test_map)."""
    if not isinstance(spec, dict) or spec.get("schema_version") != 1:
        return {}
    tests = spec.get("tests")
    if not isinstance(tests, list):
        return {}
    fname = canonical_file(run_name)
    rendered, manifest, seen = [], {}, set()
    for t in tests:
        if not isinstance(t, dict):
            continue
        out = _render_entry(t)
        if out is None:
            continue
        fn, cid, source = out
        if cid in seen:        # duplicate criterion would overwrite the function -> keep the first
            continue
        seen.add(cid)
        rendered.append(source)
        manifest[f"{fname}::{fn}"] = cid
    if not manifest:
        return {}
    body = "\n\n".join(rendered)
    # Import only what the rendered bodies reference — an unused import fails strict-lint
    # (ruff F401) target repos, and this file ships INTO the target on merge.
    header = ""
    if "pytest." in body:
        header = "import pytest\n"
    if "mock." in body:
        header += "from unittest import mock\n"
    if "datetime(" in body or "date(" in body or "time(" in body or "timedelta(" in body:
        header += "from datetime import datetime, date, time, timedelta\n"
    os.makedirs(target_dir, exist_ok=True)
    with open(os.path.join(target_dir, fname), "w", encoding="utf-8") as f:
        f.write((header + "\n\n" if header else "") + body)
    return manifest
