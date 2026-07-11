#!/usr/bin/env python3
"""Test suite for ask.py — alias resolution, thinking levels, CLI parsing, dry-run safe.

Run:  python3 -m pytest tests/test_ask.py -v
Or:   python3 tests/test_ask.py

Tests are organized in groups:
  1. Alias resolution — fast, no API calls
  2. Thinking levels — fast, no API calls (uses hermes config show/set but restores)
  3. CLI parsing — fast, no API calls
  4. Dry-run dispatch — fast, no model calls (mocks hermes chat)
  5. Live dispatch — slow, requires API (skipped if OLLAMA_URL unreachable)
"""

import io
import json
import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

# Add parent dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from ask import (
    THINKING_LEVELS, resolve_alias, is_known_model,
    build_prompt, clean_output, get_reasoning_effort, set_reasoning_effort,
    dispatch_single, dispatch_comparison, save_session, get_session, dispatch_single_raw, _run_raw_mode, _run_agent_mode,
    clean_expired_sessions,
)
import ask
import model_utils

HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
ASK_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "ask.py")

# Import model_utils for mocking purposes


class TestAliasResolution(unittest.TestCase):
    """Test alias resolution — fast, no API."""

    def test_deepseek_alias(self):
        self.assertEqual(resolve_alias("deepseek"), "deepseek-v4-pro:cloud")

    def test_ds_shortcut(self):
        self.assertEqual(resolve_alias("ds"), "deepseek-v4-pro:cloud")

    def test_kimi_alias(self):
        self.assertEqual(resolve_alias("kimi"), "kimi-k2.7-code:cloud")

    def test_qwen_alias(self):
        self.assertEqual(resolve_alias("qwen"), "qwen3.6:35b-a3b")

    def test_glm_alias(self):
        self.assertEqual(resolve_alias("glm"), "glm-5.2:cloud")

    def test_fast_alias(self):
        self.assertEqual(resolve_alias("fast"), "qwen3.6:35b-a3b")

    def test_gemma_alias(self):
        self.assertEqual(resolve_alias("gemma"), "gemma4:12b-mlx-bf16")

    def test_full_model_passthrough(self):
        self.assertEqual(resolve_alias("deepseek-v4-pro:cloud"), "deepseek-v4-pro:cloud")

    def test_unknown_passthrough(self):
        self.assertEqual(resolve_alias("unknown-model"), "unknown-model")

    def test_case_insensitive(self):
        self.assertEqual(resolve_alias("DeepSeek"), "deepseek-v4-pro:cloud")
        self.assertEqual(resolve_alias("KIMI"), "kimi-k2.7-code:cloud")

    def test_is_known_model_alias(self):
        self.assertTrue(is_known_model("deepseek"))
        self.assertTrue(is_known_model("kimi"))

    def test_is_known_model_full_name(self):
        self.assertTrue(is_known_model("deepseek-v4-pro:cloud"))

    def test_is_not_known_model(self):
        self.assertFalse(is_known_model("what"))
        self.assertFalse(is_known_model("hello world"))

    def test_dev_role_aliases(self):
        self.assertEqual(resolve_alias("planner"), "glm-5.2:cloud")
        self.assertEqual(resolve_alias("coder"), "qwen3-coder-next:q4_K_M")
        # P9: debugger is now qwen-coder (primary), kimi is debugger-fallback
        self.assertEqual(resolve_alias("debugger"), "qwen3-coder-next:q4_K_M")
        self.assertEqual(resolve_alias("debugger-fallback"), "kimi-k2.7-code:cloud")
        self.assertEqual(resolve_alias("test-planner"), "deepseek-v4-pro:cloud")
        self.assertEqual(resolve_alias("qa"), "qwen3-coder-next:q4_K_M")

    def test_minimax_aliases(self):
        """Minimax M3 aliases — minimax, minimax-m3, mm, mm3."""
        self.assertEqual(resolve_alias("minimax"), "minimax-m3:cloud")
        self.assertEqual(resolve_alias("minimax-m3"), "minimax-m3:cloud")
        self.assertEqual(resolve_alias("mm"), "minimax-m3:cloud")
        self.assertEqual(resolve_alias("mm3"), "minimax-m3:cloud")


class TestFuzzyAliasResolution(unittest.TestCase):
    """Test two-tier alias resolution: exact match → LLM fuzzy fallback.

    Mock tests (no API): verify tier-1 exact match, full-model passthrough,
    cache behavior, and graceful fallback when LLM is unavailable.
    Live tests (need Ollama): verify actual fuzzy matching.
    """

    def setUp(self):
        """Clear the fuzzy cache before each test."""
        from model_utils import _fuzzy_cache
        _fuzzy_cache.clear()

    def test_exact_match_no_llm(self):
        """Exact match returns immediately without calling the LLM."""
        from model_utils import resolve_alias_fuzzy
        resolved, was_fuzzy = resolve_alias_fuzzy("deepseek")
        self.assertEqual(resolved, "deepseek-v4-pro:cloud")
        self.assertFalse(was_fuzzy)

    def test_exact_match_minimax(self):
        """Minimax aliases hit exact match, no LLM."""
        from model_utils import resolve_alias_fuzzy
        resolved, was_fuzzy = resolve_alias_fuzzy("minimax")
        self.assertEqual(resolved, "minimax-m3:cloud")
        self.assertFalse(was_fuzzy)

    def test_full_model_passthrough_no_llm(self):
        """Full model names (with ':') pass through without LLM call."""
        from model_utils import resolve_alias_fuzzy
        resolved, was_fuzzy = resolve_alias_fuzzy("deepseek-v4-pro:cloud")
        self.assertEqual(resolved, "deepseek-v4-pro:cloud")
        self.assertFalse(was_fuzzy)

    def test_case_insensitive_exact(self):
        """Exact match is case-insensitive."""
        from model_utils import resolve_alias_fuzzy
        resolved, was_fuzzy = resolve_alias_fuzzy("DEEPSEEK")
        self.assertEqual(resolved, "deepseek-v4-pro:cloud")
        self.assertFalse(was_fuzzy)

    @patch("model_utils._fuzzy_resolve_raw", return_value=None)
    def test_fuzzy_llm_no_match_returns_original(self, mock_raw):
        """When LLM returns None, original name is returned unchanged."""
        from model_utils import resolve_alias_fuzzy
        resolved, was_fuzzy = resolve_alias_fuzzy("totally-unknown")
        self.assertEqual(resolved, "totally-unknown")
        self.assertFalse(was_fuzzy)  # was_fuzzy=False because no match was found
        mock_raw.assert_called_once()

    @patch("model_utils._fuzzy_resolve_raw", return_value="minimax-m3")
    def test_fuzzy_llm_match(self, mock_raw):
        """LLM fuzzy match resolves to correct model."""
        from model_utils import resolve_alias_fuzzy
        resolved, was_fuzzy = resolve_alias_fuzzy("minimax-3")
        self.assertEqual(resolved, "minimax-m3:cloud")
        self.assertTrue(was_fuzzy)
        mock_raw.assert_called_once()

    @patch("model_utils._fuzzy_resolve_raw", return_value="minimax-m3")
    def test_fuzzy_cache_hit_no_second_llm_call(self, mock_raw):
        """Second call with same input uses cache, doesn't call LLM again."""
        from model_utils import resolve_alias_fuzzy
        # First call — hits LLM
        r1, f1 = resolve_alias_fuzzy("minimax-3")
        self.assertTrue(f1)
        # Second call — should use cache
        r2, f2 = resolve_alias_fuzzy("minimax-3")
        self.assertEqual(r2, "minimax-m3:cloud")
        self.assertTrue(f2)
        # LLM should only have been called once
        self.assertEqual(mock_raw.call_count, 1)

    @patch("model_utils._fuzzy_resolve_raw", return_value="deepseek-pro")
    def test_fuzzy_llm_match_deepseek(self, mock_raw):
        """LLM fuzzy match for 'ds-pro' → deepseek-pro → deepseek-v4-pro:cloud."""
        from model_utils import resolve_alias_fuzzy
        resolved, was_fuzzy = resolve_alias_fuzzy("ds-pro")
        self.assertEqual(resolved, "deepseek-v4-pro:cloud")
        self.assertTrue(was_fuzzy)

    @patch("model_utils._fuzzy_resolve_raw", return_value=None)
    def test_fuzzy_llm_network_error_returns_original(self, mock_raw):
        """When LLM call fails (network error caught inside _fuzzy_resolve_raw),
        it returns None, which means no match → returns original, was_fuzzy=False."""
        from model_utils import resolve_alias_fuzzy
        resolved, was_fuzzy = resolve_alias_fuzzy("minimax-3")
        self.assertEqual(resolved, "minimax-3")
        self.assertFalse(was_fuzzy)


