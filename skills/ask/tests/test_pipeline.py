#!/usr/bin/env python3
"""test_pipeline — SDLC pipeline integration tests.

Validates the full chain: triage → routing → dispatch → output.
Tests that a user can state an idea and the pipeline opaquely routes it
through the SDLC to produce working code (or a correct response).

## Test Execution

### CI (always, ~2s):
    cd /opt/data/skills/productivity/ask
    uv run --with pytest python3 -m pytest tests/test_pipeline.py -v

### Live (opt-in, ~2min, requires Ollama + Hermes):
    RUN_LIVE_PIPELINE=1 uv run --with pytest python3 -m pytest tests/test_pipeline.py::TestPipelineDispatchLive -v

## Test Matrix

| Class                  | Triage  | Routing | Dispatch  | CI? |
|------------------------|---------|---------|-----------|------|
| TriageRoutingChain     | Mocked  | Real    | Skipped   | ✅   |
| DispatchMocked         | Mocked  | Real    | Mocked    | ✅   |
| DispatchLive           | Real    | Real    | Real      | ⚡   |
| CostBudgets            | Mocked  | Real    | Mocked    | ✅   |
| ErrorPaths             | Mocked  | Real    | Mocked    | ✅   |
| CLIAndOutput           | Subproc | Real    | Skipped   | ✅   |
| EventLogging           | Mocked  | Real    | Mocked    | ✅   |
| EdgeCases              | Mocked  | Real    | Mocked    | ✅   |
"""

import inspect
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch, MagicMock

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
TRIAGE_SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "triage", "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, TRIAGE_SCRIPTS)

import pipeline  # noqa: E402
import model_utils  # noqa: E402
from routing import route, ROUTING_TABLE  # noqa: E402
from model_utils import dispatch_single, dispatch_comparison  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_triage(category, confidence="high", exact=True):
    """Return a canned triage result dict in the shape pipeline.py expects."""
    return {
        "category": category,
        "confidence": confidence,
        "raw_output": category if exact else f"maybe {category}",
        "tokens": 3,
        "elapsed": 0.4,
        "elapsed_first": 0.4,
        "elapsed_retry": 0.0,
        "exact_match": exact,
        "model": "gemma4:12b-mlx-bf16",
        "fallback_used": False,
    }


def _fake_dispatch(content="Here is your response.", elapsed=1.2, error=None):
    """Return a canned dispatch_single result."""
    return {
        "content": content,
        "session_id": None,
        "elapsed": elapsed,
        "error": error,
        "thinking": "default",
    }


# Disable the devloop SDLC engine for non-live tests. When build_code/debug_code route to devloop,
# the pipeline calls devloop_bridge.run_build/run_debug — real multi-phase orchestration that would
# make real model calls. Use the operator KILL-SWITCH (DEVLOOP_ENABLED=0) — the one intentional
# single-dispatch fallback. Do NOT null pipeline.devloop_bridge: bridge-is-None now means
# "import broke" and FAILS CLOSED (fail-closed three-way split, deep review 2026-07-01) instead of
# silently degrading. Live tests (TestPipelineDispatchLive) re-enable for real E2E testing.
import os as _os  # noqa: E402
_orig_devloop_enabled = _os.environ.get('DEVLOOP_ENABLED')
_os.environ['DEVLOOP_ENABLED'] = '0'


# Realistic messages for each of the 11 triage categories
CATEGORY_MESSAGES = {
    "query_model": "ask deepseek what is ACID compliance?",
    "build_code": "Build a REST API with FastAPI and PostgreSQL",
    "debug_code": "Debug this TypeError: expected str, got NoneType on line 47",
    "research_info": "Research ORM options for Python",
    "urgent_action": "URGENT: production is down, users can't log in!",
    "general_chat": "hello",
    "deploy_code": "Deploy to staging and promote to production",
    "write_docs": "Write README for the API module",
    "config_change": "Update the config timeout value to 30s",
    "status_check": "Is the server up?",
    "explain_concept": "What is ACID compliance?",
}

# Expected routing decisions per category (with confidence=high)
EXPECTED_ROUTING = {
    "query_model":    {"skill": "ask",      "toolsets": "file,web",         "role": None},
    "build_code":     {"skill": "dev",       "toolsets": "file,web,terminal", "role": None},
    "debug_code":     {"skill": "dev",       "toolsets": "file,web,terminal", "role": "debugger"},
    "research_info":  {"skill": "advisors",  "toolsets": "file,web",         "role": None},
    "urgent_action":  {"skill": None,        "toolsets": None,               "role": None},
    "general_chat":   {"skill": None,        "toolsets": None,               "role": None},
    "deploy_code":    {"skill": "dev",       "toolsets": "file,web,terminal", "role": None},
    "write_docs":     {"skill": "dev",       "toolsets": "file,web",         "role": None},
    "config_change":  {"skill": "dev",       "toolsets": "file,terminal",     "role": None},
    "status_check":   {"skill": None,        "toolsets": None,               "role": None},
    "explain_concept": {"skill": "ask",      "toolsets": "file,web",         "role": None},
}

# Expected thinking level per category with confidence=high
# general_chat → 'minimal'; query_model or confidence high → 'low'; else → 'medium'
EXPECTED_THINKING_HIGH_CONF = {
    "query_model": "low",
    "build_code": "low",
    "debug_code": "low",
    "research_info": "low",
    "urgent_action": "low",
    "general_chat": "minimal",
    "deploy_code": "low",
    "write_docs": "low",
    "config_change": "low",
    "status_check": "low",
    "explain_concept": "low",
}

# Expected model per cost budget (medium budget → first in COST_TIERS['medium'])
EXPECTED_MODEL_MEDIUM = "deepseek"  # COST_TIERS['medium'][0]


# ── Test Class 1: Triage → Routing Chain (all 11 categories) ─────────────────

class TestPipelineTriageRoutingChain(unittest.TestCase):
    """Verify triage → routing produces correct skill/model/thinking for all 11 categories.

    Mocks triage.classify, lets routing.route run for real, skips dispatch (dry_run=True).
    This validates that every category maps to the expected skill, toolsets, role, and thinking.
    """

    def _run_with_category(self, category, confidence="high"):
        """Run pipeline with a mocked triage returning the given category.

        Mocks dispatch_single (to avoid real hermes chat) but lets routing run for real.
        NOT dry-run — dry-run hardcodes 'general_chat' as the placeholder category.
        """
        with patch("pipeline.triage.classify", return_value=_fake_triage(category, confidence)), \
             patch("pipeline.dispatch_single", return_value=_fake_dispatch()):
            return pipeline.run_pipeline(CATEGORY_MESSAGES[category])

    def test_build_code_routes_to_dev(self):
        result = self._run_with_category("build_code")
        rd = result["routing_decision"]
        self.assertEqual(rd["skill"], "dev")
        self.assertEqual(rd["toolsets"], "file,web,terminal")
        self.assertIsNone(rd["role"])
        self.assertEqual(rd["thinking"], EXPECTED_THINKING_HIGH_CONF["build_code"])

    def test_debug_code_routes_to_dev_debugger(self):
        result = self._run_with_category("debug_code")
        rd = result["routing_decision"]
        self.assertEqual(rd["skill"], "dev")
        self.assertEqual(rd["toolsets"], "file,web,terminal")
        self.assertEqual(rd["role"], "debugger")

    def test_research_info_routes_to_advisors(self):
        result = self._run_with_category("research_info")
        rd = result["routing_decision"]
        self.assertEqual(rd["skill"], "advisors")
        self.assertEqual(rd["toolsets"], "file,web")

    def test_query_model_routes_to_ask(self):
        result = self._run_with_category("query_model")
        rd = result["routing_decision"]
        self.assertEqual(rd["skill"], "ask")
        self.assertEqual(rd["toolsets"], "file,web")
        self.assertEqual(rd["thinking"], "low")

    def test_urgent_action_routes_inline(self):
        result = self._run_with_category("urgent_action")
        rd = result["routing_decision"]
        self.assertIsNone(rd["skill"])
        self.assertIsNone(rd["toolsets"])

    def test_general_chat_routes_inline(self):
        result = self._run_with_category("general_chat")
        rd = result["routing_decision"]
        self.assertIsNone(rd["skill"])
        self.assertEqual(rd["thinking"], "minimal")

    def test_deploy_code_routes_to_dev(self):
        result = self._run_with_category("deploy_code")
        rd = result["routing_decision"]
        self.assertEqual(rd["skill"], "dev")
        self.assertEqual(rd["toolsets"], "file,web,terminal")

    def test_write_docs_routes_to_dev(self):
        result = self._run_with_category("write_docs")
        rd = result["routing_decision"]
        self.assertEqual(rd["skill"], "dev")
        self.assertEqual(rd["toolsets"], "file,web")

    def test_config_change_routes_to_dev(self):
        result = self._run_with_category("config_change")
        rd = result["routing_decision"]
        self.assertEqual(rd["skill"], "dev")
        self.assertEqual(rd["toolsets"], "file,terminal")

    def test_status_check_routes_inline(self):
        result = self._run_with_category("status_check")
        rd = result["routing_decision"]
        self.assertIsNone(rd["skill"])

    def test_explain_concept_routes_to_ask(self):
        result = self._run_with_category("explain_concept")
        rd = result["routing_decision"]
        self.assertEqual(rd["skill"], "ask")
        self.assertEqual(rd["toolsets"], "file,web")

    def test_all_categories_covered(self):
        """Every triage category should be in the routing table."""
        for cat in CATEGORY_MESSAGES:
            result = self._run_with_category(cat)
            self.assertEqual(result["triage_result"]["category"], cat)
            self.assertIn(cat, ROUTING_TABLE, f"Category {cat} missing from ROUTING_TABLE")


