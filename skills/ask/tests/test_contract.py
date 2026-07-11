#!/usr/bin/env python3
"""test_contract — Verify the ask skill's interaction contract.

Tests that dispatch_single's return shape matches the documented contract
in ask.py's module docstring. Catches regressions where someone changes the
return dict without updating the contract.

Run:  python3 -m pytest tests/test_contract.py -v
Or:   uv run --with pytest python3 -m pytest tests/test_contract.py -v
"""

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

# Add parent dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


class TestDispatchSingleReturnShape(unittest.TestCase):
    """Verify dispatch_single returns the documented shape on all paths."""

    @staticmethod
    def _result(returncode=0, stdout="", stderr=""):
        """Build the minimal subprocess result used by dispatch_single."""
        return type("StubResult", (), {
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
        })()

    # ── Error path (no API call needed) ──────────────────────────────────

    @patch("model_utils.subprocess.run")
    def test_error_path_has_required_keys(self, mock_run):
        """dispatch_single must return {content, session_id, elapsed, error, thinking, fallback} on error."""
        from model_utils import dispatch_single

        mock_run.return_value = self._result(returncode=2, stderr="Some error")

        r = dispatch_single(
            model="nonexistent:model",
            prompt="test",
            context="",
            toolsets="",
            max_turns=None,
            timeout=5,
            provider="test",
        )

        # Documented keys must be present
        self.assertIn("content", r)
        self.assertIn("session_id", r)
        self.assertIn("elapsed", r)
        self.assertIn("error", r)
        self.assertIn("thinking", r)
        self.assertIn("fallback", r)

        # On error: content must be None, error must be non-None
        self.assertIsNone(r["content"])
        self.assertIsNotNone(r["error"])
        self.assertIsInstance(r["elapsed"], (int, float))
        self.assertGreaterEqual(r["elapsed"], 0)
        self.assertEqual(r["thinking"], "default")
        self.assertIn("exit 2", r["error"])
        self.assertEqual(r["returncode"], 2)

    @patch("model_utils.subprocess.run")
    def test_timeout_path_has_required_keys(self, mock_run):
        """dispatch_single must return documented shape on timeout."""
        import subprocess as sp
        from model_utils import dispatch_single

        mock_run.side_effect = sp.TimeoutExpired(cmd="hermes", timeout=1)

        r = dispatch_single(
            model="any:model",
            prompt="test",
            context="",
            toolsets="",
            max_turns=None,
            timeout=1,
            provider="test",
        )

        self.assertIsNone(r["content"])
        self.assertIsNotNone(r["error"])
        self.assertIn("Timed out", r["error"])
        self.assertIn("elapsed", r)
        self.assertEqual(r["thinking"], "default")

    @patch("model_utils.subprocess.run")
    def test_api_error_path_has_required_keys(self, mock_run):
        """dispatch_single must return documented shape when content is an API error."""
        from model_utils import dispatch_single

        mock_run.return_value = self._result(
            stdout="API call failed: HTTP 429. Rate limit exceeded. Error code: 429"
        )

        r = dispatch_single(
            model="any:model",
            prompt="test",
            context="",
            toolsets="",
            max_turns=None,
            timeout=5,
            provider="test",
        )

        # API errors should be detected and converted to error returns
        self.assertIsNone(r["content"])
        self.assertIsNotNone(r["error"])
        self.assertEqual(r["thinking"], "default")

    @patch("model_utils.subprocess.run")
    def test_generic_exception_path_has_default_thinking(self, mock_run):
        """dispatch_single must include default thinking on generic exceptions."""
        from model_utils import dispatch_single

        mock_run.side_effect = OSError("subprocess unavailable")

        r = dispatch_single(
            model="any:model", prompt="test", context="", toolsets="",
            max_turns=None, timeout=5, provider="test",
        )

        self.assertIsNone(r["content"])
        self.assertEqual(r["error"], "subprocess unavailable")
        self.assertEqual(r["thinking"], "default")

    # ── Success path (mocked) ────────────────────────────────────────────

    @patch("model_utils.subprocess.run")
    def test_success_path_has_required_keys(self, mock_run):
        """dispatch_single must return documented shape on success."""
        from model_utils import dispatch_single

        mock_run.return_value = self._result(stdout="Here is the answer")

        r = dispatch_single(
            model="any:model",
            prompt="test",
            context="",
            toolsets="",
            max_turns=None,
            timeout=5,
            provider="test",
        )

        self.assertIn("content", r)
        self.assertIn("session_id", r)
        self.assertIn("elapsed", r)
        self.assertIn("error", r)
        self.assertIn("thinking", r)
        self.assertIn("fallback", r)

        # On success: content must be non-None, error must be None
        self.assertIsNotNone(r["content"])
        self.assertIsNone(r["error"])
        self.assertEqual(r["thinking"], "default")

    @patch("model_utils.subprocess.run")
    def test_empty_output_exit_zero_includes_returncode_and_default_thinking(self, mock_run):
        """Empty output preserves exit 0 for the retry classifier."""
        from model_utils import dispatch_single

        mock_run.return_value = self._result(returncode=0)

        r = dispatch_single(
            model="any:model", prompt="test", context="", toolsets="",
            max_turns=None, timeout=5, provider="test",
        )

        self.assertIsNone(r["content"])
        self.assertIn("exit 0", r["error"])
        self.assertEqual(r["returncode"], 0)
        self.assertEqual(r["thinking"], "default")

    # ── DispatchEvent TypedDict ──────────────────────────────────────────

    def test_dispatch_event_typedict_has_timestamp(self):
        """DispatchEvent TypedDict must have timestamp field."""
        from model_utils import DispatchEvent

        # TypedDict with total=False allows any subset of keys
        # We just verify the class exists and has the expected annotations
        annotations = DispatchEvent.__annotations__
        self.assertIn("timestamp", annotations)
        self.assertIn("model", annotations)
        self.assertIn("elapsed", annotations)
        self.assertIn("success", annotations)
        self.assertIn("error", annotations)
        self.assertIn("notice", annotations)

    # ── progress_callback invocation ────────────────────────────────────

    @patch("model_utils.subprocess.run")
    def test_progress_callback_called_on_start_and_end(self, mock_run):
        """dispatch_single must invoke progress_callback for start and end events."""
        from model_utils import dispatch_single

        mock_result = MagicMock()
        mock_result.stdout = "Answer"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        events = []
        def callback(event):
            events.append(event["event"])

        dispatch_single(
            model="any:model",
            prompt="test",
            context="",
            toolsets="",
            max_turns=None,
            timeout=5,
            provider="test",
            progress_callback=callback,
        )

        self.assertIn("dispatch_start", events)
        self.assertIn("dispatch_end", events)

    @patch("model_utils.subprocess.run")
    def test_auth_fallback_is_returned_and_emitted_before_dispatch_end(self, mock_run):
        """Auth fallback notices leave content and are emitted before dispatch_end."""
        from model_utils import dispatch_single

        mock_run.return_value = self._result(
            stdout="⚠️ Primary auth failed — switching to fallback: gemma\nReal answer"
        )
        events = []
        r = dispatch_single(
            model="any:model", prompt="test", context="", toolsets="",
            max_turns=None, timeout=5, provider="test", progress_callback=events.append,
        )

        self.assertEqual(r["content"], "Real answer")
        self.assertIn("Primary auth failed", r["fallback"])
        self.assertEqual([event["event"] for event in events],
                         ["dispatch_start", "fallback", "dispatch_end"])

    @patch("model_utils.subprocess.run")
    def test_model_fallback_is_returned_and_emitted_before_dispatch_end(self, mock_run):
        """Model fallback notices leave content and are emitted before dispatch_end."""
        from model_utils import dispatch_single

        mock_run.return_value = self._result(
            stdout="🔄 Primary model failed — switching to fallback: gemma\nReal answer"
        )
        events = []
        r = dispatch_single(
            model="any:model", prompt="test", context="", toolsets="",
            max_turns=None, timeout=5, provider="test", progress_callback=events.append,
        )

        self.assertEqual(r["content"], "Real answer")
        self.assertIn("Primary model failed", r["fallback"])
        self.assertEqual([event["event"] for event in events],
                         ["dispatch_start", "fallback", "dispatch_end"])

    @patch("model_utils.subprocess.run")
    def test_no_fallback_has_no_fallback_event(self, mock_run):
        """Responses without notices do not report a fallback event."""
        from model_utils import dispatch_single

        mock_run.return_value = self._result(stdout="Real answer")
        events = []
        r = dispatch_single(
            model="any:model", prompt="test", context="", toolsets="",
            max_turns=None, timeout=5, provider="test", progress_callback=events.append,
        )

        self.assertIsNone(r["fallback"])
        self.assertEqual([event["event"] for event in events],
                         ["dispatch_start", "dispatch_end"])

    def test_clean_output_keeps_two_tuple_and_strips_fallback_notice(self):
        """The public clean_output wrapper remains a two-tuple API."""
        from model_utils import clean_output

        result = clean_output(
            "⚠️ Primary auth failed — switching to fallback: gemma\nReal answer"
        )

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertEqual(result, ("Real answer", None))

    # ── Alias resolution ─────────────────────────────────────────────────

    def test_resolve_alias_returns_full_model_name(self):
        """resolve_alias must map short names to full model IDs."""
        from model_utils import resolve_alias

        self.assertEqual(resolve_alias("deepseek"), "deepseek-v4-pro:cloud")
        self.assertEqual(resolve_alias("kimi"), "kimi-k2.7-code:cloud")
        # Full names pass through unchanged
        self.assertEqual(resolve_alias("deepseek-v4-pro:cloud"), "deepseek-v4-pro:cloud")

    # ── _alias_for_model helper ──────────────────────────────────────────

    def test_alias_for_model_returns_alias_key(self):
        """_alias_for_model must return the alias key for a full model name."""
        from ask import _alias_for_model

        self.assertEqual(_alias_for_model("deepseek-v4-pro:cloud"), "deepseek")
        self.assertEqual(_alias_for_model("kimi-k2.7-code:cloud"), "kimi")
        self.assertIsNone(_alias_for_model("nonexistent:model"))