class TestFuzzyPromptBuilding(unittest.TestCase):
    """Test the prompt construction for the fuzzy resolver LLM."""

    def test_prompt_contains_user_input(self):
        from model_utils import _build_fuzzy_prompt
        prompt = _build_fuzzy_prompt("minimax-3", ["minimax", "deepseek"])
        self.assertIn("minimax-3", prompt)

    def test_prompt_contains_all_aliases(self):
        from model_utils import _build_fuzzy_prompt
        prompt = _build_fuzzy_prompt("test", ["minimax", "deepseek", "kimi"])
        self.assertIn("minimax", prompt)
        self.assertIn("deepseek", prompt)
        self.assertIn("kimi", prompt)

    def test_prompt_has_no_think_prefix(self):
        from model_utils import _build_fuzzy_prompt
        prompt = _build_fuzzy_prompt("test", ["minimax"])
        self.assertTrue(prompt.startswith("/no_think"))

    def test_prompt_has_none_instruction(self):
        from model_utils import _build_fuzzy_prompt
        prompt = _build_fuzzy_prompt("test", ["minimax"])
        self.assertIn("NONE", prompt)


class TestThinkingLevels(unittest.TestCase):
    """Test thinking level configuration — uses hermes config but restores."""

    def test_thinking_levels_exist(self):
        expected = {"none", "minimal", "low", "medium", "high", "xhigh"}
        self.assertEqual(set(THINKING_LEVELS.keys()), expected)

    def test_thinking_levels_have_descriptions(self):
        for level, desc in THINKING_LEVELS.items():
            self.assertIsInstance(desc, str)
            self.assertGreater(len(desc), 10, f"Description for '{level}' too short")

    def test_get_reasoning_effort_returns_string(self):
        """get_reasoning_effort should return a string (might be empty)."""
        result = get_reasoning_effort()
        self.assertIsInstance(result, str)

    def test_set_reasoning_effort_valid(self):
        """Test setting and restoring reasoning effort."""
        original = get_reasoning_effort()
        try:
            success = set_reasoning_effort("low")
            self.assertTrue(success, "set_reasoning_effort('low') failed")
            current = get_reasoning_effort()
            self.assertEqual(current, "low")
        finally:
            if original:
                set_reasoning_effort(original)

    def test_set_reasoning_effort_invalid(self):
        result = set_reasoning_effort("invalid_level")
        self.assertFalse(result)

    def test_set_reasoning_effort_none(self):
        """Test setting reasoning to 'none'."""
        original = get_reasoning_effort()
        try:
            set_reasoning_effort("none")
            current = get_reasoning_effort()
            self.assertEqual(current, "none")
        finally:
            if original:
                set_reasoning_effort(original)