# ── Test Class 2: Dispatch Mocked (verify dispatch_single is called correctly) ─

class TestConfigDefaults(unittest.TestCase):
    """Verify pipeline defaults are sourced from model_utils."""

    def test_run_pipeline_defaults_match_model_utils(self):
        defaults = inspect.signature(pipeline.run_pipeline).parameters
        self.assertEqual(defaults["timeout"].default, model_utils.DEFAULT_TIMEOUT)
        self.assertEqual(defaults["max_turns"].default, model_utils.DEFAULT_MAX_TURNS)

    @patch("pipeline.dispatch_single", return_value=_fake_dispatch())
    @patch("pipeline.triage.classify", return_value=_fake_triage("query_model"))
    def test_progress_callback_emits_pipeline_events_and_reaches_dispatch(
            self, mock_triage, mock_dispatch):
        """Pipeline events precede dispatch and the same callback reaches dispatch_single."""
        events = []

        def callback(event):
            events.append(event)

        pipeline.run_pipeline("What is ACID?", progress_callback=callback)

        self.assertEqual(
            [event["event"] for event in events],
            ["triage_done", "routing_decision"],
        )
        self.assertIs(mock_dispatch.call_args.kwargs["progress_callback"], callback)

    @patch("pipeline.time.sleep")
    @patch("pipeline.dispatch_single", return_value=_fake_dispatch(
        content=None, error="API error: 429 rate limit"))
    @patch("pipeline.triage.classify", return_value=_fake_triage("query_model"))
    def test_progress_callback_emits_retry_event(
            self, mock_triage, mock_dispatch, mock_sleep):
        """A transient first attempt emits a one-based dispatch_retry event."""
        events = []

        pipeline.run_pipeline(
            "What is ACID?", max_retries=1, progress_callback=events.append)

        retries = [event for event in events if event["event"] == "dispatch_retry"]
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0]["attempt"], 1)
        self.assertIn("429", retries[0]["reason"])

    def test_dry_run_progress_callback_emits_only_pipeline_events(self):
        """Synthetic dry-run triage still reports the two completed pipeline stages."""
        events = []

        pipeline.run_pipeline("x", dry_run=True, progress_callback=events.append)

        self.assertEqual(
            [event["event"] for event in events],
            ["triage_done", "routing_decision"],
        )

    @patch("pipeline.time.sleep")
    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_transient_dispatch_retries_are_bounded(self, mock_triage, mock_dispatch, mock_sleep):
        mock_dispatch.return_value = {
            "content": None, "session_id": None, "elapsed": 0.1,
            "error": "API error: 429 rate limit",
        }

        result = pipeline.run_pipeline("Build a REST API", max_retries=2)

        self.assertEqual(mock_dispatch.call_count, 3)
        self.assertEqual(result["dispatch_retries"], 2)
        self.assertTrue(result["dispatch_result"]["retried"])

    @patch("pipeline.time.sleep")
    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_exit_zero_empty_output_retries(self, mock_triage, mock_dispatch, mock_sleep):
        mock_dispatch.return_value = {
            "content": None, "session_id": None, "elapsed": 0.1,
            "error": "Empty output (exit 0). stderr: ", "returncode": 0,
            "thinking": "default",
        }

        result = pipeline.run_pipeline("Build a REST API")

        self.assertEqual(mock_dispatch.call_count, 2)
        self.assertTrue(result["dispatch_result"]["retried"])
        self.assertEqual(result["pipeline_status"], "dispatch_failed")

    @patch("pipeline.time.sleep")
    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_nonzero_exit_empty_output_does_not_retry(self, mock_triage, mock_dispatch, mock_sleep):
        mock_dispatch.return_value = {
            "content": None, "session_id": None, "elapsed": 0.1,
            "error": "Empty output (exit 2). stderr: usage: ...", "returncode": 2,
            "thinking": "default",
        }

        result = pipeline.run_pipeline("Build a REST API")

        mock_dispatch.assert_called_once()
        self.assertEqual(result["pipeline_status"], "dispatch_failed")
        self.assertEqual(result["dispatch_retries"], 0)


class TestPipelineDispatchMocked(unittest.TestCase):
    """Verify dispatch_single is called with the right args and outputs flow back.

    Mocks both triage.classify and pipeline.dispatch_single.
    P9: SDLC functions are disabled at module level — build_code/debug_code
    fall through to single dispatch for these tests.
    """

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_dispatch_fires_for_build_code(self, mock_triage, mock_dispatch):
        mock_dispatch.return_value = _fake_dispatch("FastAPI plan with routes...")
        result = pipeline.run_pipeline("Build a REST API")
        mock_dispatch.assert_called_once()
        kwargs = mock_dispatch.call_args.kwargs
        # Pipeline resolves alias → full model name
        self.assertEqual(kwargs["model"], "deepseek-v4-pro:cloud")
        self.assertEqual(kwargs["thinking"], "low")  # confidence=high → 'low'
        # P1-C: P3 augmentation narrows toolsets — removes file,terminal for dev skill
        self.assertEqual(kwargs["toolsets"], "web")
        self.assertIn("Build a REST API", kwargs["prompt"])
        self.assertIsNotNone(result["dispatch_result"]["content"])
        self.assertTrue(result["pipeline_success"])

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("debug_code"))
    def test_dispatch_uses_routing_toolsets(self, mock_triage, mock_dispatch):
        """Dispatch should use toolsets from routing, not a default."""
        mock_dispatch.return_value = _fake_dispatch()
        pipeline.run_pipeline("Debug this error")
        kwargs = mock_dispatch.call_args.kwargs
        self.assertEqual(kwargs["toolsets"], "file,web,terminal")  # debug_code toolsets

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_dispatch_respects_cost_budget_free(self, mock_triage, mock_dispatch):
        mock_dispatch.return_value = _fake_dispatch()
        pipeline.run_pipeline("Build a REST API", cost_budget="free")
        kwargs = mock_dispatch.call_args.kwargs
        # free → 'fast' alias → resolved to 'qwen3.6:35b-a3b'
        self.assertEqual(kwargs["model"], "qwen3.6:35b-a3b")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("research_info"))
    def test_dispatch_respects_cost_budget_low(self, mock_triage, mock_dispatch):
        mock_dispatch.return_value = _fake_dispatch()
        pipeline.run_pipeline("Research ORM options", cost_budget="low")
        kwargs = mock_dispatch.call_args.kwargs
        # low → 'glm' alias → resolved to 'glm-5.2:cloud'
        self.assertEqual(kwargs["model"], "glm-5.2:cloud")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("general_chat"))
    def test_dispatch_does_not_fire_for_inline(self, mock_triage, mock_dispatch):
        """Inline categories (skill=None) should not dispatch."""
        result = pipeline.run_pipeline("hello")
        mock_dispatch.assert_not_called()
        self.assertTrue(result["dispatch_result"]["inline"])

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_dispatch_failure_propagates(self, mock_triage, mock_dispatch):
        """If dispatch returns an error, pipeline_success should be True (routing succeeded)."""
        mock_dispatch.return_value = {
            "content": None, "session_id": None,
            "elapsed": 5.0, "error": "Timed out after 300s", "thinking": "low",
        }
        result = pipeline.run_pipeline("Build a REST API")
        # Pipeline success is True (no routing error), but dispatch_result has error
        self.assertIsNotNone(result["dispatch_result"]["error"])
        self.assertIn("Timed out", result["dispatch_result"]["error"])


    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_custom_toolsets_override(self, mock_triage, mock_dispatch):
        """Pipeline should pass custom toolsets override to dispatch."""
        mock_dispatch.return_value = _fake_dispatch()
        pipeline.run_pipeline("Build a REST API", toolsets="terminal")
        kwargs = mock_dispatch.call_args.kwargs
        self.assertEqual(kwargs["toolsets"], "terminal")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_max_turns_and_timeout_passthrough(self, mock_triage, mock_dispatch):
        """Pipeline should pass max_turns and timeout to dispatch."""
        mock_dispatch.return_value = _fake_dispatch()
        pipeline.run_pipeline("Build a REST API", max_turns=10, timeout=120)
        kwargs = mock_dispatch.call_args.kwargs
        self.assertEqual(kwargs["max_turns"], 10)
        self.assertEqual(kwargs["timeout"], 120)


