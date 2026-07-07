#!/usr/bin/env python3
"""
Tests for dispatch_advisors.py — covers crash-class bugs, edge cases, and
all advisor review findings (Kimi + DeepSeek, 2026-07-05).

Run: python3 tests/test_dispatch_advisors.py
Or:  python3 -m pytest tests/test_dispatch_advisors.py -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock  # noqa: F401 — used by future mock-based tests

# Add scripts dir to path
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS_DIR)

from dispatch_advisors import (
    AdvisorDispatch,
    parse_seats,
    DEFAULT_SEATS,
    DEFAULT_SYNTHESIS_MODEL,
    ASK_SCRIPTS_DIR,
    PROMPT_MODEL,
)


class TestParseSeats(unittest.TestCase):
    """parse_seats model/role disambiguation."""

    def test_none_returns_defaults(self):
        seats = parse_seats(None)
        self.assertEqual(seats, list(DEFAULT_SEATS))

    def test_empty_string_returns_defaults(self):
        seats = parse_seats("")
        self.assertEqual(seats, list(DEFAULT_SEATS))

    def test_bare_model(self):
        seats = parse_seats("deepseek-v4-pro:cloud")
        self.assertEqual(seats, [("deepseek-v4-pro:cloud", "deepseek-v4-pro:cloud")])

    def test_multiple_bare_models(self):
        seats = parse_seats("deepseek-v4-pro:cloud,kimi-k2.7-code:cloud")
        self.assertEqual(len(seats), 2)
        self.assertEqual(seats[0][0], "deepseek-v4-pro:cloud")
        self.assertEqual(seats[1][0], "kimi-k2.7-code:cloud")

    def test_pipe_syntax_explicit_role(self):
        seats = parse_seats("deepseek-v4-pro:cloud|Reasoner,kimi-k2.7-code:cloud|Coder")
        self.assertEqual(seats[0], ("deepseek-v4-pro:cloud", "Reasoner"))
        self.assertEqual(seats[1], ("kimi-k2.7-code:cloud", "Coder"))

    def test_pipe_syntax_local_model(self):
        """Local model tags with non-standard suffixes need pipe syntax."""
        seats = parse_seats("qwen3.6:35b-a3b|Local Lens")
        self.assertEqual(seats[0], ("qwen3.6:35b-a3b", "Local Lens"))

    def test_colon_in_model_name_preserved(self):
        """Colons are NOT used for role parsing — entire string is model."""
        seats = parse_seats("qwen3-coder-next:q4_K_M")
        self.assertEqual(seats[0], ("qwen3-coder-next:q4_K_M", "qwen3-coder-next:q4_K_M"))

    def test_pipe_with_spaces_stripped(self):
        seats = parse_seats("deepseek-v4-pro:cloud | Reasoner")
        self.assertEqual(seats[0], ("deepseek-v4-pro:cloud", "Reasoner"))

    def test_empty_segments_skipped(self):
        seats = parse_seats("deepseek-v4-pro:cloud,,kimi-k2.7-code:cloud")
        self.assertEqual(len(seats), 2)

    def test_whitespace_only_returns_defaults(self):
        """Bug 3 fix: whitespace-only input should return defaults, not empty list."""
        seats = parse_seats("  ,  ")
        self.assertEqual(len(seats), len(DEFAULT_SEATS))

    def test_no_colon_no_pipe(self):
        seats = parse_seats("ollama-model")
        self.assertEqual(seats, [("ollama-model", "ollama-model")])


class TestAdvisorDispatchInit(unittest.TestCase):
    """__init__ behavior — absolute paths, auto-subdir."""

    def test_outdir_resolved_to_absolute(self):
        ad = AdvisorDispatch(outdir="relative/path", auto_subdir=False)
        self.assertTrue(os.path.isabs(ad.outdir))

    def test_auto_subdir_creates_unique_dir(self):
        ad1 = AdvisorDispatch(outdir="/tmp/test-advisors-init", auto_subdir=True)
        ad2 = AdvisorDispatch(outdir="/tmp/test-advisors-init", auto_subdir=True)
        self.assertNotEqual(ad1.outdir, ad2.outdir)
        self.assertTrue(os.path.exists(ad1.outdir))
        self.assertTrue(os.path.exists(ad2.outdir))

    def test_no_auto_subdir_uses_outdir_directly(self):
        ad = AdvisorDispatch(outdir="/tmp/test-advisors-nosub", auto_subdir=False)
        self.assertEqual(ad.outdir, "/tmp/test-advisors-nosub")

    def test_outdir_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            outdir = os.path.join(tmp, "nested", "dir")
            ad = AdvisorDispatch(outdir=outdir, auto_subdir=False)
            self.assertTrue(os.path.exists(ad.outdir))


class TestPrepareBrief(unittest.TestCase):
    """prepare_brief — brief assembly and file writing."""

    def setUp(self):
        self.ad = AdvisorDispatch(outdir="/tmp/test-advisors-brief", auto_subdir=False)

    def test_inline_context_only(self):
        path = self.ad.prepare_brief(question="Q1", context="Inline context")
        self.assertTrue(os.path.exists(path))
        content = open(path).read()
        self.assertIn("Q1", content)
        self.assertIn("Inline context", content)

    def test_context_file_only(self):
        ctx_path = os.path.join(self.ad.outdir, "ctx.md")
        with open(ctx_path, "w") as f:
            f.write("File context data")
        path = self.ad.prepare_brief(question="Q2", context_file=ctx_path)
        content = open(path).read()
        self.assertIn("Q2", content)
        self.assertIn("File context data", content)

    def test_both_context_and_context_file(self):
        """Bug A fix: both are included, not either/or."""
        ctx_path = os.path.join(self.ad.outdir, "ctx.md")
        with open(ctx_path, "w") as f:
            f.write("File context")
        path = self.ad.prepare_brief(
            question="Q3", context="Inline context", context_file=ctx_path
        )
        content = open(path).read()
        self.assertIn("File context", content)
        self.assertIn("Inline context", content)

    def test_extra_context_files(self):
        extra = os.path.join(self.ad.outdir, "extra.md")
        with open(extra, "w") as f:
            f.write("Extra data")
        path = self.ad.prepare_brief(question="Q4", extra_context_files=[extra])
        content = open(path).read()
        self.assertIn("Extra data", content)

    def test_missing_context_file_warns(self):
        """Missing context_file should warn, not crash."""
        path = self.ad.prepare_brief(
            question="Q5", context_file="/nonexistent/file.md"
        )
        self.assertTrue(os.path.exists(path))
        content = open(path).read()
        self.assertIn("Q5", content)

    def test_missing_extra_context_file_warns(self):
        path = self.ad.prepare_brief(
            question="Q6", extra_context_files=["/nonexistent/extra.md"]
        )
        self.assertTrue(os.path.exists(path))

    def test_verify_preamble_added(self):
        path = self.ad.prepare_brief(question="Q7", context="C", verify_preamble=True)
        content = open(path).read()
        self.assertIn("verify each claim", content)

    def test_no_verify_preamble_by_default(self):
        path = self.ad.prepare_brief(question="Q8", context="C")
        content = open(path).read()
        self.assertNotIn("verify each claim", content)


class TestDispatchValidation(unittest.TestCase):
    """dispatch() input validation — errors before subprocess calls."""

    def test_dispatch_without_brief_raises(self):
        ad = AdvisorDispatch(outdir="/tmp/test-advisors-dispatch", auto_subdir=False)
        with self.assertRaises(ValueError):
            ad.dispatch()

    def test_dispatch_with_missing_brief_raises(self):
        ad = AdvisorDispatch(outdir="/tmp/test-advisors-dispatch2", auto_subdir=False)
        ad.brief_path = "/tmp/nonexistent/brief.md"
        with self.assertRaises(FileNotFoundError):
            ad.dispatch()

    def test_invalid_seat_tuple_raises(self):
        ad = AdvisorDispatch(outdir="/tmp/test-advisors-dispatch3", auto_subdir=False)
        ad.prepare_brief(question="Q", context="C")
        with self.assertRaises(ValueError):
            ad.dispatch(seats=[("model", "role", "extra")])

    def test_invalid_seat_type_raises(self):
        ad = AdvisorDispatch(outdir="/tmp/test-advisors-dispatch4", auto_subdir=False)
        ad.prepare_brief(question="Q", context="C")
        with self.assertRaises(ValueError):
            ad.dispatch(seats=[123])

    def test_empty_seats_raises(self):
        """Empty seats list should raise ValueError, not crash ThreadPoolExecutor."""
        ad = AdvisorDispatch(outdir="/tmp/test-advisors-dispatch5", auto_subdir=False)
        ad.prepare_brief(question="Q", context="C")
        with self.assertRaises(ValueError, msg="No seats to dispatch"):
            ad.dispatch(seats=[])


class TestSynthesizeValidation(unittest.TestCase):
    """synthesize() input validation."""

    def test_synthesize_without_dispatch_raises(self):
        ad = AdvisorDispatch(outdir="/tmp/test-advisors-synth", auto_subdir=False)
        ad.brief_path = "/tmp/test-advisors-synth/brief.md"
        with open(ad.brief_path, "w") as f:
            f.write("brief")
        with self.assertRaises(ValueError):
            ad.synthesize()


class TestReadSynthesis(unittest.TestCase):
    """read_synthesis() — None on missing/empty."""

    def test_returns_none_when_no_synthesis(self):
        ad = AdvisorDispatch(outdir="/tmp/test-advisors-read", auto_subdir=False)
        self.assertIsNone(ad.read_synthesis())

    def test_returns_none_when_synthesis_empty(self):
        ad = AdvisorDispatch(outdir="/tmp/test-advisors-read2", auto_subdir=False)
        path = os.path.join(ad.outdir, "synthesis.md")
        with open(path, "w") as f:
            f.write("")
        self.assertIsNone(ad.read_synthesis())

    def test_returns_content_when_synthesis_exists(self):
        ad = AdvisorDispatch(outdir="/tmp/test-advisors-read3", auto_subdir=False)
        path = os.path.join(ad.outdir, "synthesis.md")
        with open(path, "w") as f:
            f.write("## Synthesis\n\nResult here")
        result = ad.read_synthesis()
        self.assertIsNotNone(result)
        self.assertIn("Result here", result)


class TestReadSeat(unittest.TestCase):
    """read_seat() — None on missing/empty."""

    def test_returns_none_when_no_results(self):
        ad = AdvisorDispatch(outdir="/tmp/test-advisors-seat", auto_subdir=False)
        self.assertIsNone(ad.read_seat(0))

    def test_returns_none_when_out_of_range(self):
        ad = AdvisorDispatch(outdir="/tmp/test-advisors-seat2", auto_subdir=False)
        ad.seat_results = [("role", "model", 0, 0, "/tmp/out.md")]
        self.assertIsNone(ad.read_seat(5))


class TestCLI(unittest.TestCase):
    """CLI subcommands."""

    def test_help_shows_subcommands(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "dispatch_advisors.py"), "--help"],
            capture_output=True, text=True
        )
        self.assertEqual(r.returncode, 0)
        for cmd in ["run", "prepare", "dispatch", "synthesize"]:
            self.assertIn(cmd, r.stdout)

    def test_cli_prepare(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "dispatch_advisors.py"), "prepare",
             "--question", "CLI question", "--context", "CLI context",
             "--outdir", "/tmp/test-advisors-cli"],
            capture_output=True, text=True
        )
        self.assertEqual(r.returncode, 0, f"CLI prepare failed: {r.stderr}")
        brief_path = r.stdout.strip()
        self.assertTrue(os.path.exists(brief_path))
        content = open(brief_path).read()
        self.assertIn("CLI question", content)
        self.assertIn("CLI context", content)

    def test_cli_prepare_with_context_file(self):
        os.makedirs("/tmp/test-advisors-cli2", exist_ok=True)
        ctx_file = "/tmp/test-advisors-cli2/ctx.md"
        with open(ctx_file, "w") as f:
            f.write("File context here")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "dispatch_advisors.py"), "prepare",
             "--question", "Q", "--context-file", ctx_file,
             "--outdir", "/tmp/test-advisors-cli2"],
            capture_output=True, text=True
        )
        self.assertEqual(r.returncode, 0)
        content = open(r.stdout.strip()).read()
        self.assertIn("File context here", content)

    def test_cli_synthesize_requires_manifest(self):
        """Bug D fix: no fallback to filename scanning."""
        os.makedirs("/tmp/test-advisors-cli3", exist_ok=True)
        # Create a brief file so the brief existence check passes
        with open("/tmp/test-advisors-cli3/brief.md", "w") as f:
            f.write("## Question\n\ntest question")
        # Create a fake seat file without seats.json
        with open("/tmp/test-advisors-cli3/seat-1-test.md", "w") as f:
            f.write("fake review")
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "dispatch_advisors.py"), "synthesize",
             "--brief", "/tmp/test-advisors-cli3/brief.md",
             "--outdir", "/tmp/test-advisors-cli3"],
            capture_output=True, text=True
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("seats.json", r.stderr)

    def test_cli_dispatch_missing_brief_fails(self):
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "dispatch_advisors.py"), "dispatch",
             "--brief", "/nonexistent/brief.md",
             "--outdir", "/tmp/test-advisors-cli4"],
            capture_output=True, text=True
        )
        self.assertNotEqual(r.returncode, 0)


class TestPathsResolve(unittest.TestCase):
    """Import paths resolve correctly."""

    def test_ask_scripts_dir_exists(self):
        self.assertTrue(os.path.exists(ASK_SCRIPTS_DIR))

    def test_prompt_model_exists(self):
        self.assertTrue(os.path.exists(PROMPT_MODEL))

    def test_script_dir_is_correct(self):
        expected = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "scripts"
        ))
        self.assertEqual(os.path.normpath(SCRIPTS_DIR), expected)


class TestAutoSubdirIsolation(unittest.TestCase):
    """Run-specific subdirectories eliminate stale file issues."""

    def test_two_runs_dont_collide(self):
        """Two AdvisorDispatch instances with auto_subdir get different dirs."""
        with tempfile.TemporaryDirectory() as tmp:
            ad1 = AdvisorDispatch(outdir=tmp, auto_subdir=True)
            ad1.prepare_brief(question="Q1", context="Run 1")

            ad2 = AdvisorDispatch(outdir=tmp, auto_subdir=True)
            ad2.prepare_brief(question="Q2", context="Run 2")

            # Different directories
            self.assertNotEqual(ad1.outdir, ad2.outdir)

            # Both briefs exist and have correct content
            self.assertIn("Run 1", open(ad1.brief_path).read())
            self.assertIn("Run 2", open(ad2.brief_path).read())


if __name__ == "__main__":
    unittest.main(verbosity=2)