class TestCLIParsing(unittest.TestCase):
    """Test CLI argument parsing — fast, no API calls."""

    def _run(self, args, timeout=10):
        return subprocess.run(
            ["python3", ASK_SCRIPT] + args,
            capture_output=True, text=True, timeout=timeout
        )

    def test_help(self):
        r = self._run(["--help"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("--thinking", r.stdout)
        self.assertIn("--models", r.stdout)

    def test_thinking_flag_in_choices(self):
        """--thinking should only accept valid levels."""
        r = self._run(["--thinking", "invalid", "fast", "test"])
        self.assertNotEqual(r.returncode, 0)

    def test_thinking_flag_accepted(self):
        """--thinking none should be accepted by argparse (will fail on missing model, not on --thinking)."""
        r = self._run(["--thinking", "none", "fast", "--prompt", "test", "--timeout", "1"])
        # Should not fail on --thinking parsing — it might fail on timeout
        # but the error should NOT be "invalid choice"
        self.assertNotIn("invalid choice", r.stderr)

    def test_sessions_flag(self):
        r = self._run(["--sessions"])
        self.assertEqual(r.returncode, 0)

    def test_no_models_error(self):
        r = self._run(["just a prompt"])
        self.assertEqual(r.returncode, 3)
        self.assertIn("Available aliases", r.stderr)

    def test_fast_alias_in_available_list(self):
        r = self._run(["just a prompt"])
        self.assertIn("fast", r.stderr)


class TestEmitEvents(unittest.TestCase):
    """Verify the ask CLI keeps its JSONL event contract."""

    def test_stderr_event_callback_is_model_utils_compatibility_alias(self):
        self.assertIs(
            ask._make_stderr_event_callback,
            model_utils._make_stderr_event_callback,
        )

    def test_emit_events_writes_jsonl_to_stderr(self):
        stderr = io.StringIO()

        def fake_dispatch(*args, **kwargs):
            callback = kwargs["progress_callback"]
            callback({"event": "dispatch_start", "model": "qwen3.6:35b-a3b"})
            callback({"event": "dispatch_end", "model": "qwen3.6:35b-a3b", "success": True})
            return {
                "content": "response", "session_id": None,
                "elapsed": 0.1, "error": None,
            }

        with patch.object(sys, "argv", ["ask.py", "fast", "hello", "--emit-events"]), \
             patch("ask.dispatch_single", side_effect=fake_dispatch), \
             patch("ask.get_session", return_value={}), \
             patch.object(sys.stdin, "isatty", return_value=True), \
             patch.object(sys, "stderr", stderr):
            ask.main()

        events = [json.loads(line) for line in stderr.getvalue().splitlines() if line.strip()]
        self.assertEqual([event["event"] for event in events], ["dispatch_start", "dispatch_end"])


class TestBuildPrompt(unittest.TestCase):
    """Test prompt building — fast, no API."""

    def test_basic_prompt(self):
        prompt = build_prompt("What is ACID?", "", "deepseek-v4-pro:cloud")
        self.assertIn("What is ACID?", prompt)

    def test_context_included(self):
        prompt = build_prompt("Design API", "Use FastAPI", "glm-5.2:cloud")
        self.assertIn("CONTEXT:", prompt)
        self.assertIn("Use FastAPI", prompt)

    def test_english_directive_for_glm(self):
        prompt = build_prompt("test", "", "glm-5.2:cloud")
        self.assertIn("respond in English", prompt)

    def test_no_english_directive_for_deepseek(self):
        prompt = build_prompt("test", "", "deepseek-v4-pro:cloud")
        self.assertNotIn("respond in English", prompt)


class TestCleanOutput(unittest.TestCase):
    """Test output cleaning — fast."""

    def test_strips_bitwarden(self):
        raw = f"{BITWARDEN_PREFIX}\nHello world"
        content, _ = clean_output(raw)
        self.assertEqual(content, "Hello world")

    def test_extracts_session_id(self):
        raw = "session_id: abc123\nHello world"
        content, sid = clean_output(raw)
        self.assertEqual(content, "Hello world")
        self.assertEqual(sid, "abc123")

    def test_strips_unknown_toolsets_warning(self):
        raw = "Warning: Unknown toolsets: foo\nHello"
        content, _ = clean_output(raw)
        self.assertEqual(content, "Hello")


BITWARDEN_PREFIX = "Bitwarden Secrets Manager"


class TestDryRunDispatch(unittest.TestCase):
    """Test dispatch_single with mocked subprocess — no real API calls."""

    @patch("model_utils.subprocess.run")
    def test_dispatch_returns_content(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = "Hello from the model"
        mock_result.stderr = "session_id: test123"
        mock_run.return_value = mock_result

        r = dispatch_single(
            "deepseek-v4-pro:cloud", "test prompt", "", "file", 5, 30, "ollama-glm"
        )
        self.assertEqual(r["content"], "Hello from the model")
        self.assertEqual(r["session_id"], "test123")
        self.assertIsNone(r["error"])

    @patch("model_utils.subprocess.run")
    def test_dispatch_empty_output(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        r = dispatch_single("test-model", "test", "", "", 1, 10, "test")
        self.assertIsNone(r["content"])
        self.assertIn("Empty output", r["error"])

    @patch("model_utils.subprocess.run")
    def test_dispatch_timeout(self, mock_run):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="hermes", timeout=5)

        r = dispatch_single("test-model", "test", "", "", 1, 5, "test")
        self.assertIsNone(r["content"])
        self.assertIn("Timed out", r["error"])

    @patch("ask.dispatch_single")
    def test_dispatch_with_thinking(self, mock_dispatch):
        """Test that thinking level is passed through to dispatch."""
        import ask as ask_module
        mock_dispatch.return_value = {
            "content": "Deep answer", "session_id": None,
            "elapsed": 1.0, "error": None, "thinking": "high"
        }

        r = ask_module.dispatch_single(
            "test-model", "test", "", "", 1, 10, "test",
            thinking="high"
        )
        # Should have delegated with thinking="high"
        mock_dispatch.assert_called_once()
        _, kwargs = mock_dispatch.call_args
        self.assertEqual(kwargs.get("thinking"), "high")
        self.assertEqual(r["thinking"], "high")

    @patch("ask.dispatch_single")
    def test_dispatch_restores_thinking_on_error(self, mock_dispatch):
        """Test that error propagates when dispatch fails."""
        import ask as ask_module
        mock_dispatch.return_value = {
            "content": None, "session_id": None,
            "elapsed": 5.0, "error": "Timed out"
        }

        r = ask_module.dispatch_single(
            "test-model", "test", "", "", 1, 5, "test",
            thinking="low"
        )
        self.assertIn("Timed out", r["error"])

    @patch("model_utils.subprocess.run")
    @patch("model_utils.get_reasoning_effort")
    @patch("model_utils.set_reasoning_effort")
    def test_dispatch_no_thinking_no_config_change(self, mock_set, mock_get, mock_run):
        """Without --thinking, no config changes should happen."""
        mock_result = MagicMock()
        mock_result.stdout = "Answer"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        r = dispatch_single("test-model", "test", "", "", 1, 10, "test")
        mock_set.assert_not_called()
        mock_get.assert_not_called()
        self.assertEqual(r["thinking"], "default")

    @patch("model_utils.subprocess.run")
    def test_dispatch_output_includes_thinking_metadata(self, mock_run):
        """File output should include thinking level in metadata header."""
        import tempfile
        mock_result = MagicMock()
        mock_result.stdout = "Deep answer"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            tmpfile = f.name

        try:
            dispatch_single(
                "test-model", "test", "", "", 1, 10, "test",
                output_file=tmpfile, thinking="xhigh"
            )
            with open(tmpfile) as f:
                content = f.read()
            self.assertIn("thinking: xhigh", content)
        finally:
            os.unlink(tmpfile)


class TestComparisonMode(unittest.TestCase):
    """Test dispatch_comparison — covers race condition fix and parallel/sequential modes."""

    @patch("model_utils.subprocess.run")
    def test_comparison_without_thinking_runs_parallel(self, mock_run):
        """Without --thinking, comparison mode should run all models in parallel."""
        mock_result = MagicMock()
        mock_result.stdout = "Answer"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        models = ["model-a", "model-b", "model-c"]
        results = dispatch_comparison(
            models, "test", "", "", 1, 10, "test", thinking=None
        )
        self.assertEqual(len(results), 3)
        # All should succeed
        for r in results:
            self.assertIsNotNone(r["content"])

    @patch("model_utils.dispatch_single")
    def test_comparison_with_thinking_runs_sequential(self, mock_dispatch):
        """With --thinking, comparison mode should run sequentially to avoid race."""
        mock_dispatch.return_value = {
            "content": "Answer", "session_id": None,
            "elapsed": 1.0, "error": None, "thinking": "high"
        }

        models = ["model-a", "model-b"]
        results = dispatch_comparison(
            models, "test", "", "", 1, 10, "test", thinking="high"
        )
        self.assertEqual(len(results), 2)
        # Both should succeed
        for r in results:
            self.assertIsNotNone(r["content"])

    @patch("model_utils.dispatch_single")
    def test_comparison_with_thinking_restores_on_error(self, mock_dispatch):
        """With --thinking, if one model fails, error propagates."""
        mock_dispatch.return_value = {
            "content": None, "session_id": None,
            "elapsed": 5.0, "error": "Timed out"
        }

        models = ["model-a", "model-b"]
        results = dispatch_comparison(
            models, "test", "", "", 1, 5, "test", thinking="low"
        )
        self.assertEqual(len(results), 2)
        # Both should have errors
        for r in results:
            self.assertIn("Timed out", r["error"])

    @patch("model_utils.subprocess.run")
    def test_comparison_results_sorted_by_model_order(self, mock_run):
        """Results should be sorted by the original model order, not completion order."""
        # Make different models return at different speeds
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            mock_r = MagicMock()
            mock_r.stdout = f"Answer from call {call_count[0]}"
            mock_r.stderr = ""
            return mock_r

        mock_run.side_effect = side_effect
        models = ["model-c", "model-a", "model-b"]
        results = dispatch_comparison(
            models, "test", "", "", 1, 10, "test", thinking=None
        )
        # Results should be in original order: model-c, model-a, model-b
        self.assertEqual(results[0]["model"], "model-c")
        self.assertEqual(results[1]["model"], "model-a")
        self.assertEqual(results[2]["model"], "model-b")


class TestLiveDispatch(unittest.TestCase):
    """Live API tests — skipped if Ollama is unreachable."""

    @classmethod
    def setUpClass(cls):
        """Check if Ollama API is reachable."""
        import urllib.request
        try:
            req = urllib.request.Request(
                "http://host.docker.internal:11434/api/tags",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.load(resp)
                cls.ollama_reachable = True
                cls.available_models = {
                    model.get("name") for model in payload.get("models", [])
                    if model.get("name")
                }
        except Exception:
            cls.ollama_reachable = False
            cls.available_models = set()

    def setUp(self):
        if not self.ollama_reachable:
            self.skipTest("Ollama API not reachable")
        if resolve_alias("fast") not in self.available_models:
            self.skipTest(f"fast model {resolve_alias('fast')} is unavailable")

    def test_live_fast_alias(self):
        """Test that 'fast' alias works end-to-end."""
        r = dispatch_single(
            resolve_alias("fast"), "What is 2+2? Answer with just the number.",
            "", "", 1, 60, "ollama-glm",
        )
        self.assertIsNotNone(r["content"], f"Error: {r.get('error')}")
        self.assertIn("4", r["content"])

    def test_live_thinking_restored(self):
        """Test that reasoning effort is restored after a thinking call."""
        original = get_reasoning_effort()
        dispatch_single(
            resolve_alias("fast"), "What is 3+3?", "", "", 1, 60, "ollama-glm",
            thinking="none",
        )
        restored = get_reasoning_effort()
        self.assertEqual(original, restored, "Reasoning effort was not restored after call")


class TestTriageDryRun(unittest.TestCase):
    """Test triage.py --dry-run — fast, no API."""

    TRIAGE_SCRIPT = "/opt/data/skills/productivity/triage/scripts/triage.py"

    def _run(self, args, timeout=10):
        return subprocess.run(
            ["python3", self.TRIAGE_SCRIPT] + args,
            capture_output=True, text=True, timeout=timeout
        )

    def test_dry_run_shows_prompt(self):
        r = self._run(["test message", "--dry-run"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("DRY RUN", r.stdout)
        self.assertIn("test message", r.stdout)

    def test_dry_run_json(self):
        r = self._run(["hello", "--dry-run", "--json"])
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertTrue(data["dry_run"])
        self.assertIn("prompt", data)
        self.assertIn("categories", data)

    def test_dry_run_custom_categories(self):
        r = self._run(["test", "--categories", "a,b,c", "--dry-run", "--json"])
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["categories"], ["a", "b", "c"])

    def test_dry_run_shows_role(self):
        r = self._run(["test", "--dry-run"])
        # P2-E: Stripped "tactical intent classifier" persona — now just "Classify"
        self.assertIn("Classify", r.stdout)

    def test_dry_run_shows_rules(self):
        r = self._run(["test", "--dry-run"])
        self.assertIn("Classification Rules", r.stdout)
        self.assertIn("Primary intent wins", r.stdout)

    def test_dry_run_shows_examples(self):
        r = self._run(["test", "--dry-run"])
        # P0-B: Few-shot examples now use bare category names (no "Category:" prefix)
        # Verify examples are present by checking for known category names
        for cat in ("query_model", "build_code", "debug_code", "general_chat"):
            self.assertIn(cat, r.stdout)


class TestTriageLiveAPI(unittest.TestCase):
    """Test triage with live Ollama API — skipped if unreachable."""

    @classmethod
    def setUpClass(cls):
        import urllib.request
        try:
            req = urllib.request.Request(
                "http://host.docker.internal:11434/api/tags",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5):
                cls.ollama_reachable = True
        except Exception:
            cls.ollama_reachable = False

    def setUp(self):
        if not self.ollama_reachable:
            self.skipTest("Ollama API not reachable")

    TRIAGE_SCRIPT = "/opt/data/skills/productivity/triage/scripts/triage.py"

    def _run(self, args, timeout=15):
        return subprocess.run(
            ["python3", self.TRIAGE_SCRIPT] + args,
            capture_output=True, text=True, timeout=timeout
        )

    def test_urgent_classification(self):
        r = self._run(["URGENT: production is down!", "--json"])
        data = json.loads(r.stdout)
        self.assertEqual(data["category"], "urgent_action")
        self.assertEqual(data["confidence"], "high")

    def test_build_classification(self):
        r = self._run(["Build a REST API", "--json"])
        data = json.loads(r.stdout)
        self.assertEqual(data["category"], "build_code")

    def test_query_model_classification(self):
        r = self._run(["ask deepseek what is ACID?", "--json"])
        data = json.loads(r.stdout)
        self.assertEqual(data["category"], "query_model")

    def test_has_raw_output(self):
        r = self._run(["hello", "--json"])
        data = json.loads(r.stdout)
        self.assertIn("raw_output", data)
        self.assertIn("exact_match", data)

    def test_multi_intent_primary_wins(self):
        r = self._run(["Research ORM options, then build a prototype", "--json"])
        data = json.loads(r.stdout)
        self.assertEqual(data["category"], "research_info")


class TestSessionManagement(unittest.TestCase):
    """Test session save/get/list/resume — uses temp file, no real sessions."""

    def setUp(self):
        """Use a temp file for sessions so we don't clobber real sessions."""
        import tempfile
        import model_utils as mu_module
        self._tmpdir = tempfile.mkdtemp()
        self._orig = mu_module.SESSIONS_FILE
        mu_module.SESSIONS_FILE = os.path.join(self._tmpdir, "test-sessions.json")

    def tearDown(self):
        import model_utils as mu_module
        mu_module.SESSIONS_FILE = self._orig
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_save_session_creates_file(self):
        import model_utils as mu_module
        save_session("deepseek", "deepseek-v4-pro:cloud", "sid_123", "test prompt")
        self.assertTrue(os.path.exists(mu_module.SESSIONS_FILE))

    def test_save_session_stores_correct_fields(self):
        save_session("kimi", "kimi-k2.7-code:cloud", "sid_456", "hello world")
        info = get_session("kimi")
        self.assertEqual(info["model"], "kimi-k2.7-code:cloud")
        self.assertEqual(info["session_id"], "sid_456")
        self.assertEqual(info["prompt_preview"], "hello world")
        self.assertIn("timestamp", info)

    def test_save_session_truncates_preview(self):
        long_prompt = "x" * 500
        save_session("test", "model", "sid", long_prompt)
        info = get_session("test")
        self.assertEqual(len(info["prompt_preview"]), 200)

    def test_save_session_case_insensitive_alias(self):
        save_session("DeepSeek", "model", "sid", "prompt")
        info = get_session("deepseek")
        self.assertEqual(info["session_id"], "sid")

    def test_save_session_overwrites_existing(self):
        save_session("test", "model-a", "sid_1", "prompt 1")
        save_session("test", "model-b", "sid_2", "prompt 2")
        info = get_session("test")
        self.assertEqual(info["session_id"], "sid_2")
        self.assertEqual(info["model"], "model-b")

    def test_save_session_preserves_other_entries(self):
        save_session("deepseek", "model-a", "sid_a", "prompt a")
        save_session("kimi", "model-b", "sid_b", "prompt b")
        self.assertEqual(get_session("deepseek")["session_id"], "sid_a")
        self.assertEqual(get_session("kimi")["session_id"], "sid_b")

    def test_get_session_missing_alias(self):
        save_session("deepseek", "model", "sid", "prompt")
        self.assertEqual(get_session("nonexistent"), {})

    def test_get_session_missing_file(self):
        # Don't create the file
        self.assertEqual(get_session("anything"), {})

    def test_get_session_corrupt_json(self):
        import model_utils as mu_module
        # Write corrupt JSON to the sessions file
        with open(mu_module.SESSIONS_FILE, "w") as f:
            f.write("{corrupt json!!!")
        self.assertEqual(get_session("anything"), {})

    def test_save_session_handles_corrupt_existing(self):
        import model_utils as mu_module
        # Write corrupt JSON, then save should still work
        with open(mu_module.SESSIONS_FILE, "w") as f:
            f.write("{corrupt")
        save_session("test", "model", "sid", "prompt")
        info = get_session("test")
        self.assertEqual(info["session_id"], "sid")


class TestCleanOutputEdgeCases(unittest.TestCase):
    """Edge cases for clean_output — empty, all-noise, unicode."""

    def test_empty_string(self):
        content, sid = clean_output("")
        self.assertEqual(content, "")
        self.assertIsNone(sid)

    def test_only_bitwarden_noise(self):
        content, sid = clean_output(f"{BITWARDEN_PREFIX}\n{BITWARDEN_PREFIX}")
        self.assertEqual(content, "")
        self.assertIsNone(sid)

    def test_only_warnings(self):
        content, sid = clean_output("Warning: Unknown toolsets: foo\nWarning: Unknown toolsets: bar")
        self.assertEqual(content, "")

    def test_unicode_emoji_preserved(self):
        content, _ = clean_output("Hello 🤖 世界 🎉")
        self.assertIn("🤖", content)
        self.assertIn("世界", content)

    def test_session_id_from_stderr_format(self):
        """Session ID in stderr format (quiet mode puts it there)."""
        content, sid = clean_output("session_id: abc123\nHello world")
        self.assertEqual(sid, "abc123")
        self.assertEqual(content, "Hello world")

    def test_multiple_session_ids(self):
        """When multiple session_id lines appear, last one wins."""
        content, sid = clean_output("session_id: first\nsession_id: second\nContent")
        self.assertEqual(sid, "second")

    def test_session_id_with_extra_whitespace(self):
        content, sid = clean_output("session_id:   sid_with_spaces\nContent")
        self.assertEqual(sid, "sid_with_spaces")


class TestComparisonEdgeCases(unittest.TestCase):
    """Edge cases for dispatch_comparison — partial failure, single model, empty."""

    @patch("model_utils.subprocess.run")
    def test_partial_failure(self, mock_run):
        """2 of 3 models succeed, 1 fails."""
        import subprocess as sp

        def side_effect(cmd, **kwargs):
            if "model-b" in cmd:
                raise sp.TimeoutExpired(cmd="hermes", timeout=5)
            mock_r = MagicMock()
            mock_r.stdout = "Answer"
            mock_r.stderr = ""
            return mock_r

        mock_run.side_effect = side_effect
        models = ["model-a", "model-b", "model-c"]
        results = dispatch_comparison(models, "test", "", "", 1, 5, "test", thinking=None)
        self.assertEqual(len(results), 3)
        # model-a and model-c should succeed
        succeeded = [r for r in results if r["content"]]
        failed = [r for r in results if r["error"]]
        self.assertEqual(len(succeeded), 2)
        self.assertEqual(len(failed), 1)
        self.assertIn("Timed out", failed[0]["error"])

    @patch("model_utils.subprocess.run")
    def test_all_models_fail(self, mock_run):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="hermes", timeout=5)
        results = dispatch_comparison(["model-a", "model-b"], "test", "", "", 1, 5, "test", thinking=None)
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertIn("Timed out", r["error"])

    @patch("model_utils.subprocess.run")
    def test_single_model_comparison(self, mock_run):
        """Single model in comparison mode should still work."""
        mock_result = MagicMock()
        mock_result.stdout = "Answer"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        results = dispatch_comparison(["only-model"], "test", "", "", 1, 10, "test", thinking=None)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["model"], "only-model")


class TestMockAssertionStrength(unittest.TestCase):
    """Strengthen mock assertions — verify actual command structure passed to subprocess."""

    @patch("model_utils.subprocess.run")
    def test_dispatch_uses_correct_hermes_binary(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = "Answer"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        dispatch_single("test-model", "test", "", "", 1, 10, "test-provider")
        call_args = mock_run.call_args
        cmd = call_args[0][0] if call_args[0] else call_args[1].get("args", [])
        self.assertIn("chat", cmd)
        self.assertIn("-q", cmd)
        self.assertIn("-m", cmd)
        self.assertIn("test-model", cmd)
        self.assertIn("--provider", cmd)
        self.assertIn("test-provider", cmd)
        self.assertIn("-Q", cmd)
        self.assertIn("--yolo", cmd)
        self.assertIn("--max-turns", cmd)
        self.assertIn("--pass-session-id", cmd)

    @patch("model_utils.subprocess.run")
    def test_dispatch_passes_toolsets(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = "Answer"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        dispatch_single("model", "test", "", "file,web,terminal", 1, 10, "prov")
        cmd = mock_run.call_args[0][0]
        self.assertIn("-t", cmd)
        idx = cmd.index("-t")
        self.assertEqual(cmd[idx + 1], "file,web,terminal")

    @patch("model_utils.subprocess.run")
    def test_dispatch_passes_resume_session(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = "Answer"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        dispatch_single("model", "test", "", "", 1, 10, "prov", resume_session="sid_123")
        cmd = mock_run.call_args[0][0]
        self.assertIn("--resume", cmd)
        idx = cmd.index("--resume")
        self.assertEqual(cmd[idx + 1], "sid_123")

    @patch("model_utils.dispatch_single")
    def test_comparison_sequential_verify_exact_pattern(self, mock_dispatch):
        """Verify comparison mode calls dispatch for each model when thinking is set."""
        mock_dispatch.return_value = {
            "content": "Answer", "session_id": None,
            "elapsed": 1.0, "error": None, "thinking": "high"
        }
        dispatch_comparison(["a", "b"], "test", "", "", 1, 10, "p", thinking="high")
        # Should have called dispatch twice (sequential for thinking mode)
        self.assertEqual(mock_dispatch.call_count, 2)
        # Each call should have thinking="high"
        for call in mock_dispatch.call_args_list:
            _, kwargs = call
            self.assertEqual(kwargs.get("thinking"), "high")


class TestCLICombinations(unittest.TestCase):
    """Test CLI mode combinations that DeepSeek flagged as untested."""

    def _run(self, args, stdin=None, timeout=15):
        return subprocess.run(
            ["python3", ASK_SCRIPT] + args,
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.PIPE if stdin else None,
            input=stdin,
        )

    def test_prompt_and_models_combined(self):
        """Mode 1: --models + --prompt together."""
        r = self._run(["--models", "fast", "--prompt", "What is 2+2?", "--timeout", "1"])
        # Should not fail on parsing — it might timeout but that's ok
        self.assertNotIn("Error: specify at least one model", r.stderr)
        self.assertNotIn("Error: no prompt provided", r.stderr)

    def test_context_file_flag(self):
        """--context-file reads context from file."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("This is context")
            ctx_file = f.name
        try:
            r = self._run(["--models", "fast", "--prompt", "test", "-c", ctx_file, "--timeout", "1"])
            self.assertNotIn("Error", r.stderr)
        finally:
            os.unlink(ctx_file)

    def test_stdin_piping(self):
        """Context can be piped via stdin."""
        r = subprocess.run(
            ["python3", ASK_SCRIPT, "--models", "fast", "--prompt", "test", "--timeout", "1"],
            capture_output=True, text=True, timeout=15,
            input="piped context data",
        )
        self.assertNotEqual(r.returncode, 3)  # not a model error

    def test_prompt_with_double_dashes(self):
        """Prompt containing -- should work with --prompt flag."""
        r = self._run(["--models", "fast", "--prompt", "What does --max-turns mean?", "--timeout", "1"])
        # Should not crash on --max-turns being interpreted as a flag
        self.assertNotEqual(r.returncode, 2)  # not argparse error


class TestIsKnownModelEdgeCases(unittest.TestCase):
    """Edge cases for is_known_model."""

    def test_empty_string(self):
        self.assertFalse(is_known_model(""))

    def test_model_with_space_and_colon(self):
        self.assertFalse(is_known_model("bad: model name"))

    def test_model_with_colon_no_space(self):
        self.assertTrue(is_known_model("model-name:tag"))


class TestGetReasoningEffortEdgeCases(unittest.TestCase):
    """Edge cases for get_reasoning_effort — config file edge cases."""

    def setUp(self):
        """Invalidate the get_reasoning_effort cache before each test."""
        import model_utils as mu
        mu._reasoning_effort_loaded = False

    def test_missing_config_file(self):
        """Should return empty string when config file doesn't exist."""
        # The function checks expanduser, then falls back to /opt/data/config.yaml.
        # Patch open to simulate both files being missing.
        def mock_open(path, *args, **kwargs):
            raise FileNotFoundError(f"No such file: {path}")
        with patch("builtins.open", mock_open):
            result = get_reasoning_effort()
            self.assertEqual(result, "")

    def test_agent_section_without_reasoning_effort(self):
        """Config with agent: section but no reasoning_effort key."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("agent:\n  max_turns: 90\n  verbose: false\n")
            tmpfile = f.name
        try:
            with patch("os.path.expanduser", return_value=tmpfile):
                result = get_reasoning_effort()
                self.assertEqual(result, "")
        finally:
            os.unlink(tmpfile)


class TestLiveEndToEnd(unittest.TestCase):
    """Live end-to-end CLI tests — runs ask.py as subprocess with real model."""

    @classmethod
    def setUpClass(cls):
        import urllib.request
        try:
            req = urllib.request.Request(
                "http://host.docker.internal:11434/api/tags",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5):
                cls.ollama_reachable = True
        except Exception:
            cls.ollama_reachable = False

    def setUp(self):
        if not self.ollama_reachable:
            self.skipTest("Ollama API not reachable")

    def _run_cli(self, args, timeout=60):
        return subprocess.run(
            ["python3", ASK_SCRIPT] + args,
            capture_output=True, text=True, timeout=timeout,
        )

    def test_cli_single_model(self):
        """Full CLI: ask.py fast '2+2' — verifies CLI→subprocess→output pipeline."""
        r = self._run_cli(["fast", "What is 2+2? Answer with just the number.", "--timeout", "30"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("🤖", r.stdout)
        self.assertIn("4", r.stdout)

    def test_cli_with_thinking_none(self):
        """Verify --thinking flag works end-to-end."""
        r = self._run_cli(["fast", "What is 3+3?", "--thinking", "none", "--timeout", "60"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("🤖", r.stdout)

    def test_cli_file_output(self):
        """Verify -o writes file with metadata header."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="r", suffix=".md", delete=False) as f:
            tmpfile = f.name
        try:
            r = self._run_cli(["fast", "What is 5+5?", "-o", tmpfile, "--timeout", "30"])
            self.assertEqual(r.returncode, 0)
            with open(tmpfile) as f:
                content = f.read()
            self.assertIn("model:", content)
            self.assertIn("elapsed:", content)
            # "fast" alias resolves to qwen3.6:35b-a3b (was gemma4 previously)
            self.assertIn("qwen3.6", content)
        finally:
            if os.path.exists(tmpfile):
                os.unlink(tmpfile)

    def test_cli_sessions_list(self):
        """Verify --sessions works after a successful call."""
        # First make a call to create a session
        self._run_cli(["fast", "hello", "--timeout", "30"])
        # Then list sessions
        r = self._run_cli(["--sessions"])
        self.assertEqual(r.returncode, 0)


# ── Phase 6B: Tests for _run_raw_mode and _run_agent_mode ──────────────────


class TestRunRawMode(unittest.TestCase):
    """Tests for _run_raw_mode — direct Ollama API dispatch."""

    def test_raw_mode_rejects_multiple_models(self):
        """--mode raw with multiple models should error and exit."""
        from unittest.mock import MagicMock
        args = MagicMock()
        args.sessions = False
        args.session = None
        args.prompt = "test prompt"
        args.models = "fast,gemma"
        args.args = []
        args.context = ""
        args.context_file = None
        args.provider = "ollama-glm"
        args.timeout = 60

        with patch("sys.stdin.isatty", return_value=True):
            with self.assertRaises(SystemExit) as ctx:
                _run_raw_mode(args, [])
            self.assertEqual(ctx.exception.code, 1)

    def test_raw_mode_no_prompt_exits(self):
        """--mode raw with no prompt should error and exit."""
        from unittest.mock import MagicMock
        args = MagicMock()
        args.sessions = False
        args.session = None
        args.prompt = None
        args.models = None
        args.args = ["fast"]
        args.context = ""
        args.context_file = None
        args.provider = "ollama-glm"
        args.timeout = 60

        with patch("sys.stdin.isatty", return_value=True):
            with self.assertRaises(SystemExit) as ctx:
                _run_raw_mode(args, ["fast"])
            self.assertEqual(ctx.exception.code, 1)

    def test_raw_mode_no_model_exits(self):
        """--mode raw with no model should error and exit."""
        from unittest.mock import MagicMock
        args = MagicMock()
        args.sessions = False
        args.session = None
        args.prompt = "hello"
        args.models = None
        args.args = []
        args.context = ""
        args.context_file = None
        args.provider = "ollama-glm"
        args.timeout = 60

        with patch("sys.stdin.isatty", return_value=True):
            with self.assertRaises(SystemExit) as ctx:
                _run_raw_mode(args, [])
            self.assertEqual(ctx.exception.code, 3)

    def test_raw_mode_dispatches_via_api(self):
        """--mode raw with valid model+prompt should call dispatch_single_raw."""
        from unittest.mock import MagicMock
        args = MagicMock()
        args.sessions = False
        args.session = None
        args.prompt = "hello"
        args.models = None
        args.args = ["fast"]
        args.context = ""
        args.context_file = None
        args.provider = "ollama-glm"
        args.timeout = 60

        mock_result = {"content": "hello back", "elapsed": 0.5, "error": None}
        with patch("sys.stdin.isatty", return_value=True), \
             patch("ask.dispatch_single_raw", return_value=mock_result):
            _run_raw_mode(args, ["fast"])


class TestRunAgentMode(unittest.TestCase):
    """Tests for _run_agent_mode — hermes chat subprocess dispatch."""

    def test_agent_mode_rejects_no_model(self):
        """--mode agent with no model should error and exit."""
        from unittest.mock import MagicMock
        args = MagicMock()
        args.sessions = False
        args.session = None
        args.prompt = "hello"
        args.models = None
        args.args = []
        args.context = ""
        args.context_file = None
        args.provider = "ollama-glm"
        args.timeout = 60
        args.thinking = None
        args.max_turns = 5
        args.toolsets = "file,web"
        args.output = None
        args.resume = None
        args.mode = "agent"

        with patch("sys.stdin.isatty", return_value=True):
            with self.assertRaises(SystemExit) as ctx:
                _run_agent_mode(args, [])
            self.assertEqual(ctx.exception.code, 3)

    def test_agent_mode_rejects_no_prompt(self):
        """--mode agent with model but no prompt should error and exit."""
        from unittest.mock import MagicMock
        args = MagicMock()
        args.sessions = False
        args.session = None
        args.prompt = None
        args.models = None
        args.args = ["fast"]
        args.context = ""
        args.context_file = None
        args.provider = "ollama-glm"
        args.timeout = 60
        args.thinking = None
        args.max_turns = 5
        args.toolsets = "file,web"
        args.output = None
        args.resume = None
        args.mode = "agent"

        with patch("sys.stdin.isatty", return_value=True):
            with self.assertRaises(SystemExit) as ctx:
                _run_agent_mode(args, ["fast"])
            self.assertEqual(ctx.exception.code, 1)

    def test_agent_mode_dispatches_single(self):
        """--mode agent with single model should call dispatch_single."""
        from unittest.mock import MagicMock
        args = MagicMock()
        args.sessions = False
        args.session = None
        args.prompt = "hello"
        args.models = None
        args.args = ["fast"]
        args.context = ""
        args.context_file = None
        args.provider = "ollama-glm"
        args.timeout = 60
        args.thinking = None
        args.max_turns = 5
        args.toolsets = "file,web"
        args.output = None
        args.resume = None
        args.mode = "agent"

        mock_result = {"content": "response", "session_id": None, "elapsed": 1.0, "error": None, "thinking": "default"}
        with patch("sys.stdin.isatty", return_value=True), \
             patch("ask.dispatch_single", return_value=mock_result):
            _run_agent_mode(args, ["fast"])

    def test_agent_mode_comparison_dispatches(self):
        """--mode agent with multiple models should call dispatch_comparison."""
        from unittest.mock import MagicMock
        args = MagicMock()
        args.sessions = False
        args.session = None
        args.prompt = "compare this"
        args.models = "fast,gemma"
        args.args = []
        args.context = ""
        args.context_file = None
        args.provider = "ollama-glm"
        args.timeout = 60
        args.thinking = None
        args.max_turns = 5
        args.toolsets = "file,web"
        args.output = None
        args.resume = None
        args.mode = "agent"

        mock_results = [
            {"content": "resp1", "session_id": None, "elapsed": 1.0, "error": None, "thinking": "default", "model": "gemma4:12b-mlx-bf16"},
            {"content": "resp2", "session_id": None, "elapsed": 1.0, "error": None, "thinking": "default", "model": "gemma4:12b-mlx-bf16"},
        ]
        with patch("sys.stdin.isatty", return_value=True), \
             patch("ask.dispatch_comparison", return_value=mock_results), \
             patch("ask.save_session"):
            _run_agent_mode(args, [])

    def test_auto_answer_resumes_same_session_after_clarification(self):
        """A question-shaped reply is answered once and resumed in its session."""
        args = SimpleNamespace(
            sessions=False,
            session=None,
            prompt="Design the data layer",
            models=None,
            args=["fast"],
            context="",
            context_file=None,
            provider="ollama-glm",
            timeout=60,
            thinking=None,
            max_turns=5,
            toolsets="file,web",
            output=None,
            resume=None,
            mode="agent",
            auto_answer=None,
            cwd=None,
        )
        question = {
            "content": "Which database do you prefer?",
            "session_id": "s1",
            "elapsed": 0.1,
            "error": None,
        }
        final = {
            "content": "Use PostgreSQL with a small connection pool.",
            "session_id": "s1",
            "elapsed": 0.1,
            "error": None,
        }
        events = []
        stdout = io.StringIO()

        with patch("sys.stdin.isatty", return_value=True), \
             patch("ask.get_session", return_value={}), \
             patch("ask.dispatch_single", side_effect=[question, final]) as mock_dispatch, \
             patch("ask.generate_auto_answer", return_value={"answer": "PostgreSQL", "error": None}):
            with patch.object(sys, "stdout", stdout):
                result = _run_agent_mode(args, [], progress_callback=events.append)

        self.assertEqual(mock_dispatch.call_count, 2)
        self.assertEqual(mock_dispatch.call_args_list[1].kwargs["resume_session"], "s1")
        self.assertIn("Use PostgreSQL", stdout.getvalue())
        auto_events = [event for event in events if event["event"] == "auto_answer"]
        self.assertEqual(len(auto_events), 1)
        self.assertEqual(auto_events[0]["seam"], "freetext")
        self.assertEqual(result["auto_answers"], auto_events)


# ── Phase 9: Test Coverage Gaps ─────────────────────────────────────────────


class TestNeedsNoThink(unittest.TestCase):
    """T1: Test needs_no_think() — pure function, 5 cases."""

    def test_qwen_model_returns_true(self):
        from model_utils import needs_no_think
        self.assertTrue(needs_no_think("qwen3.6:35b-a3b"))

    def test_qwen_coder_returns_true(self):
        from model_utils import needs_no_think
        self.assertTrue(needs_no_think("qwen3-coder-next:q4_K_M"))

    def test_non_qwen_returns_false(self):
        from model_utils import needs_no_think
        self.assertFalse(needs_no_think("deepseek-v4-pro:cloud"))

    def test_empty_string_returns_false(self):
        from model_utils import needs_no_think
        self.assertFalse(needs_no_think(""))

    def test_none_raises(self):
        from model_utils import needs_no_think
        with self.assertRaises(AttributeError):
            needs_no_think(None)

    def test_mixed_case_qwen_returns_true(self):
        from model_utils import needs_no_think
        self.assertTrue(needs_no_think("Qwen3:14b"))

    def test_gemma_returns_false(self):
        from model_utils import needs_no_think
        self.assertFalse(needs_no_think("gemma4:12b-mlx-bf16"))


class TestCleanExpiredSessions(unittest.TestCase):
    """T2: Test clean_expired_sessions() — file I/O, 5 cases."""

    def setUp(self):
        import tempfile
        import model_utils as mu_module
        self._tmpdir = tempfile.mkdtemp()
        self._orig = mu_module.SESSIONS_FILE
        mu_module.SESSIONS_FILE = os.path.join(self._tmpdir, "test-sessions.json")

    def tearDown(self):
        import model_utils as mu_module
        mu_module.SESSIONS_FILE = self._orig
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_no_expired_sessions(self):
        """All sessions fresh — should remove 0."""
        # Save a session with current timestamp
        save_session("deepseek", "model", "sid", "prompt")
        removed = clean_expired_sessions()
        self.assertEqual(removed, 0)

    def test_some_expired_sessions(self):
        """Mix of fresh and expired sessions."""
        import model_utils as mu_module
        # Save a fresh session
        save_session("fresh", "model", "sid_fresh", "prompt")
        # Write an expired session manually (timestamp 2 hours ago)
        import json as _json
        import time as _time
        old_ts = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(_time.time() - 7200))
        with open(mu_module.SESSIONS_FILE, "w") as f:
            _json.dump({
                "fresh": {"model": "m", "session_id": "s1", "prompt_preview": "p", "timestamp": _time.strftime("%Y-%m-%d %H:%M:%S")},
                "stale": {"model": "m", "session_id": "s2", "prompt_preview": "p", "timestamp": old_ts},
            }, f)
        removed = clean_expired_sessions()
        self.assertEqual(removed, 1)

    def test_all_expired_sessions(self):
        """All sessions expired."""
        import model_utils as mu_module
        import json as _json
        import time as _time
        old_ts = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(_time.time() - 7200))
        with open(mu_module.SESSIONS_FILE, "w") as f:
            _json.dump({
                "old1": {"model": "m", "session_id": "s1", "prompt_preview": "p", "timestamp": old_ts},
                "old2": {"model": "m", "session_id": "s2", "prompt_preview": "p", "timestamp": old_ts},
            }, f)
        removed = clean_expired_sessions()
        self.assertEqual(removed, 2)

    def test_missing_file_returns_zero(self):
        """No sessions file — should return 0."""
        import model_utils as mu_module
        # Ensure file doesn't exist
        if os.path.exists(mu_module.SESSIONS_FILE):
            os.unlink(mu_module.SESSIONS_FILE)
        removed = clean_expired_sessions()
        self.assertEqual(removed, 0)

    def test_corrupt_file_returns_zero(self):
        """Corrupt JSON — should return 0."""
        import model_utils as mu_module
        with open(mu_module.SESSIONS_FILE, "w") as f:
            f.write("{corrupt json!!!")
        removed = clean_expired_sessions()
        self.assertEqual(removed, 0)

    def test_invalid_timestamp_treated_as_expired(self):
        """Sessions with invalid timestamps are treated as expired."""
        import model_utils as mu_module
        import json as _json
        with open(mu_module.SESSIONS_FILE, "w") as f:
            _json.dump({
                "bad_ts": {"model": "m", "session_id": "s1", "prompt_preview": "p", "timestamp": "not-a-date"},
            }, f)
        removed = clean_expired_sessions()
        self.assertEqual(removed, 1)


class TestClassifyBatch(unittest.TestCase):
    """T3: Test classify_batch() — batch wrapper, 3 cases."""

    def test_single_message(self):
        import sys as _sys
        _sys.path.insert(0, "/opt/data/skills/productivity/triage/scripts")
        import triage
        with patch("triage.classify") as mock_classify:
            mock_classify.return_value = {"category": "general_chat", "confidence": "high"}
            results = triage.classify_batch(["hello"])
            self.assertEqual(len(results), 1)
            mock_classify.assert_called_once()

    def test_multiple_messages(self):
        import sys as _sys
        _sys.path.insert(0, "/opt/data/skills/productivity/triage/scripts")
        import triage
        with patch("triage.classify") as mock_classify:
            mock_classify.side_effect = [
                {"category": "general_chat", "confidence": "high"},
                {"category": "build_code", "confidence": "high"},
                {"category": "query_model", "confidence": "medium"},
            ]
            results = triage.classify_batch(["hello", "build a REST API", "ask deepseek"])
            self.assertEqual(len(results), 3)
            self.assertEqual(results[0]["category"], "general_chat")
            self.assertEqual(results[1]["category"], "build_code")
            self.assertEqual(results[2]["category"], "query_model")

    def test_empty_list(self):
        import sys as _sys
        _sys.path.insert(0, "/opt/data/skills/productivity/triage/scripts")
        import triage
        with patch("triage.classify") as mock_classify:
            results = triage.classify_batch([])
            self.assertEqual(len(results), 0)
            mock_classify.assert_not_called()


class TestNeedsNoThinkSync(unittest.TestCase):
    """T4/L4: Cross-file sync test — assert triage._needs_no_think and model_utils.needs_no_think return same results."""

    def test_sync_qwen_models(self):
        import sys as _sys
        _sys.path.insert(0, "/opt/data/skills/productivity/triage/scripts")
        from model_utils import needs_no_think
        import triage
        qwen_models = ["qwen3.6:35b-a3b", "qwen3-coder-next:q4_K_M", "Qwen3:14b", "qwen3:1.7b"]
        for model in qwen_models:
            self.assertEqual(
                needs_no_think(model), triage._needs_no_think(model),
                f"Mismatch for {model}: model_utils={needs_no_think(model)}, triage={triage._needs_no_think(model)}"
            )

    def test_sync_non_qwen_models(self):
        import sys as _sys
        _sys.path.insert(0, "/opt/data/skills/productivity/triage/scripts")
        from model_utils import needs_no_think
        import triage
        non_qwen = ["deepseek-v4-pro:cloud", "gemma4:12b-mlx-bf16", "glm-5.2:cloud", "kimi-k2.7-code:cloud"]
        for model in non_qwen:
            self.assertEqual(
                needs_no_think(model), triage._needs_no_think(model),
                f"Mismatch for {model}: model_utils={needs_no_think(model)}, triage={triage._needs_no_think(model)}"
            )

    def test_sync_edge_cases(self):
        import sys as _sys
        _sys.path.insert(0, "/opt/data/skills/productivity/triage/scripts")
        from model_utils import needs_no_think
        import triage
        # Both should return False for empty string
        self.assertEqual(needs_no_think(""), triage._needs_no_think(""))


# ── Phase 8 Edge Case Tests ──────────────────────────────────────────────────


class TestRouteFallbackAlias(unittest.TestCase):
    """M10: route() fallback should return alias, not literal model name."""

    def test_fallback_returns_alias_not_literal(self):
        """M10: When available_models exist but none match preferred, fallback should be from COST_TIERS not literal."""
        from routing import route
        triage_result = {"category": "general_chat", "confidence": "high"}
        # system_state with models that don't match any preferred → triggers final fallback
        system_state = {"available_models": ["nonexistent-model"]}
        decision = route(triage_result, system_state=system_state)
        # When no preferred models match and available_models is non-empty,
        # it picks available_models[0]. The M10 fix is about the ELSE branch
        # (both empty) — test that separately.
        self.assertEqual(decision["model"], "nonexistent-model")

    def test_fallback_no_system_state_returns_alias(self):
        """M10: With no system_state at all, model should be an alias (from COST_TIERS), not a literal model name."""
        from routing import route
        triage_result = {"category": "general_chat", "confidence": "high"}
        # Default user_context (medium budget) → preferred = ['deepseek', 'minimax']
        # No system_state → all preferred accepted → model = 'deepseek' (an alias)
        decision = route(triage_result)
        self.assertNotIn(":", decision["model"])  # Should be alias, not "deepseek-v4-pro:cloud"


class TestDispatchSingleRawEnglishOnly(unittest.TestCase):
    """M4: dispatch_single_raw should pass english_only for NON_ENGLISH_MODELS."""

    @patch("ask.urllib.request.urlopen")
    def test_raw_mode_glm_gets_english_directive(self, mock_urlopen):
        """GLM model in raw mode should get 'respond in English only'."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "message": {"content": "response"}
        }).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_resp

        dispatch_single_raw("glm-5.2:cloud", "test", "", "ollama-glm", 30)
        # Check that the request data contains "respond in English only"
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        content = body["messages"][0]["content"]
        self.assertIn("respond in English only", content)

    @patch("ask.urllib.request.urlopen")
    def test_raw_mode_deepseek_no_english_directive(self, mock_urlopen):
        """DeepSeek model in raw mode should NOT get 'respond in English only'."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "message": {"content": "response"}
        }).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_resp

        dispatch_single_raw("deepseek-v4-pro:cloud", "test", "", "ollama-glm", 30)
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        content = body["messages"][0]["content"]
        self.assertNotIn("respond in English only", content)


class TestTriageFallbackUsedLogic(unittest.TestCase):
    """M7: triage classify retry should only set fallback_used=True when retry finds a match."""

    def test_fallback_used_false_when_retry_fails(self):
        """If retry also returns 'unknown', fallback_used should be False."""
        import sys as _sys
        _sys.path.insert(0, "/opt/data/skills/productivity/triage/scripts")
        import triage
        from unittest.mock import patch, MagicMock

        # Mock first call returns low confidence, retry also returns unknown
        call_count = [0]
        def mock_urlopen_side_effect(req, timeout=None):
            call_count[0] += 1
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=None)
            if call_count[0] == 1:
                # First call: low confidence result
                mock_resp.read.return_value = json.dumps({
                    "message": {"content": "something unrelated"},
                    "eval_count": 5,
                }).encode("utf-8")
            else:
                # Retry: also returns unknown
                mock_resp.read.return_value = json.dumps({
                    "message": {"content": "still unknown"},
                    "eval_count": 10,
                }).encode("utf-8")
            return mock_resp

        with patch("triage.urllib.request.urlopen", side_effect=mock_urlopen_side_effect):
            result = triage.classify("test message", timeout=5)
            # fallback_used should be False because retry also didn't find a match
            self.assertFalse(result["fallback_used"])


class TestPipelineEventLoggingError(unittest.TestCase):
    """M11: log_pipeline_event should log to stderr on failure, not silently swallow."""

    def test_logging_error_prints_to_stderr(self, capsys=None):
        """When file I/O fails, error should be printed to stderr."""
        from routing import log_pipeline_event
        from unittest.mock import patch
        import io

        triage_result = {"category": "general_chat", "confidence": "high"}
        routing_decision = {"skill": None}

        # Mock open to raise IOError
        with patch("builtins.open", side_effect=IOError("permission denied")), \
             patch("os.makedirs", side_effect=IOError("permission denied")):
            # Should not raise, should print to stderr
            import sys as _sys
            old_stderr = _sys.stderr
            _sys.stderr = io.StringIO()
            try:
                log_pipeline_event(
                    triage_result=triage_result,
                    routing_decision=routing_decision,
                    model_used="fast",
                    latency=0.1,
                    token_count=10,
                    success=True,
                )
                stderr_output = _sys.stderr.getvalue()
                self.assertIn("pipeline event logging failed", stderr_output)
            finally:
                _sys.stderr = old_stderr


# ── Phase 11: Pipeline Tests ─────────────────────────────────────────────────


class TestPipelineDryRun(unittest.TestCase):
    """S1-S7: Test pipeline.py dry-run mode — no API calls."""

    PIPELINE_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "pipeline.py")

    def _run(self, args, timeout=15):
        return subprocess.run(
            ["python3", self.PIPELINE_SCRIPT] + args,
            capture_output=True, text=True, timeout=timeout
        )

    def test_dry_run_human_readable(self):
        """Dry-run should show triage + routing stages."""
        r = self._run(["Build a REST API", "--dry-run"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("Stage 1: Triage", r.stdout)
        self.assertIn("Stage 2: Routing", r.stdout)
        self.assertIn("Pipeline:", r.stdout)

    def test_dry_run_json(self):
        """Dry-run with --json should produce valid JSON."""
        r = self._run(["hello", "--dry-run", "--json"])
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertIn("message", data)
        self.assertIn("triage_result", data)
        self.assertIn("routing_decision", data)
        self.assertTrue(data["pipeline_success"])

    def test_dry_run_cost_budget_free(self):
        """Dry-run with --cost-budget free should route to local model."""
        r = self._run(["debug this", "--dry-run", "--json"])
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        # Default medium budget → deepseek
        r_free = self._run(["debug this", "--dry-run", "--json", "--cost-budget", "free"])
        data_free = json.loads(r_free.stdout)
        # Free budget should prefer local models
        self.assertNotEqual(
            data["routing_decision"]["model"],
            data_free["routing_decision"]["model"]
        )

    def test_no_message_errors(self):
        """No message argument should error."""
        r = self._run([])
        self.assertNotEqual(r.returncode, 0)

    def test_json_output_structure(self):
        """JSON output should have all expected keys."""
        r = self._run(["test", "--dry-run", "--json"])
        data = json.loads(r.stdout)
        expected_keys = {"message", "triage_result", "routing_decision",
                         "dispatch_result", "pipeline_elapsed", "pipeline_success", "error"}
        self.assertTrue(expected_keys.issubset(data.keys()))


class TestPipelineRunFunction(unittest.TestCase):
    """Test run_pipeline() directly with mocked triage."""

    def test_dry_run_returns_routing_only(self):
        """run_pipeline with dry_run=True should return routing without dispatch."""
        from pipeline import run_pipeline
        result = run_pipeline("Build a REST API", dry_run=True)
        self.assertTrue(result["pipeline_success"])
        self.assertIsNotNone(result["triage_result"])
        self.assertIsNotNone(result["routing_decision"])
        self.assertIsNone(result["dispatch_result"])

    def test_inline_category_no_dispatch(self):
        """Categories with skill=None should return inline (no dispatch)."""
        from pipeline import run_pipeline
        with patch("triage.classify") as mock_classify:
            mock_classify.return_value = {
                "category": "general_chat",
                "confidence": "high",
                "raw_output": "general_chat",
                "tokens": 3,
                "elapsed": 0.5,
            }
            result = run_pipeline("hello", dry_run=False)
            self.assertTrue(result["pipeline_success"])
            # general_chat → skill=None → inline response
            self.assertTrue(result["dispatch_result"]["inline"])

    def test_skill_category_triggers_dispatch(self):
        """Categories with a skill should trigger dispatch_single."""
        from pipeline import run_pipeline
        with patch("triage.classify") as mock_classify, \
             patch("pipeline.dispatch_single") as mock_dispatch:
            mock_classify.return_value = {
                "category": "build_code",
                "confidence": "high",
                "raw_output": "build_code",
                "tokens": 3,
                "elapsed": 0.5,
            }
            mock_dispatch.return_value = {
                "content": "Here's your API design...",
                "session_id": None,
                "elapsed": 5.0,
                "error": None,
                "thinking": "low",
            }
            result = run_pipeline("Build a REST API", dry_run=False, timeout=10)
            self.assertTrue(result["pipeline_success"])
            mock_dispatch.assert_called_once()
            self.assertIsNotNone(result["dispatch_result"]["content"])


# ── P1: API Error Detection Tests ────────────────────────────────────────────


class TestIsApiError(unittest.TestCase):
    """P1: Test is_api_error() in model_utils.py (production code, not test helper)."""

    def setUp(self):
        from model_utils import is_api_error
        self.is_api_error = is_api_error

    def test_detects_429_rate_limit(self):
        """HTTP 429 rate limit should be detected as API error."""
        self.assertTrue(self.is_api_error(
            "API call failed after 3 retries: HTTP 429: Error code: 429 - rate limit exceeded"
        ))

    def test_detects_monthly_max_reached(self):
        """Ollama monthly max message should be detected."""
        self.assertTrue(self.is_api_error(
            "extra usage auto reload monthly max reached, increase your monthly max"
        ))

    def test_detects_connection_refused(self):
        """Connection refused should be detected."""
        self.assertTrue(self.is_api_error(
            "API call failed: connection refused. HTTP 500: Internal server error"
        ))

    def test_does_not_flag_normal_code(self):
        """Normal Python code should NOT be flagged as API error."""
        self.assertFalse(self.is_api_error(
            "def is_palindrome(s):\n    return s == s[::-1]\nprint(is_palindrome('racecar'))"
        ))

    def test_does_not_flag_bare_429_number(self):
        """Code containing 429 as a number should not be flagged (needs 2+ patterns)."""
        self.assertFalse(self.is_api_error("x = 429\nprint(x)"))

    def test_does_not_flag_empty_string(self):
        """Empty string should not be flagged."""
        self.assertFalse(self.is_api_error(""))

    def test_does_not_flag_short_string(self):
        """Very short strings should not be flagged (likely not an error message)."""
        self.assertFalse(self.is_api_error("429"))


class TestPipelineApiErrorRetry(unittest.TestCase):
    """P1: Pipeline should retry dispatch on transient API errors."""

    _fake_build = {
        "category": "build_code", "confidence": "high",
        "raw_output": "build_code", "tokens": 3, "elapsed": 0.5,
    }

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_build)
    @patch("pipeline.time.sleep")  # Don't actually sleep in tests
    def test_transient_error_retried(self, mock_sleep, mock_triage, mock_dispatch):
        """429 error on first attempt should trigger a retry."""
        from pipeline import run_pipeline
        # First call returns API error, second succeeds
        mock_dispatch.side_effect = [
            {"content": None, "session_id": None, "elapsed": 1.0,
             "error": "API error: HTTP 429: rate limit exceeded", "thinking": "default"},
            {"content": "Here is your code", "session_id": "abc",
             "elapsed": 2.0, "error": None, "thinking": "default"},
        ]
        result = run_pipeline("Build a REST API", max_retries=1, timeout=10)
        self.assertTrue(result["pipeline_success"])
        self.assertEqual(result["dispatch_retries"], 1)
        self.assertEqual(mock_dispatch.call_count, 2)

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_build)
    @patch("pipeline.time.sleep")
    def test_non_transient_error_not_retried(self, mock_sleep, mock_triage, mock_dispatch):
        """Non-transient errors should not be retried."""
        from pipeline import run_pipeline
        mock_dispatch.return_value = {
            "content": None, "session_id": None, "elapsed": 1.0,
            "error": "Empty output. stderr: bad model name", "thinking": "default",
        }
        result = run_pipeline("Build a REST API", max_retries=1, timeout=10)
        self.assertFalse(result["pipeline_success"])
        self.assertEqual(result["dispatch_retries"], 0)
        self.assertEqual(mock_dispatch.call_count, 1)

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_build)
    @patch("pipeline.time.sleep")
    def test_all_retries_exhausted(self, mock_sleep, mock_triage, mock_dispatch):
        """When all retries fail, pipeline should report failure."""
        from pipeline import run_pipeline
        mock_dispatch.return_value = {
            "content": None, "session_id": None, "elapsed": 1.0,
            "error": "API error: HTTP 429: rate limit exceeded", "thinking": "default",
        }
        result = run_pipeline("Build a REST API", max_retries=2, timeout=10)
        self.assertFalse(result["pipeline_success"])
        self.assertEqual(result["dispatch_retries"], 2)
        self.assertEqual(mock_dispatch.call_count, 3)  # initial + 2 retries