class TestPipelineAutoAnswer(unittest.TestCase):
    """Free-text clarification handling stays bounded and session-scoped."""

    def test_question_round_cap_returns_needs_human(self):
        question = {
            "content": "Which database do you prefer?",
            "session_id": "s1",
            "elapsed": 0.1,
            "error": None,
            "thinking": "low",
        }
        events = []

        with patch("pipeline.triage.classify", return_value=_fake_triage("query_model")), \
             patch("pipeline.dispatch_single", return_value=question) as mock_dispatch, \
             patch(
                 "pipeline.generate_auto_answer",
                 side_effect=[
                     {"answer": "PostgreSQL", "error": None},
                     {"answer": "Use the standard deployment.", "error": None},
                 ],
             ), \
             patch("pipeline.routing.log_pipeline_event"):
            result = pipeline.run_pipeline(
                "Design the data layer",
                auto_answer=True,
                progress_callback=events.append,
            )

        self.assertEqual(mock_dispatch.call_count, 3)
        self.assertEqual(mock_dispatch.call_args_list[1].kwargs["resume_session"], "s1")
        self.assertEqual(result["pipeline_status"], "needs_human")
        self.assertEqual(result["pipeline_exit_code"], 2)
        self.assertIsNone(result["error"])
        self.assertEqual(result["pending_question"], "Which database do you prefer?")
        self.assertEqual(len(result["auto_answers"]), 2)
        self.assertEqual(
            len([event for event in events if event["event"] == "auto_answer"]), 2,
        )


# ── Test Class 3: Live Dispatch (opt-in) ──────────────────────────────────────

@pytest.mark.live
class TestPipelineDispatchLive(unittest.TestCase):
    """Full live pipeline — only runs when RUN_LIVE_PIPELINE=1 and Ollama is reachable.

    These tests exercise the real triage → routing → hermes chat chain.
    Each test uses a realistic user message and verifies the pipeline produces output.
    """

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("RUN_LIVE_PIPELINE"):
            raise unittest.SkipTest("Set RUN_LIVE_PIPELINE=1 to run live pipeline tests")
        import urllib.request
        try:
            req = urllib.request.Request(
                "http://host.docker.internal:11434/api/tags",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception:
            raise unittest.SkipTest("Ollama API not reachable")
        # Re-enable devloop for live tests (real E2E through devloop)
        if _orig_devloop_enabled is None:
            _os.environ.pop('DEVLOOP_ENABLED', None)
        else:
            _os.environ['DEVLOOP_ENABLED'] = _orig_devloop_enabled

    def _run_live(self, message, timeout=120, max_turns=3):
        return pipeline.run_pipeline(message, timeout=timeout, max_turns=max_turns)

    def test_live_build_code_produces_output(self):
        """Idea: build a FastAPI todo app → pipeline routes to dev, produces code."""
        result = self._run_live("Build a minimal FastAPI todo API")
        self.assertTrue(result["pipeline_success"])
        self.assertEqual(result["triage_result"]["category"], "build_code")
        self.assertEqual(result["routing_decision"]["skill"], "dev")
        self.assertIsNotNone(result["dispatch_result"]["content"])
        self.assertGreater(len(result["dispatch_result"]["content"]), 50)

    def test_live_debug_code_produces_output(self):
        """Idea: debug a TypeError → pipeline routes to dev/debugger, produces explanation."""
        result = self._run_live("Debug this: TypeError: expected str, got NoneType")
        self.assertTrue(result["pipeline_success"])
        self.assertEqual(result["triage_result"]["category"], "debug_code")
        self.assertEqual(result["routing_decision"]["skill"], "dev")
        self.assertIsNotNone(result["dispatch_result"]["content"])

    def test_live_research_info_produces_output(self):
        """Idea: research ORM options → pipeline routes to advisors, produces analysis."""
        result = self._run_live("Research SQLAlchemy vs Django ORM")
        self.assertTrue(result["pipeline_success"])
        self.assertEqual(result["triage_result"]["category"], "research_info")
        self.assertIsNotNone(result["dispatch_result"]["content"])

    def test_live_explain_concept_produces_output(self):
        """Idea: explain idempotency → pipeline routes to ask, produces explanation."""
        result = self._run_live("What is idempotency?")
        self.assertTrue(result["pipeline_success"])
        self.assertEqual(result["triage_result"]["category"], "explain_concept")
        self.assertEqual(result["routing_decision"]["skill"], "ask")
        self.assertIsNotNone(result["dispatch_result"]["content"])

    def test_live_urgent_action_inline_no_dispatch(self):
        """Urgent message → pipeline classifies as urgent_action, responds inline (no dispatch)."""
        result = self._run_live("URGENT production is down")
        self.assertEqual(result["triage_result"]["category"], "urgent_action")
        self.assertIsNone(result["routing_decision"]["skill"])
        self.assertTrue(result["dispatch_result"]["inline"])

    def test_live_general_chat_inline_no_dispatch(self):
        """Casual message → pipeline classifies as general_chat, responds inline."""
        result = self._run_live("hello there")
        self.assertEqual(result["triage_result"]["category"], "general_chat")
        self.assertIsNone(result["routing_decision"]["skill"])
        self.assertTrue(result["dispatch_result"]["inline"])


# ── Test Class 4: Cost Budgets ───────────────────────────────────────────────

class TestPipelineCostBudgets(unittest.TestCase):
    """Verify cost budget routing through the full pipeline."""

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_cost_budget_free_prefers_local(self, mock_triage, mock_dispatch):
        mock_dispatch.return_value = _fake_dispatch()
        pipeline.run_pipeline("Build a REST API", cost_budget="free")
        self.assertEqual(mock_dispatch.call_args.kwargs["model"], "qwen3.6:35b-a3b")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_cost_budget_low_prefers_glm(self, mock_triage, mock_dispatch):
        mock_dispatch.return_value = _fake_dispatch()
        pipeline.run_pipeline("Build a REST API", cost_budget="low")
        self.assertEqual(mock_dispatch.call_args.kwargs["model"], "glm-5.2:cloud")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_cost_budget_medium_prefers_deepseek(self, mock_triage, mock_dispatch):
        mock_dispatch.return_value = _fake_dispatch()
        pipeline.run_pipeline("Build a REST API", cost_budget="medium")
        self.assertEqual(mock_dispatch.call_args.kwargs["model"], "deepseek-v4-pro:cloud")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_cost_budget_high_prefers_deepseek(self, mock_triage, mock_dispatch):
        mock_dispatch.return_value = _fake_dispatch()
        pipeline.run_pipeline("Build a REST API", cost_budget="high")
        self.assertEqual(mock_dispatch.call_args.kwargs["model"], "deepseek-v4-pro:cloud")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_invalid_cost_budget_defaults_to_medium(self, mock_triage, mock_dispatch):
        """Invalid cost budget should fall back to medium tier."""
        mock_dispatch.return_value = _fake_dispatch()
        result = pipeline.run_pipeline("Build a REST API", cost_budget="expensive")
        rd = result["routing_decision"]
        self.assertEqual(rd["model"], "deepseek")
        # But dispatch gets the resolved alias
        self.assertEqual(mock_dispatch.call_args.kwargs["model"], "deepseek-v4-pro:cloud")


# ── Test Class 5: Error Paths ─────────────────────────────────────────────────

class TestPipelineErrorPaths(unittest.TestCase):
    """Verify pipeline handles errors gracefully at each stage."""

    @patch("pipeline.triage.classify")
    def test_triage_error_returns_error_category(self, mock_triage):
        """If triage returns an error category, routing should fail gracefully."""
        mock_triage.return_value = {
            "category": "error",
            "confidence": "none",
            "error": "Connection refused",
            "elapsed": 0.1,
        }
        result = pipeline.run_pipeline("test message")
        # "error" is not in ROUTING_TABLE → routing.route raises ValueError
        self.assertFalse(result["pipeline_success"])
        self.assertIsNotNone(result["error"])

    @patch("pipeline.triage.classify")
    def test_unknown_triage_category_routing_fails(self, mock_triage):
        """Unknown category should cause routing to raise ValueError."""
        mock_triage.return_value = _fake_triage("not_a_real_category")
        result = pipeline.run_pipeline("test message")
        self.assertFalse(result["pipeline_success"])
        self.assertIn("Routing failed", result["error"])

    @patch("pipeline.routing.route")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_routing_valueerror_caught(self, mock_triage, mock_route):
        """If routing.route raises ValueError, pipeline should catch and report it."""
        mock_route.side_effect = ValueError("Bad routing input")
        result = pipeline.run_pipeline("test message")
        self.assertFalse(result["pipeline_success"])
        self.assertIn("Routing failed", result["error"])

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_dispatch_timeout_marks_failure(self, mock_triage, mock_dispatch):
        """Dispatch timeout should be visible in the result but not crash the pipeline."""
        mock_dispatch.return_value = {
            "content": None, "session_id": None,
            "elapsed": 300.0, "error": "Timed out after 300s", "thinking": "low",
        }
        result = pipeline.run_pipeline("Build a REST API")
        # P5 fix: pipeline_success must reflect dispatch errors, not just routing
        self.assertFalse(result["pipeline_success"],
                         "Dispatch timeout should make pipeline_success=False")
        self.assertIn("Timed out", result["error"],
                      "Dispatch error should propagate to pipeline error field")
        self.assertEqual(result["pipeline_status"], "dispatch_failed")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_dispatch_error_propagates_to_pipeline_success(self, mock_triage, mock_dispatch):
        """P5: dispatch_single returning an error must set pipeline_success=False."""
        mock_dispatch.return_value = {
            "content": None, "session_id": None,
            "elapsed": 5.0, "error": "Empty output. stderr: connection refused",
            "thinking": "default",
        }
        result = pipeline.run_pipeline("Build a REST API")
        self.assertFalse(result["pipeline_success"])
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["pipeline_status"], "dispatch_failed")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_dispatch_success_yields_pipeline_success(self, mock_triage, mock_dispatch):
        """P5: successful dispatch should make pipeline_success=True."""
        mock_dispatch.return_value = {
            "content": "Here is your code", "session_id": "abc123",
            "elapsed": 5.0, "error": None, "thinking": "default",
        }
        result = pipeline.run_pipeline("Build a REST API")
        self.assertTrue(result["pipeline_success"])
        self.assertIsNone(result["error"])
        self.assertEqual(result["pipeline_status"], "success")

    @patch("pipeline.triage.classify", return_value=_fake_triage("general_chat"))
    def test_inline_category_pipeline_success(self, mock_triage):
        """P5: inline (no dispatch) should be pipeline_success=True."""
        result = pipeline.run_pipeline("Hello there")
        # general_chat → skill=None → inline, no dispatch
        self.assertTrue(result["pipeline_success"])
        self.assertEqual(result["pipeline_status"], "success")

    def test_empty_message_triage_returns_error(self):
        """Empty message should cause triage to return error category."""
        with patch("pipeline.triage.classify") as mock_classify:
            mock_classify.return_value = {
                "category": "error",
                "confidence": "none",
                "error": "message is empty or None",
                "elapsed": 0,
            }
            result = pipeline.run_pipeline("")
            self.assertFalse(result["pipeline_success"])


