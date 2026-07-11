"""Unit tests for the durable prompt-workflow auto-answer driver."""

import os
import sys
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import gate_driver  # noqa: E402


class _RunResult:
    def __init__(self, code, payload=None):
        self.code = code
        self.payload = payload if payload is not None else {"code": code}


def _pending(gate_id="gate-1", question="Which option?", options=None):
    return {"pending": {"key": gate_id, "question": {
        "prompt": question,
        "options": options or [],
    }}}


class TestCanonicalOption(unittest.TestCase):
    def test_normalizes_unambiguous_live_model_replies(self):
        options = ["approved", "denied"]
        cases = {
            "Approved.": "approved",
            '"denied"': "denied",
            "Answer: approved": "approved",
            "APPROVED\n\nbecause reasons": "approved",
            "maybe": None,
            "approved because it is safe": None,
        }

        for answer, expected in cases.items():
            with self.subTest(answer=answer):
                self.assertEqual(gate_driver._canonical_option(answer, options), expected)


class TestDrive(unittest.TestCase):
    @patch("gate_driver.generate_auto_answer")
    def test_suspend_auto_answer_resume_complete(self, generate):
        generate.return_value = {"answer": "Use the standard option.", "error": None}
        events = []
        resumed = Mock(return_value=_RunResult(0, {"status": "completed"}))

        result = gate_driver.drive(
            lambda: _RunResult(10, {"status": "suspended"}),
            lambda: _pending(question="What should I do?"), resumed,
            auto_answer=True, answer_model="test-model", progress_callback=events.append,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["rounds_used"], 1)
        self.assertEqual(len(result["auto_answers"]), 1)
        self.assertEqual(result["auto_answers"][0]["seam"], "gate")
        self.assertEqual(events[0]["event"], "auto_answer")
        self.assertEqual(generate.call_args.kwargs["timeout"], gate_driver.DEFAULT_TIMEOUT)
        resumed.assert_called_once_with("gate-1", "Use the standard option.")

    @patch("gate_driver.generate_auto_answer")
    def test_enum_retries_off_menu_then_resumes_valid_option(self, generate):
        generate.side_effect = [
            {"answer": "possibly", "error": None},
            {"answer": "APPROVED", "error": None},
        ]
        resumed = Mock(return_value=_RunResult(0))

        result = gate_driver.drive(
            lambda: _RunResult(10),
            lambda: _pending(options=["approved", "denied"]), resumed,
            auto_answer=True, answer_model="test-model",
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(generate.call_count, 2)
        self.assertIn("previous reply 'possibly' was not one of the options",
                      generate.call_args_list[1].kwargs["context"])
        resumed.assert_called_once_with("gate-1", "approved")

    @patch("gate_driver.generate_auto_answer")
    def test_enum_off_menu_twice_escalates_without_invalid_resume(self, generate):
        generate.side_effect = [
            {"answer": "maybe", "error": None},
            {"answer": "still maybe", "error": None},
        ]
        resumed = Mock()

        result = gate_driver.drive(
            lambda: _RunResult(10),
            lambda: _pending(options=["one", "two"]), resumed,
            auto_answer=True, answer_model="test-model",
        )

        self.assertEqual(result["status"], "needs_human")
        self.assertEqual(result["exit_code"], 2)
        self.assertIsNotNone(result["pending"])
        resumed.assert_not_called()

    @patch("gate_driver.generate_auto_answer")
    def test_round_cap_escalates_after_exactly_two_answers(self, generate):
        generate.side_effect = [
            {"answer": "first", "error": None},
            {"answer": "second", "error": None},
        ]
        inspections = iter([_pending("gate-1"), _pending("gate-2"), _pending("gate-3")])
        resumed = Mock(side_effect=[_RunResult(10), _RunResult(10)])

        result = gate_driver.drive(
            lambda: _RunResult(10), lambda: next(inspections), resumed,
            auto_answer=True, answer_model="test-model",
        )

        self.assertEqual(result["status"], "needs_human")
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["rounds_used"], 2)
        self.assertEqual(len(result["auto_answers"]), 2)
        self.assertEqual(resumed.call_count, 2)

    @patch("gate_driver.generate_auto_answer")
    def test_auto_answer_false_escalates_immediately(self, generate):
        resumed = Mock()

        result = gate_driver.drive(
            lambda: _RunResult(10), lambda: _pending(), resumed,
            auto_answer=False, answer_model=None,
        )

        self.assertEqual(result["status"], "needs_human")
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["rounds_used"], 0)
        generate.assert_not_called()
        resumed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