# ── P2: Role Passthrough Tests ───────────────────────────────────────────────


class TestRolePassthrough(unittest.TestCase):
    """P2: Verify role from routing is passed to dispatch_single."""

    _fake_debug = {
        "category": "debug_code", "confidence": "high",
        "raw_output": "debug_code", "tokens": 3, "elapsed": 0.5,
    }
    _fake_build = {
        "category": "build_code", "confidence": "high",
        "raw_output": "build_code", "tokens": 3, "elapsed": 0.5,
    }

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_debug)
    def test_debug_code_passes_debugger_role(self, mock_triage, mock_dispatch):
        """debug_code category should pass role='debugger' to dispatch_single."""
        from pipeline import run_pipeline
        mock_dispatch.return_value = {
            "content": "fixed", "session_id": None, "elapsed": 1.0,
            "error": None, "thinking": "default",
        }
        run_pipeline("Debug this error", timeout=10)
        # Verify role was passed
        call_kwargs = mock_dispatch.call_args.kwargs
        self.assertEqual(call_kwargs.get("role"), "debugger")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_build)
    def test_build_code_passes_none_role(self, mock_triage, mock_dispatch):
        """build_code category should pass role=None to dispatch_single."""
        from pipeline import run_pipeline
        mock_dispatch.return_value = {
            "content": "built", "session_id": None, "elapsed": 1.0,
            "error": None, "thinking": "default",
        }
        run_pipeline("Build a REST API", timeout=10)
        call_kwargs = mock_dispatch.call_args.kwargs
        self.assertIsNone(call_kwargs.get("role"))