# ── Test Class 6: CLI and Output ──────────────────────────────────────────────

class TestDevloopOutcomeSeam(unittest.TestCase):
    """Ask must consume devloop's shared outcome classification without reinterpretation."""

    def _run_devloop(self, dispatch_result):
        classifier = pipeline.devloop_bridge.classify_outcome
        bridge = MagicMock()
        bridge.SCRATCH = object()
        bridge.devloop_enabled.return_value = True
        bridge.call_guarded.return_value = dispatch_result
        bridge.classify_outcome.side_effect = classifier

        with patch("pipeline.triage.classify", return_value=_fake_triage("build_code")), \
             patch.object(pipeline, "devloop_bridge", bridge), \
             patch("routing.log_pipeline_event") as mock_log:
            result = pipeline.run_pipeline("Build a REST API")

        bridge.classify_outcome.assert_called_once_with(
            dispatch_result, requested_keep_branch=False)
        return result, mock_log

    def test_enabled_devloop_never_degrades_to_single_dispatch(self):
        """A live test_first route must reach call_guarded, never dispatch_single."""
        classifier = pipeline.devloop_bridge.classify_outcome
        bridge = MagicMock()
        bridge.SCRATCH = object()
        bridge.devloop_enabled.return_value = True
        bridge.call_guarded.return_value = {
            "content": "Merged devloop result", "error": None,
            "devloop_result": {
                "terminal": "COMPLETE", "merged": True, "delivery_mode": "merged",
            },
        }
        bridge.classify_outcome.side_effect = classifier
        routing_decision = {
            "skill": "dev", "model": "deepseek", "thinking": "high",
            "toolsets": "file,web", "role": None, "pipeline": "test_first",
        }

        with patch("pipeline.triage.classify", return_value=_fake_triage("build_code")), \
             patch("pipeline.routing.route", return_value=routing_decision), \
             patch.object(pipeline, "devloop_bridge", bridge), \
             patch("pipeline.dispatch_single") as mock_dispatch:
            result = pipeline.run_pipeline("Build a REST API")

        self.assertTrue(result["pipeline_success"])
        bridge.call_guarded.assert_called_once_with(
            bridge.run_build, "Build a REST API", timeout=3600, repo=bridge.SCRATCH)
        mock_dispatch.assert_not_called()

    def test_missing_devloop_bridge_fails_closed(self):
        """A test_first route must fail rather than silently single-dispatch on import loss."""
        routing_decision = {
            "skill": "dev", "model": "deepseek", "thinking": "high",
            "toolsets": "file,web", "role": None, "pipeline": "test_first",
        }
        with patch("pipeline.triage.classify", return_value=_fake_triage("build_code")), \
             patch("pipeline.routing.route", return_value=routing_decision), \
             patch.object(pipeline, "devloop_bridge", None), \
             patch("pipeline.dispatch_single") as mock_dispatch:
            result = pipeline.run_pipeline("Build a REST API")

        self.assertEqual(result["pipeline_status"], "dispatch_failed")
        self.assertEqual(result["pipeline_exit_code"], 1)
        self.assertIsNotNone(result["error"])
        self.assertIn("devloop unavailable", result["error"])
        mock_dispatch.assert_not_called()

    def test_merged_complete_is_success_everywhere(self):
        dispatch = {
            "content": "Merged devloop result", "error": None,
            "devloop_result": {
                "terminal": "COMPLETE", "merged": True, "delivery_mode": "merged",
            },
        }
        result, mock_log = self._run_devloop(dispatch)

        self.assertTrue(result["pipeline_success"])
        self.assertEqual(result["pipeline_status"], "success")
        self.assertIsNone(result["error"])
        self.assertEqual(result["pipeline_exit_code"], 0)
        self.assertTrue(mock_log.call_args.kwargs["success"])

    def test_human_review_is_needs_human_not_success(self):
        dispatch = {
            "content": "Human decision required", "error": None,
            "devloop_result": {"terminal": "HUMAN_REVIEW", "needs_human": True},
        }
        result, mock_log = self._run_devloop(dispatch)

        self.assertFalse(result["pipeline_success"])
        self.assertEqual(result["pipeline_status"], "needs_human")
        self.assertIsNone(result["error"])
        self.assertEqual(result["pipeline_exit_code"], 2)
        self.assertFalse(mock_log.call_args.kwargs["success"])

    def test_merge_degradation_is_delivery_failed(self):
        dispatch = {
            "content": "Complete, but branch was not delivered", "error": None,
            "devloop_result": {
                "terminal": "COMPLETE", "merged": False,
                "kept_branch": "devloop/run-123", "delivery_mode": "none",
                "merge_reason": "merge failed",
            },
        }
        result, mock_log = self._run_devloop(dispatch)

        self.assertFalse(result["pipeline_success"])
        self.assertEqual(result["pipeline_status"], "delivery_failed")
        self.assertEqual(result["error"], "merge failed")
        self.assertEqual(result["pipeline_exit_code"], 1)
        self.assertFalse(mock_log.call_args.kwargs["success"])

    def test_missing_terminal_is_dispatch_failed(self):
        dispatch = {"content": "malformed result", "error": None, "devloop_result": {}}
        result, mock_log = self._run_devloop(dispatch)

        self.assertFalse(result["pipeline_success"])
        self.assertEqual(result["pipeline_status"], "dispatch_failed")
        self.assertEqual(result["error"], "devloop did not complete")
        self.assertEqual(result["pipeline_exit_code"], 1)
        self.assertFalse(mock_log.call_args.kwargs["success"])

    def test_runtime_crash_remains_dispatch_failed(self):
        dispatch = {
            "content": "devloop crashed: boom", "error": "devloop crashed: boom",
            "devloop_result": {"terminal": "HUMAN_REVIEW", "reason": "boom"},
        }
        result, mock_log = self._run_devloop(dispatch)

        self.assertFalse(result["pipeline_success"])
        self.assertEqual(result["pipeline_status"], "dispatch_failed")
        self.assertEqual(result["error"], "devloop crashed: boom")
        self.assertEqual(result["pipeline_exit_code"], 1)
        self.assertFalse(mock_log.call_args.kwargs["success"])

    def test_already_satisfied_goal_metadata_is_preserved(self):
        goal = {
            "status": "achieved", "attempt_count": 1, "max_attempts": 3,
            "plan_path": "/tmp/goal/PLAN.json",
            "lessons_path": "/tmp/goal/LESSONS.jsonl",
            "journal_warning": None,
            "attempts": [{"name": "goal-p1-a1", "terminal": "COMPLETE",
                          "retryable": False, "delivery_mode": "already_satisfied"}],
        }
        dispatch = {
            "content": "Target already satisfies the verified goal", "error": None,
            "devloop_result": {
                "terminal": "COMPLETE", "delivery_mode": "already_satisfied",
                "already_satisfied": True, "merged": False, "goal": goal,
            },
        }

        result, mock_log = self._run_devloop(dispatch)

        self.assertTrue(result["pipeline_success"])
        self.assertEqual(result["pipeline_exit_code"], 0)
        self.assertEqual(result["dispatch_result"]["devloop_result"]["goal"], goal)
        self.assertTrue(mock_log.call_args.kwargs["success"])

    def test_goal_cap_exhaustion_is_needs_human_not_last_attempt_error(self):
        attempts = [
            {"name": f"goal-p1-a{i}", "terminal": "HUMAN_REVIEW",
             "retryable": True, "reason": "implementation evidence stayed red"}
            for i in range(1, 4)
        ]
        dispatch = {
            "content": "Three autonomous attempts exhausted; human review required",
            "error": None,
            "devloop_result": {
                "terminal": "HUMAN_REVIEW", "needs_human": True,
                "reason": "autonomous attempt cap exhausted",
                "goal": {
                    "status": "blocked", "attempt_count": 3, "max_attempts": 3,
                    "plan_path": "/tmp/goal/PLAN.json",
                    "lessons_path": "/tmp/goal/LESSONS.jsonl",
                    "journal_warning": None, "attempts": attempts,
                },
            },
        }

        result, mock_log = self._run_devloop(dispatch)

        self.assertFalse(result["pipeline_success"])
        self.assertEqual(result["pipeline_status"], "needs_human")
        self.assertEqual(result["pipeline_exit_code"], 2)
        self.assertIsNone(result["error"])
        self.assertEqual(
            result["dispatch_result"]["devloop_result"]["goal"]["attempts"], attempts)
        self.assertFalse(mock_log.call_args.kwargs["success"])


