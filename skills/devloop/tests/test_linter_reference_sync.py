"""Test that linter-reference.md coverage table stays in sync with lint.py _LANGUAGES.

Prevents the wired-but-never-functional pattern from recurring: if a linter is
listed in the doc but not wired in code (or vice versa), this test catches it.
Also verifies that all wired linters pass their available() check in this env,
so a silently-broken linter (like the ruff venv-bin bug) is caught immediately.

Run: python3 tests/test_linter_reference_sync.py
     uv run --with pytest --with pyyaml --with sqlparse --with mypy python3 -m pytest tests/test_linter_reference_sync.py -v
"""
import os
import re
import sys
import unittest

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import lint  # noqa: E402

_REF_PATH = os.path.join(_DIR, "references", "linter-reference.md")


def _parse_coverage_table(text):
    """Parse the 'Wired linters in lint.py' coverage table from linter-reference.md.

    Only parses the table under the '### Wired linters' heading, NOT the
    'future coverage' or 'environment inventory' sections.

    Returns: [([".py"], ["py-syntax", "ruff", "mypy"]), ...]
    """
    # Extract only the "Wired linters" section
    section_match = re.search(
        r"### Wired linters in.*?\n(.*?)(?=\n###|\n## |\Z)",
        text, re.DOTALL
    )
    if not section_match:
        return []
    section = section_match.group(1)

    rows = []
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        if "---" in line:  # header separator
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 2:
            continue
        ext_cell = cells[0]
        linter_cell = cells[1]
        # Extract backtick-quoted extensions like `.py`, `.yaml`, `Makefile`
        exts = re.findall(r"`([^`]+)`", ext_cell)
        if not exts:
            continue
        # Filter to only real extensions/names (skip header text)
        exts = [e for e in exts if e.startswith(".") or e[0].isupper()]
        if not exts:
            continue
        # Extract linter display names from the linter cell.
        # The reference uses display names like `py-syntax`, `ruff`, `mypy`,
        # `node --check`, `docker build --check` — matching lint.py spec["name"].
        linters = re.findall(r"`([^`]+)`", linter_cell)
        if not linters:
            continue
        rows.append((exts, linters))
    return rows


class TestLinterReferenceSync(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(_REF_PATH, "r") as f:
            cls.ref_text = f.read()
        cls.ref_rows = _parse_coverage_table(cls.ref_text)
        # Build the code-side expected sets
        cls.code_exts = set()
        cls.code_linters_by_ext = {}
        for exts, builders in lint._LANGUAGES:
            specs = [b() for b in builders]
            names = [s["name"] for s in specs]
            for ext in exts:
                cls.code_exts.add(ext)
                cls.code_linters_by_ext[ext] = names

    def test_reference_file_exists(self):
        """linter-reference.md must exist."""
        self.assertTrue(os.path.isfile(_REF_PATH),
                        f"linter-reference.md not found at {_REF_PATH}")

    def test_reference_has_coverage_table(self):
        """The reference must have a parseable coverage table with at least 10 rows."""
        self.assertGreaterEqual(len(self.ref_rows), 10,
                                f"Expected ≥10 rows in coverage table, found {len(self.ref_rows)}")

    def test_every_code_extension_is_in_reference(self):
        """Every extension in lint._LANGUAGES must appear in the reference table."""
        ref_exts = set()
        for exts, _ in self.ref_rows:
            ref_exts.update(exts)
        missing = self.code_exts - ref_exts
        self.assertFalse(missing,
                         f"Extensions in lint.py but NOT in linter-reference.md: {missing}")

    def test_every_reference_extension_is_in_code(self):
        """Every extension in the reference table must be in lint._LANGUAGES."""
        ref_exts = set()
        for exts, _ in self.ref_rows:
            ref_exts.update(exts)
        extra = ref_exts - self.code_exts
        self.assertFalse(extra,
                         f"Extensions in linter-reference.md but NOT in lint.py: {extra}")

    def test_linter_names_match_between_reference_and_code(self):
        """For each extension, the linter names in the reference must match lint._LANGUAGES."""
        ref_linters_by_ext = {}
        for exts, linters in self.ref_rows:
            for ext in exts:
                ref_linters_by_ext[ext] = linters
        mismatches = []
        for ext, code_names in sorted(self.code_linters_by_ext.items()):
            ref_names = ref_linters_by_ext.get(ext, [])
            if set(ref_names) != set(code_names):
                mismatches.append(f"  {ext}: code={code_names}, ref={ref_names}")
        self.assertFalse(mismatches,
                         f"Linter name mismatches between code and reference:\n" +
                         "\n".join(mismatches))

    def test_discover_runs_without_error(self):
        """lint.discover() must run without raising — basic health check."""
        report = lint.discover()
        self.assertIsInstance(report, list)
        self.assertGreater(len(report), 0)

    def test_discover_with_paths_only_checks_relevant(self):
        """discover(paths) should only return languages for the given file types."""
        # Create a temp .py file
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("x = 1\n")
            py_path = f.name
        try:
            report = lint.discover([py_path])
            exts_checked = set()
            for r in report:
                exts_checked.update(r["extensions"])
            # Should only check .py
            self.assertIn(".py", exts_checked)
            # Should NOT check unrelated types
            self.assertNotIn(".json", exts_checked)
            self.assertNotIn(".yaml", exts_checked)
        finally:
            os.unlink(py_path)

    def test_discover_with_unknown_file_type_flags_research(self):
        """discover(paths) with an unknown file type should flag it with research=True."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".xyz", mode="w", delete=False) as f:
            f.write("test\n")
            xyz_path = f.name
        try:
            report = lint.discover([xyz_path])
            research_rows = [r for r in report if r.get("research") is True]
            self.assertTrue(research_rows,
                            "Expected a research=True row for unknown .xyz file type")
        finally:
            os.unlink(xyz_path)

    def test_py_linters_available_in_env(self):
        """The Python linters (py-syntax, ruff, mypy) should all be available in this env.

        This catches the wired-but-never-functional pattern: if ruff is wired but
        not discoverable (the venv-bin bug), this test fails.
        """
        for exts, builders in lint._LANGUAGES:
            if ".py" not in exts:
                continue
            for build in builders:
                spec = build()
                self.assertTrue(spec["available"](),
                                f"Python linter '{spec['name']}' is wired but NOT available. "
                                f"This is the wired-but-never-functional pattern — check _resolve_exe().")

    def test_lint_paths_flags_unknown_file_type_as_research(self):
        """lint_paths on an unknown file type should record research=True in the result."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".xyz", mode="w", delete=False) as f:
            f.write("test\n")
            xyz_path = f.name
        try:
            ok, results = lint.lint_paths([xyz_path])
            skipped = [r for r in results if r.get("skipped")]
            self.assertTrue(skipped, "Expected a skipped result for .xyz file")
            self.assertTrue(skipped[0].get("research") is True,
                            "Expected research=True flag for unknown file type")
        finally:
            os.unlink(xyz_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)