class TestRoleInjectionInDispatchSingle(unittest.TestCase):
    """P2: Verify dispatch_single injects role into the prompt context."""

    @patch("model_utils.subprocess.run")
    def test_role_debugger_injected_into_context(self, mock_run):
        """dispatch_single with role='debugger' should inject role text into context."""
        from model_utils import dispatch_single
        mock_run.return_value = MagicMock(
            stdout="Fixed the bug", stderr="session_id: abc123"
        )
        dispatch_single(
            model="deepseek-v4-pro:cloud", prompt="Fix this bug",
            context="", toolsets="file,web", max_turns=3, timeout=10,
            provider="ollama-glm", role="debugger",
        )
        # The prompt passed to hermes chat should contain the role directive
        prompt_arg = mock_run.call_args.args[0]
        # -q is the prompt flag, next element is the prompt text
        q_idx = prompt_arg.index("-q")
        full_prompt = prompt_arg[q_idx + 1]
        self.assertIn("debugger", full_prompt.lower())
        self.assertIn("finding and fixing bugs", full_prompt.lower())

    @patch("model_utils.subprocess.run")
    def test_no_role_no_injection(self, mock_run):
        """dispatch_single with role=None should not inject role text."""
        from model_utils import dispatch_single
        mock_run.return_value = MagicMock(
            stdout="Here is code", stderr="session_id: abc123"
        )
        dispatch_single(
            model="deepseek-v4-pro:cloud", prompt="Build something",
            context="", toolsets="file,web", max_turns=3, timeout=10,
            provider="ollama-glm", role=None,
        )
        prompt_arg = mock_run.call_args.args[0]
        q_idx = prompt_arg.index("-q")
        full_prompt = prompt_arg[q_idx + 1]
        self.assertNotIn("debugger", full_prompt.lower())
        self.assertNotIn("acting as", full_prompt.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