class TestPipelineCLIAndOutput(unittest.TestCase):
    """Test the pipeline CLI subprocess interface."""

    PIPELINE_SCRIPT = os.path.join(SCRIPTS, "pipeline.py")

    def _run(self, args, timeout=15):
        return subprocess.run(
            ["python3", self.PIPELINE_SCRIPT] + args,
            capture_output=True, text=True, timeout=timeout
        )

    def test_cli_dry_run_human_output(self):
        r = self._run(["Build a REST API", "--dry-run"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("Stage 1: Triage", r.stdout)
        self.assertIn("Stage 2: Routing", r.stdout)
        self.assertIn("Pipeline:", r.stdout)

    def test_cli_dry_run_json_output(self):
        r = self._run(["What is ACID?", "--dry-run", "--json"])
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertIn("triage_result", data)
        self.assertIn("routing_decision", data)
        self.assertTrue(data["pipeline_success"])

    def test_cli_cost_budget_free(self):
        r = self._run(["Build API", "--dry-run", "--cost-budget", "free", "--json"])
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["routing_decision"]["model"], "fast")

    def test_cli_json_output_valid_schema(self):
        """JSON output should have all expected top-level keys."""
        r = self._run(["test", "--dry-run", "--json"])
        data = json.loads(r.stdout)
        expected_keys = {"message", "triage_result", "routing_decision",
                         "dispatch_result", "pipeline_elapsed", "pipeline_success", "error",
                         "pipeline_exit_code"}
        self.assertTrue(expected_keys.issubset(data.keys()))

    def test_cli_no_message_errors(self):
        """No message argument should cause argparse error."""
        r = self._run([])
        self.assertNotEqual(r.returncode, 0)

    def test_main_uses_classified_pipeline_exit_code(self):
        """The CLI must preserve devloop's 0/2/1 terminal contract."""
        for status, exit_code in (("success", 0), ("needs_human", 2),
                                  ("delivery_failed", 1), ("dispatch_failed", 1)):
            result = {
                "pipeline_success": exit_code == 0,
                "pipeline_status": status,
                "pipeline_exit_code": exit_code,
                "error": None if status in ("success", "needs_human") else "failed",
                "triage_result": {}, "routing_decision": {}, "dispatch_result": None,
                "pipeline_elapsed": 0.0,
            }
            with self.subTest(status=status), \
                 patch("pipeline.run_pipeline", return_value=result), \
                 patch.object(sys, "argv", ["pipeline.py", "Build it", "--json"]), \
                 patch("builtins.print"):
                with self.assertRaises(SystemExit) as exited:
                    pipeline.main()
                self.assertEqual(exited.exception.code, exit_code)


# ── Test Class 7: Event Logging ──────────────────────────────────────────────

class TestPipelineEventLogging(unittest.TestCase):
    """Verify pipeline events are logged correctly to the events file."""

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_successful_pipeline_logs_event(self, mock_triage, mock_dispatch):
        mock_dispatch.return_value = _fake_dispatch()
        with patch("routing.log_pipeline_event") as mock_log:
            pipeline.run_pipeline("Build a REST API")
            mock_log.assert_called_once()
            args = mock_log.call_args.kwargs
            self.assertTrue(args["success"])
            self.assertEqual(args["triage_result"]["category"], "build_code")
            self.assertGreater(args["latency"], 0)

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_failed_dispatch_logs_success_false(self, mock_triage, mock_dispatch):
        mock_dispatch.return_value = {
            "content": None, "session_id": None,
            "elapsed": 5.0, "error": "Timed out", "thinking": "low",
        }
        with patch("routing.log_pipeline_event") as mock_log:
            pipeline.run_pipeline("Build a REST API")
            mock_log.assert_called_once()
            self.assertFalse(mock_log.call_args.kwargs["success"])

    @patch("pipeline.triage.classify", return_value=_fake_triage("general_chat"))
    def test_dry_run_does_not_log_event(self, mock_triage):
        """Dry-run mode should NOT log pipeline events."""
        with patch("routing.log_pipeline_event") as mock_log:
            pipeline.run_pipeline("hello", dry_run=True)
            mock_log.assert_not_called()

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_log_event_has_latency(self, mock_triage, mock_dispatch):
        mock_dispatch.return_value = _fake_dispatch()
        with patch("routing.log_pipeline_event") as mock_log:
            pipeline.run_pipeline("Build a REST API")
            latency = mock_log.call_args.kwargs["latency"]
            self.assertGreaterEqual(latency, 0)


# ── Test Class 8: Edge Cases ──────────────────────────────────────────────────

class TestPipelineEdgeCases(unittest.TestCase):
    """Test edge cases: multi-intent, urgency, alias resolution, thinking override."""

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("research_info"))
    def test_multi_intent_first_actionable_wins(self, mock_triage, mock_dispatch):
        """If triage classifies as research_info (first actionable intent), routing should
        route to advisors even if the message also mentions building."""
        mock_dispatch.return_value = _fake_dispatch()
        result = pipeline.run_pipeline("Research ORM options then build the API")
        self.assertEqual(result["triage_result"]["category"], "research_info")
        self.assertEqual(result["routing_decision"]["skill"], "advisors")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("urgent_action"))
    def test_urgency_override_routes_inline(self, mock_triage, mock_dispatch):
        """Urgent messages should route inline (no dispatch)."""
        result = pipeline.run_pipeline("Build API — URGENT production down!")
        self.assertIsNone(result["routing_decision"]["skill"])
        self.assertTrue(result["dispatch_result"]["inline"])
        mock_dispatch.assert_not_called()

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("query_model"))
    def test_model_alias_from_routing_resolved_for_dispatch(self, mock_triage, mock_dispatch):
        """Routing returns alias 'deepseek' — pipeline resolves to full model name for dispatch."""
        mock_dispatch.return_value = _fake_dispatch()
        pipeline.run_pipeline("ask deepseek what is ACID?", cost_budget="medium")
        model = mock_dispatch.call_args.kwargs["model"]
        # Pipeline resolves alias → full model name
        self.assertEqual(model, "deepseek-v4-pro:cloud")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code", confidence="low"))
    def test_low_confidence_produces_medium_thinking(self, mock_triage, mock_dispatch):
        """When triage confidence is 'low', thinking should be 'medium' (not 'low')."""
        mock_dispatch.return_value = _fake_dispatch()
        result = pipeline.run_pipeline("Build a REST API")
        # build_code + confidence=low → thinking='medium' (not 'low')
        self.assertEqual(result["routing_decision"]["thinking"], "medium")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code", confidence="low"))
    def test_low_confidence_triggers_retry_in_triage(self, mock_triage, mock_dispatch):
        """When triage returns low confidence, pipeline should still proceed (retry is triage's job)."""
        mock_dispatch.return_value = _fake_dispatch()
        result = pipeline.run_pipeline("Build a REST API")
        # Pipeline doesn't retry — it uses whatever triage returns
        self.assertEqual(result["triage_result"]["confidence"], "low")
        self.assertTrue(result["pipeline_success"])


