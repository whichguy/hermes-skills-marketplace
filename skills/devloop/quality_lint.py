"""quality_lint.py — fast pre-judge semantic quality gate on rendered oracle files.

Runs BEFORE the assertion judges. Pattern-matches known-rejected test shapes and returns
specific feedback so the redesigner can fix the test, not burn a ~6-minute judge round-trip.
Fail-open on parse errors — unknown shapes are allowed through to the judges.
"""
from __future__ import annotations

import ast
import os
from typing import Sequence


class _Finding:
    def __init__(self, path: str, line: int | None, category: str, message: str):
        self.path = path
        self.line = line
        self.category = category
        self.message = message

    def as_dict(self) -> dict:
        return {"path": self.path, "line": self.line, "category": self.category, "message": self.message}


def _source_files(cwd: str) -> list[str]:
    """All rendered oracle files under cwd."""
    out = []
    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in {".git", ".venv", "__pycache__", ".pytest_cache", ".devloop"}]
        for f in files:
            if f.startswith("test_devloop_dod") and f.endswith(".py"):
                out.append(os.path.join(root, f))
    return sorted(out)


def _is_top_level_patch_call(node: ast.AST) -> bool:
    """mock.patch(...) as a context manager (module/test level, not inside a helper)."""
    if isinstance(node, ast.With):
        for item in node.items:
            call = item.context_expr
            if isinstance(call, ast.Call):
                func = call.func
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "mock" and func.attr == "patch":
                    return True
                if isinstance(func, ast.Name) and func.id == "patch":
                    return True
    return False


def _is_string_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(getattr(node, "value", None), str)


def _looks_like_datetime_literal(s: str) -> bool:
    t = s.strip()
    return t.startswith("datetime(") or t.startswith("date(") or t.startswith("time(") or t.startswith("timedelta(")


def _extract_mock_name_from_in_check(node: ast.AST) -> str | None:
    """If `m.call_args[0][0] in '...'` or similar, return the mock name `m`."""
    cur = node
    while isinstance(cur, ast.Subscript):
        cur = cur.value
    if isinstance(cur, ast.Attribute) and isinstance(cur.value, ast.Name):
        return cur.value.id
    return None