class TestAutoAnswerHelpers(unittest.TestCase):
    """The shared auto-answer helpers keep both dispatch seams consistent."""

    def test_is_question_shaped(self):
        from model_utils import is_question_shaped

        self.assertTrue(is_question_shaped("Should I use X or Y?"))
        self.assertFalse(is_question_shaped("```python\nprint('why?')\n```"))
        self.assertFalse(is_question_shaped("This is a declarative statement."))
        self.assertTrue(is_question_shaped("Which option?  \n"))

    @patch("model_utils.dispatch_single")
    def test_generate_auto_answer_artifact_beats_stdout(self, dispatch):
        from model_utils import answer_artifact_path, generate_auto_answer

        dispatch.return_value = {"content": "B", "error": None}
        with tempfile.TemporaryDirectory() as run_dir:
            path = answer_artifact_path(run_dir, "Choose an option?")
            with open(path, "w", encoding="utf-8") as artifact:
                artifact.write('{"answer": "A"}')
            result = generate_auto_answer(
                "Choose an option?", answer_model="test-model", run_dir=run_dir,
            )

        self.assertEqual(result, {"answer": "A", "error": None})

    @patch("model_utils.dispatch_single")
    def test_generate_auto_answer_uses_stdout_without_artifact(self, dispatch):
        from model_utils import generate_auto_answer

        dispatch.return_value = {"content": "B", "error": None}
        result = generate_auto_answer("Choose an option?", answer_model="test-model")

        self.assertEqual(result, {"answer": "B", "error": None})



if __name__ == "__main__":
    unittest.main()