# ── Kimi Review Gap Tests ─────────────────────────────────────────────────────


class TestPipelineAliasResolution(unittest.TestCase):
    """Kimi gap #1: Pipeline must resolve model alias before dispatch."""

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_pipeline_resolves_alias_before_dispatch(self, mock_triage, mock_dispatch):
        """Routing returns alias 'deepseek' — pipeline must resolve to 'deepseek-v4-pro:cloud'."""
        mock_dispatch.return_value = _fake_dispatch()
        pipeline.run_pipeline("Build a REST API", cost_budget="medium")
        model = mock_dispatch.call_args.kwargs["model"]
        self.assertEqual(model, "deepseek-v4-pro:cloud")
        self.assertNotEqual(model, "deepseek")  # Must be resolved, not raw alias

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_pipeline_resolves_free_budget_alias(self, mock_triage, mock_dispatch):
        """Free budget returns 'fast' alias — pipeline must resolve to 'qwen3.6:35b-a3b'."""
        mock_dispatch.return_value = _fake_dispatch()
        pipeline.run_pipeline("Build a REST API", cost_budget="free")
        model = mock_dispatch.call_args.kwargs["model"]
        self.assertEqual(model, "qwen3.6:35b-a3b")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_pipeline_resolves_low_budget_alias(self, mock_triage, mock_dispatch):
        """Low budget returns 'glm' alias — pipeline must resolve to 'glm-5.2:cloud'."""
        mock_dispatch.return_value = _fake_dispatch()
        pipeline.run_pipeline("Build a REST API", cost_budget="low")
        model = mock_dispatch.call_args.kwargs["model"]
        self.assertEqual(model, "glm-5.2:cloud")


class TestDispatchComparisonThinkingKwarg(unittest.TestCase):
    """Kimi gap #2: Regression test for thinking-as-kwarg fix in dispatch_comparison."""

    @patch("model_utils.dispatch_single")
    def test_comparison_passes_thinking_as_keyword(self, mock_dispatch):
        """dispatch_comparison must pass thinking= as kwarg, not positional arg."""
        mock_dispatch.return_value = _fake_dispatch()
        dispatch_comparison(["model-a", "model-b"], "test", "", "", 1, 10, "prov", thinking="high")
        # Both calls should have thinking="high" in kwargs
        self.assertEqual(mock_dispatch.call_count, 2)
        for call_obj in mock_dispatch.call_args_list:
            kwargs = call_obj.kwargs
            self.assertEqual(kwargs.get("thinking"), "high")

    @patch("model_utils.dispatch_single")
    def test_comparison_parallel_passes_thinking_none_as_keyword(self, mock_dispatch):
        """dispatch_comparison parallel path must also pass thinking= as kwarg."""
        mock_dispatch.return_value = _fake_dispatch()
        dispatch_comparison(["model-a", "model-b"], "test", "", "", 1, 10, "prov", thinking=None)
        self.assertEqual(mock_dispatch.call_count, 2)
        for call_obj in mock_dispatch.call_args_list:
            kwargs = call_obj.kwargs
            self.assertIsNone(kwargs.get("thinking"))


class TestStaleSessionFallback(unittest.TestCase):
    """Kimi gap #3: Test dispatch_single stale-session retry path."""

    @patch("model_utils.subprocess.run")
    @patch("model_utils._remove_session")
    def test_stale_session_triggers_fresh_retry(self, mock_remove, mock_run):
        """When stderr contains 'Session not found', dispatch retries without --resume."""

        call_count = [0]
        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            mock_r = MagicMock()
            if call_count[0] == 1:
                # First call: "Session not found" in stderr
                mock_r.stdout = ""
                mock_r.stderr = "Session not found: abc123"
            else:
                # Retry: success
                mock_r.stdout = "Here is the response"
                mock_r.stderr = ""
            return mock_r

        mock_run.side_effect = side_effect

        r = dispatch_single(
            "test-model", "test prompt", "", "file", 5, 30, "prov",
            resume_session="stale_sid", alias="test-alias",
        )
        # Should have retried (2 subprocess calls)
        self.assertEqual(call_count[0], 2)
        # Should have removed stale session
        mock_remove.assert_called_once_with("test-alias")
        # Should have content from retry
        self.assertEqual(r["content"], "Here is the response")

    @patch("model_utils.subprocess.run")
    @patch("model_utils._remove_session")
    def test_stale_session_retry_strips_resume_from_cmd(self, mock_remove, mock_run):
        """Retry command must NOT contain --resume."""
        call_count = [0]
        retry_cmd = []

        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            mock_r = MagicMock()
            if call_count[0] == 1:
                mock_r.stdout = ""
                mock_r.stderr = "Session not found: abc123"
            else:
                retry_cmd[:] = cmd
                mock_r.stdout = "Response"
                mock_r.stderr = ""
            return mock_r

        mock_run.side_effect = side_effect

        dispatch_single("test-model", "test", "", "", 5, 30, "prov",
                       resume_session="stale_sid", alias="test")

        # Retry command should not contain --resume
        self.assertNotIn("--resume", retry_cmd)


class TestRoutingMediumConfidenceThinking(unittest.TestCase):
    """Kimi gap #5: Test route() thinking branch with confidence='medium'."""

    def test_medium_confidence_non_general_uses_low_thinking(self):
        """Medium confidence on non-general_chat should produce 'low' thinking."""
        result = route({"category": "build_code", "confidence": "medium"})
        self.assertEqual(result["thinking"], "low")

    def test_medium_confidence_query_model_uses_low_thinking(self):
        """Medium confidence on query_model should produce 'low' thinking."""
        result = route({"category": "query_model", "confidence": "medium"})
        self.assertEqual(result["thinking"], "low")

    def test_low_confidence_non_general_uses_medium_thinking(self):
        """Low confidence on non-general_chat should produce 'medium' thinking."""
        result = route({"category": "build_code", "confidence": "low"})
        self.assertEqual(result["thinking"], "medium")

    def test_high_confidence_general_chat_uses_minimal(self):
        """High confidence on general_chat should produce 'minimal' thinking."""
        result = route({"category": "general_chat", "confidence": "high"})
        self.assertEqual(result["thinking"], "minimal")


class TestTriageRetryFallback(unittest.TestCase):
    """Kimi gap #6: Test triage.classify retry with think=True on low confidence."""

    def test_low_confidence_retries_with_think_enabled(self):
        """When first call returns low confidence, triage should retry with think=True."""
        import triage as triage_mod

        call_count = [0]
        def mock_urlopen_side_effect(req, timeout=None):
            call_count[0] += 1
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=None)
            if call_count[0] == 1:
                # First call: empty content → matched="unknown" → confidence="low" → triggers retry
                mock_resp.read.return_value = json.dumps({
                    "message": {"content": ""},
                    "eval_count": 5,
                }).encode("utf-8")
            else:
                # Retry with think=True: returns a valid category
                mock_resp.read.return_value = json.dumps({
                    "message": {"content": "build_code"},
                    "eval_count": 8,
                }).encode("utf-8")
            return mock_resp

        with patch("triage.urllib.request.urlopen", side_effect=mock_urlopen_side_effect):
            result = triage_mod.classify("test message", timeout=5)
            # Should have retried
            self.assertEqual(call_count[0], 2)
            self.assertTrue(result["fallback_used"])
            self.assertEqual(result["category"], "build_code")
            self.assertEqual(result["confidence"], "high")

    def test_retry_failure_keeps_original_result(self):
        """If retry also fails, original low-confidence result is kept."""
        import triage as triage_mod

        call_count = [0]
        def mock_urlopen_side_effect(req, timeout=None):
            call_count[0] += 1
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=None)
            if call_count[0] == 1:
                mock_resp.read.return_value = json.dumps({
                    "message": {"content": "zzz"},
                    "eval_count": 5,
                }).encode("utf-8")
            else:
                # Retry raises an exception
                raise Exception("Connection refused")
            return mock_resp

        with patch("triage.urllib.request.urlopen", side_effect=mock_urlopen_side_effect):
            result = triage_mod.classify("test message", timeout=5)
            # Should keep original result (not crash)
            self.assertEqual(result["category"], "zzz")
            self.assertFalse(result["fallback_used"])