def _collect_findings(path: str, src: str) -> list[_Finding]:
    findings: list[_Finding] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return findings  # fail-open: syntax errors are caught elsewhere

    lines = src.splitlines()

    # 1) mock.patch at test/module level (not dependency injection)
    for node in ast.walk(tree):
        if _is_top_level_patch_call(node):
            findings.append(_Finding(
                path, getattr(node, "lineno", None), "module_level_patch",
                "mock.patch() at test/module level cannot verify what was passed to the dependency. "
                "Use dependency injection: pass the mock/callable as a parameter to the function under test. "
                "Use the raw escape hatch for this criterion."
            ))

    # 2) Mock(return_value=...) without call_args inspection
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            func = value.func
            is_mock_ctor = (
                (isinstance(func, ast.Name) and func.id == "Mock") or
                (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "mock" and func.attr in ("Mock", "MagicMock"))
            )
            if not is_mock_ctor:
                continue
            mock_name = target.id
            used = any(
                isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == mock_name and n.attr in ("call_args", "assert_called", "assert_called_once", "assert_called_with", "assert_any_call")
                for n in ast.walk(tree)
            )
            if not used:
                findings.append(_Finding(
                    path, getattr(node, "lineno", None), "mock_without_call_inspection",
                    f"{mock_name} is created with Mock(return_value=...) but never inspected via .call_args / assert_called*. "
                    f"The test does not verify the function CALLED the dependency. "
                    f"Inspect {mock_name}.call_args[0][0] or use assert_called_with(). Use the raw escape hatch."
                ))

    # 3) assert X == 'datetime(...)' string literal
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        test = node.test
        if not isinstance(test, ast.Compare):
            continue
        for comparator in test.comparators:
            if _is_string_literal(comparator) and _looks_like_datetime_literal(getattr(comparator, "value", "")):
                findings.append(_Finding(
                    path, getattr(node, "lineno", None), "datetime_string_literal",
                    "Asserting against a string literal like 'datetime(...)' instead of a real datetime object. "
                    "Use `from datetime import datetime` and assert `result == datetime(2026, 7, 6, ...)`."
                ))

    # 4) defensively scan raw text for stringified datetime comparisons, but only on lines
    #    the AST walker did not already flag.
    ast_lines = {f.line for f in findings if f.category == "datetime_string_literal" and f.line is not None}
    for i, line in enumerate(lines, 1):
        if i in ast_lines:
            continue
        stripped = line.strip()
        if "assert " in stripped and ("== 'datetime" in stripped or '== "datetime' in stripped):
            findings.append(_Finding(
                path, i, "datetime_string_literal",
                "Possible string-literal datetime assertion. Use a real datetime object."
            ))

    # 5) Mocked command runner / executor with only weak 'in' substring assertions
    # Detect tests that mock a runner/executor and assert 'foo' in cmd_str — they pass even
    # when the command format is completely wrong (e.g. gws 'events create' vs '+insert').
    # Fail-closed: flag only when the mocked command string is checked with 'in' but never
    # split, indexed, or compared to an expected full command/args.
    weak_mock_assertions: list[tuple[str, ast.Assert]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        test = node.test
        if isinstance(test, ast.Compare) and any(isinstance(op, ast.In) for op in test.ops):
            inspected = _extract_mock_name_from_in_check(test.left) or _extract_mock_name_from_in_check(test.comparators[0])
            if inspected:
                weak_mock_assertions.append((inspected, node))

    for mock_name, assert_node in weak_mock_assertions:
        # Look for ANY structured command check involving this mock OUTSIDE the weak 'in' assertion.
        has_structured_check = False
        for node in ast.walk(tree):
            if node is assert_node or not isinstance(node, (ast.Assert, ast.Assign)):
                continue
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if mock_name not in names:
                continue
            # Structured command checks: split, indexing, exact equality, .startswith, .endswith
            if any(isinstance(n, ast.Attribute) and n.attr in ("split", "startswith", "endswith") for n in ast.walk(node)):
                has_structured_check = True
                break
            if any(isinstance(n, ast.Subscript) for n in ast.walk(node)):
                has_structured_check = True
                break
            if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare):
                if any(isinstance(op, (ast.Eq, ast.Is)) for op in node.test.ops):
                    has_structured_check = True
                    break
        if not has_structured_check:
            findings.append(_Finding(
                path, getattr(assert_node, "lineno", None), "weak_substring_command_assertion",
                f"{mock_name} is mocked and its command string is only checked with 'in' assertions. "
                "This passes even if the command format is wrong (e.g. 'events create' vs '+insert'). "
                "Use the raw escape hatch: run the real binary via subprocess or inspect "
                "mock_name.call_args[0][0].split() and assert exact arguments."
            ))

    return findings


def lint_rendered_tests(cwd: str) -> tuple[bool, list[dict]]:
    """Return (ok, findings_as_dicts). ok=True means no rejected patterns detected."""
    all_findings: list[_Finding] = []
    for path in _source_files(cwd):
        try:
            src = open(path, encoding="utf-8").read()
        except OSError:
            continue
        all_findings.extend(_collect_findings(path, src))
    return (not all_findings, [f.as_dict() for f in all_findings])


def feedback_for_redesigner(findings: Sequence[dict]) -> str:
    """Compact feedback string to append to the redesigner prompt."""
    if not findings:
        return ""
    lines = ["PRE-JUDGE QUALITY GATE rejected the rendered tests for these reasons:"]
    for f in findings:
        loc = f":{f['line']}" if f.get("line") else ""
        lines.append(f"- {f['category']} at {f['path']}{loc}: {f['message']}")
    lines.append("Fix the tests to avoid these patterns, THEN request judge review.")
    return "\n".join(lines)
