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
import time
import unittest
from unittest.mock import patch, MagicMock

# Add parent dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


class TestDispatchSingleReturnShape(unittest.TestCase):
    """Verify dispatch_single returns the documented shape on all paths."""

    # ── Error path (no API call needed) ──────────────────────────────────

    @patch("model_utils.subprocess.run")
    def test_error_path_has_required_keys(self, mock_run):
        """dispatch_single must return {content, session_id, elapsed, error, thinking} on error."""
        from model_utils import dispatch_single

        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Some error"
        mock_run.return_value = mock_result

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

        # On error: content must be None, error must be non-None
        self.assertIsNone(r["content"])
        self.assertIsNotNone(r["error"])
        self.assertIsInstance(r["elapsed"], (int, float))
        self.assertGreaterEqual(r["elapsed"], 0)

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

    @patch("model_utils.subprocess.run")
    def test_api_error_path_has_required_keys(self, mock_run):
        """dispatch_single must return documented shape when content is an API error."""
        from model_utils import dispatch_single

        mock_result = MagicMock()
        mock_result.stdout = "API call failed: HTTP 429. Rate limit exceeded. Error code: 429"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

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

    # ── Success path (mocked) ────────────────────────────────────────────

    @patch("model_utils.subprocess.run")
    def test_success_path_has_required_keys(self, mock_run):
        """dispatch_single must return documented shape on success."""
        from model_utils import dispatch_single

        mock_result = MagicMock()
        mock_result.stdout = "Here is the answer"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

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

        # On success: content must be non-None, error must be None
        self.assertIsNotNone(r["content"])
        self.assertIsNone(r["error"])

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



if __name__ == "__main__":
    unittest.main()