class TestTriageMalformedResponse(unittest.TestCase):
    """Kimi gap #7: Test handling of malformed Ollama API response."""

    def test_missing_message_key_returns_error(self):
        """If Ollama response is missing 'message' key, classify should return error."""
        import triage as triage_mod

        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)
        mock_resp.read.return_value = json.dumps({"error": "model not found"}).encode("utf-8")

        with patch("triage.urllib.request.urlopen", return_value=mock_resp):
            result = triage_mod.classify("test", timeout=5)
            self.assertEqual(result["category"], "error")
            self.assertIn("error", result)

    def test_missing_content_key_returns_error(self):
        """If Ollama response has message but no content, classify should return error."""
        import triage as triage_mod

        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=None)
        mock_resp.read.return_value = json.dumps({
            "message": {"role": "assistant"}  # no "content" key
        }).encode("utf-8")

        with patch("triage.urllib.request.urlopen", return_value=mock_resp):
            result = triage_mod.classify("test", timeout=5)
            self.assertEqual(result["category"], "error")


class TestParseCategoryStrategies(unittest.TestCase):
    """Kimi gap #8: Direct tests for _parse_category strategies 2 and 3."""

    def test_strategy1_exact_last_line_match(self):
        """Strategy 1: last line is exactly a category name."""
        from triage import _parse_category
        cats = ["build_code", "debug_code", "general_chat"]
        matched, exact = _parse_category("some text\nbuild_code", cats)
        self.assertEqual(matched, "build_code")
        self.assertFalse(exact)  # not exact (had extra text)

    def test_strategy2_last_line_word_match(self):
        """Strategy 2: category name appears as a word in the last line."""
        from triage import _parse_category
        cats = ["build_code", "debug_code"]
        # Last line has "Category: build_code" — "build_code" is a word
        matched, _ = _parse_category("thinking...\nCategory: build_code", cats)
        self.assertEqual(matched, "build_code")

    def test_strategy3_last_quarter_match(self):
        """Strategy 3: category name appears in the last 25% of output."""
        from triage import _parse_category
        cats = ["build_code", "debug_code"]
        # Long text with category only in last quarter
        content = "x" * 100 + "\n" + "x" * 10 + " build_code"
        matched, _ = _parse_category(content, cats)
        self.assertEqual(matched, "build_code")

    def test_repeated_category_word_matches(self):
        """Strategy 2 with repeated category word (e.g., 'debug_code debug_code')."""
        from triage import _parse_category
        cats = ["build_code", "debug_code"]
        matched, _ = _parse_category("debug_code debug_code", cats)
        self.assertEqual(matched, "debug_code")

    def test_empty_content_returns_unknown(self):
        """Empty content should return 'unknown'."""
        from triage import _parse_category
        matched, _ = _parse_category("", ["build_code"])
        self.assertEqual(matched, "unknown")

    def test_no_match_returns_raw_content(self):
        """No category match should return raw content."""
        from triage import _parse_category
        matched, _ = _parse_category("something random", ["build_code"])
        self.assertEqual(matched, "something random")


class TestApiErrorDetection(unittest.TestCase):
    """Test is_api_error() and extract_python_code() guard logic (CI, no network).

    These functions live in test_pipeline_e2e.py but are pure — testable
    without a live Ollama connection.
    """

    def setUp(self):
        # Import from the e2e test module (pure functions, no live deps)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_pipeline_e2e import is_api_error, extract_python_code
        self.is_api_error = is_api_error
        self.extract_python_code = extract_python_code

    def test_detects_429_rate_limit(self):
        """HTTP 429 rate limit message should be detected as API error."""
        text = "API call failed after 3 retries: HTTP 429: Error code: 429 - rate limit exceeded"
        self.assertTrue(self.is_api_error(text))

    def test_detects_monthly_max_reached(self):
        """Ollama monthly max message should be detected as API error."""
        text = "extra usage auto reload monthly max reached, increase your monthly max"
        self.assertTrue(self.is_api_error(text))

    def test_detects_connection_error(self):
        """Connection error should be detected."""
        text = "API call failed: HTTP 500: Internal server error"
        self.assertTrue(self.is_api_error(text))

    def test_does_not_flag_normal_code(self):
        """Normal Python code should NOT be flagged as API error."""
        text = "def is_palindrome(s):\n    return s == s[::-1]\n\nprint(is_palindrome('racecar'))"
        self.assertFalse(self.is_api_error(text))

    def test_does_not_flag_code_with_429_number(self):
        """Code that happens to contain '429' as a number should not be flagged."""
        text = "x = 429\nprint(x)"
        # Only 1 pattern matches ("429"), needs 2+ to flag
        self.assertFalse(self.is_api_error(text))

    def test_does_not_flag_empty_response(self):
        """Empty string should not be flagged as API error."""
        self.assertFalse(self.is_api_error(""))

    def test_extract_returns_empty_for_api_error(self):
        """extract_python_code should return '' for API error messages."""
        error_text = "API call failed after 3 retries: HTTP 429: Error code: 429"
        code = self.extract_python_code(error_text)
        self.assertEqual(code, "")

    def test_extract_python_code_block(self):
        """Extract code from ```python ... ``` blocks."""
        text = 'Here is the code:\n```python\ndef hello():\n    print("Hello, World!")\n```\nDone.'
        code = self.extract_python_code(text)
        self.assertIn("def hello", code)
        self.assertIn("print", code)

    def test_extract_generic_code_block(self):
        """Extract code from generic ``` ... ``` blocks."""
        text = '```\ndef fib(n):\n    if n < 2: return n\n    return fib(n-1) + fib(n-2)\n```'
        code = self.extract_python_code(text)
        self.assertIn("def fib", code)

    def test_extract_bare_python(self):
        """Extract bare Python without code blocks."""
        text = 'def square(x):\n    return x * x\n\nprint(square(5))'
        code = self.extract_python_code(text)
        self.assertIn("def square", code)

    def test_extract_returns_largest_block(self):
        """When multiple code blocks exist, return the largest."""
        text = '```python\nx = 1\n```\n```python\ndef factorial(n):\n    if n <= 1: return 1\n    return n * factorial(n - 1)\n```'
        code = self.extract_python_code(text)
        self.assertIn("def factorial", code)


# ── P3: Prompt Augmentation Tests ────────────────────────────────────────────


class TestPromptAugmentation(unittest.TestCase):
    """P3: Verify dev skill gets prompt augmentation for code output."""

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("build_code"))
    def test_dev_skill_gets_code_directive(self, mock_triage, mock_dispatch):
        """When skill=dev, prompt should include self-contained code directive."""
        mock_dispatch.return_value = {
            "content": "code", "session_id": None, "elapsed": 1.0,
            "error": None, "thinking": "default",
        }
        pipeline.run_pipeline("Build a palindrome checker", timeout=10)
        call_kwargs = mock_dispatch.call_args.kwargs
        prompt = call_kwargs.get("prompt", "")
        # P1-B: Language is now detected (lowercase); default is 'python'
        self.assertIn("self-contained python script", prompt.lower())
        self.assertIn("```python", prompt)

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_triage("query_model"))
    def test_ask_skill_no_code_directive(self, mock_triage, mock_dispatch):
        """When skill=ask (query_model), no code directive should be added."""
        mock_dispatch.return_value = {
            "content": "answer", "session_id": None, "elapsed": 1.0,
            "error": None, "thinking": "default",
        }
        pipeline.run_pipeline("What is ACID?", timeout=10)
        call_kwargs = mock_dispatch.call_args.kwargs
        prompt = call_kwargs.get("prompt", "")
        self.assertNotIn("self-contained Python script", prompt)


# ── P4: Triage Confidence Override Tests ──────────────────────────────────────


class TestTriageConfidenceOverride(unittest.TestCase):
    """P4: Code keywords + non-code category should override to build_code."""

    _fake_general_chat = {
        "category": "general_chat", "confidence": "high",
        "raw_output": "general_chat", "tokens": 3, "elapsed": 0.5,
    }

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_general_chat)
    def test_code_keywords_override_general_chat(self, mock_triage, mock_dispatch):
        """Message with code keywords but triage=general_chat should override to build_code."""
        mock_dispatch.return_value = {
            "content": "code", "session_id": None, "elapsed": 1.0,
            "error": None, "thinking": "default",
        }
        result = pipeline.run_pipeline(
            "Write a Python function to check if a string is a palindrome", timeout=10
        )
        # Should have dispatched (overridden to build_code → dev skill)
        self.assertTrue(result["pipeline_success"])
        self.assertEqual(result["routing_decision"]["skill"], "dev")
        self.assertTrue(result["routing_decision"].get("_overridden", False))

    @patch("pipeline.triage.classify", return_value=_fake_general_chat)
    def test_no_code_keywords_no_override(self, mock_triage):
        """Message without code keywords should stay as general_chat (inline)."""
        result = pipeline.run_pipeline("Hello, how are you?", timeout=10)
        # Should stay inline (general_chat → skill=None)
        self.assertIsNone(result["routing_decision"]["skill"])
        self.assertNotIn("_overridden", result["routing_decision"])

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_general_chat)
    def test_single_keyword_no_override(self, mock_triage, mock_dispatch):
        """Only 1 code keyword should NOT trigger override (needs 2+)."""
        mock_dispatch.return_value = {
            "content": "code", "session_id": None, "elapsed": 1.0,
            "error": None, "thinking": "default",
        }
        # "python" is 1 keyword — not enough
        result = pipeline.run_pipeline("I love python", timeout=10)
        self.assertIsNone(result["routing_decision"]["skill"])
        self.assertNotIn("_overridden", result["routing_decision"])


# ── P7: CI-Runnable E2E Smoke Tests (mocked dispatch) ────────────────────────

# Canned model responses containing working Python code.
# These let us test the full pipeline (triage→routing→dispatch→extract→execute→validate)
# without needing Ollama or a live model.

_CANNED_PALINDROME = '''```python
def is_palindrome(s):
    s = s.replace(" ", "").lower()
    return s == s[::-1]

if __name__ == "__main__":
    print(is_palindrome("racecar"))
    print(is_palindrome("hello"))
```'''

_CANNED_FIZZBUZZ = '''```python
for i in range(1, 16):
    if i % 15 == 0:
        print("FizzBuzz")
    elif i % 3 == 0:
        print("Fizz")
    elif i % 5 == 0:
        print("Buzz")
    else:
        print(i)
```'''

_CANNED_FACTORIAL = '''```python
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

if __name__ == "__main__":
    print(factorial(5))
```'''


class TestPipelineE2EMocked(unittest.TestCase):
    """P7: CI-runnable E2E smoke tests with mocked dispatch.

    These tests exercise the FULL pipeline logic (triage→routing→dispatch→
    code extraction→execution→validation) but with mocked triage and dispatch,
    so they run in CI without Ollama or a live model.

    This catches regressions in:
    - Pipeline result structure (pipeline_success, pipeline_status, dispatch_retries)
    - P3: Prompt augmentation (dev skill gets code directive)
    - P2: Role passthrough (debug_code passes debugger role)
    - P5: Dispatch error propagation
    - Code extraction + execution logic
    """

    def setUp(self):
        # Import the pure functions from the E2E test module
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_pipeline_e2e import extract_python_code, execute_code, is_api_error
        self.extract_python_code = extract_python_code
        self.execute_code = execute_code
        self.is_api_error = is_api_error

    def _run_mocked_pipeline(self, message, canned_response, triage_category="build_code"):
        """Run pipeline with mocked triage + dispatch, return result."""
        fake_triage = _fake_triage(triage_category)
        with patch("pipeline.triage.classify", return_value=fake_triage), \
             patch("pipeline.dispatch_single") as mock_dispatch:
            mock_dispatch.return_value = {
                "content": canned_response,
                "session_id": "mock-session-123",
                "elapsed": 0.1,
                "error": None,
                "thinking": "default",
            }
            return pipeline.run_pipeline(message, timeout=10)

    def test_mocked_e2e_palindrome(self):
        """Full pipeline: palindrome idea → code → execute → validate."""
        result = self._run_mocked_pipeline(
            "Write a Python function to check if a string is a palindrome",
            _CANNED_PALINDROME,
        )
        self.assertTrue(result["pipeline_success"])
        self.assertEqual(result["pipeline_status"], "success")

        # Extract and execute the code
        content = result["dispatch_result"]["content"]
        code = self.extract_python_code(content)
        self.assertGreater(len(code), 20, "Should extract meaningful code")

        exec_result = self.execute_code(code)
        self.assertEqual(exec_result["returncode"], 0)
        self.assertIn("True", exec_result["stdout"])
        self.assertIn("False", exec_result["stdout"])

    def test_mocked_e2e_fizzbuzz(self):
        """Full pipeline: fizzbuzz idea → code → execute → validate."""
        result = self._run_mocked_pipeline(
            "Write a Python script that prints FizzBuzz",
            _CANNED_FIZZBUZZ,
        )
        self.assertTrue(result["pipeline_success"])

        code = self.extract_python_code(result["dispatch_result"]["content"])
        exec_result = self.execute_code(code)
        self.assertEqual(exec_result["returncode"], 0)
        self.assertIn("Fizz", exec_result["stdout"])
        self.assertIn("Buzz", exec_result["stdout"])
        self.assertIn("FizzBuzz", exec_result["stdout"])

    def test_mocked_e2e_factorial(self):
        """Full pipeline: factorial idea → code → execute → validate."""
        result = self._run_mocked_pipeline(
            "Write a Python function to compute factorial",
            _CANNED_FACTORIAL,
        )
        self.assertTrue(result["pipeline_success"])

        code = self.extract_python_code(result["dispatch_result"]["content"])
        exec_result = self.execute_code(code)
        self.assertEqual(exec_result["returncode"], 0)
        self.assertIn("120", exec_result["stdout"])

    def test_mocked_e2e_prompt_augmentation(self):
        """P3: Verify the dispatch prompt was augmented for dev skill."""
        self._run_mocked_pipeline(
            "Build a palindrome checker",
            _CANNED_PALINDROME,
        )
        # P3: dev skill should get prompt augmentation
        # We can verify this by checking that dispatch was called with augmented prompt
        with patch("pipeline.triage.classify", return_value=_fake_triage("build_code")), \
             patch("pipeline.dispatch_single") as mock_dispatch:
            mock_dispatch.return_value = {
                "content": _CANNED_PALINDROME, "session_id": "x",
                "elapsed": 0.1, "error": None, "thinking": "default",
            }
            pipeline.run_pipeline("Build something", timeout=10)
            prompt = mock_dispatch.call_args.kwargs.get("prompt", "")
            # P1-B: Language is now detected (lowercase); default is 'python'
            self.assertIn("self-contained python script", prompt.lower())

    def test_mocked_e2e_api_error_handled(self):
        """P1+P5: API error in dispatch should set pipeline_success=False."""
        fake_triage = _fake_triage("build_code")
        with patch("pipeline.triage.classify", return_value=fake_triage), \
             patch("pipeline.dispatch_single") as mock_dispatch, \
             patch("pipeline.time.sleep"):
            mock_dispatch.return_value = {
                "content": None, "session_id": None, "elapsed": 0.1,
                "error": "API error: HTTP 429: rate limit exceeded",
                "thinking": "default",
            }
            result = pipeline.run_pipeline("Build something", max_retries=0, timeout=10)
        self.assertFalse(result["pipeline_success"])
        self.assertEqual(result["pipeline_status"], "dispatch_failed")


# ── P6: Session Registry for Iterations Tests ────────────────────────────────


class TestPipelineIteration(unittest.TestCase):
    """P6: Verify iterate() function and session passthrough."""

    _fake_build = {
        "category": "build_code", "confidence": "high",
        "raw_output": "build_code", "tokens": 3, "elapsed": 0.5,
    }

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_build)
    def test_iterate_passes_error_feedback(self, mock_triage, mock_dispatch):
        """iterate() should include error feedback in the prompt."""
        from pipeline import iterate
        mock_dispatch.return_value = {
            "content": "fixed code", "session_id": "new-session",
            "elapsed": 1.0, "error": None, "thinking": "default",
        }
        result = iterate(
            message="Write a palindrome function",
            error_feedback="NameError: name 'is_palindrome' is not defined",
            timeout=10,
        )
        self.assertTrue(result["pipeline_success"])
        # The prompt should contain the error feedback
        prompt = mock_dispatch.call_args.kwargs.get("prompt", "")
        self.assertIn("NameError", prompt)
        self.assertIn("Fix the code", prompt)

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_build)
    def test_iterate_passes_session_id(self, mock_triage, mock_dispatch):
        """iterate() should pass prev_session_id to dispatch_single."""
        from pipeline import iterate
        mock_dispatch.return_value = {
            "content": "fixed code", "session_id": "new-session",
            "elapsed": 1.0, "error": None, "thinking": "default",
        }
        iterate(
            message="Write a function",
            error_feedback="SyntaxError",
            prev_session_id="abc-123",
            timeout=10,
        )
        call_kwargs = mock_dispatch.call_args.kwargs
        self.assertEqual(call_kwargs.get("resume_session"), "abc-123")

    @patch("pipeline.dispatch_single")
    @patch("pipeline.triage.classify", return_value=_fake_build)
    def test_run_pipeline_passes_resume_session(self, mock_triage, mock_dispatch):
        """run_pipeline should pass resume_session to dispatch_single."""
        mock_dispatch.return_value = {
            "content": "code", "session_id": "xyz",
            "elapsed": 1.0, "error": None, "thinking": "default",
        }
        pipeline.run_pipeline("Build something", resume_session="sess-456", timeout=10)
        call_kwargs = mock_dispatch.call_args.kwargs
        self.assertEqual(call_kwargs.get("resume_session"), "sess-456")


# ── pytest marker registration ───────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires RUN_LIVE_PIPELINE=1 and Ollama")


if __name__ == "__main__":
    unittest.main(verbosity=2)
