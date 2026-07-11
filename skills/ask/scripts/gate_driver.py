#!/usr/bin/env python3
"""Run a prompt-first workflow and optionally answer up to two durable gates.

``prompt_runtime`` reports a suspended workflow with exit code 10.  This driver
turns an unanswered suspension into the normal needs-human exit code 2, while
``--auto-answer`` can make bounded, auditable progress through simple gates.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from typing import Any, Callable, Optional

from model_utils import (DEFAULT_PROVIDER, DEFAULT_TIMEOUT, _make_stderr_event_callback,
                         _safe_callback, generate_auto_answer, resolve_alias)


HERE = os.path.dirname(os.path.abspath(__file__))
RESUMABLE_SCRIPT_DIR = os.environ.get(
    "RESUMABLE_SCRIPT_DIR",
    os.path.abspath(os.path.join(HERE, "../../../resumable-script/scripts")),
)
if RESUMABLE_SCRIPT_DIR not in sys.path:
    sys.path.insert(0, RESUMABLE_SCRIPT_DIR)

try:
    from prompt_runtime import ModelSet, inspect_workflow, resume_workflow, run_workflow
    from prompt_workflow import read_prompt_spec
except ImportError as exc:  # pragma: no cover - host setup failure, not loop behavior
    raise ImportError(
        "gate_driver.py requires resumable-script modules. Set RESUMABLE_SCRIPT_DIR "
        f"to its scripts directory (attempted {RESUMABLE_SCRIPT_DIR!r}): {exc}"
    ) from exc


SUSPENDED_EXIT_CODE = 10


def _result_code(result: Any) -> Optional[int]:
    """Read a runtime code from either ``RunResult`` or a test-friendly mapping."""
    if hasattr(result, "code"):
        return getattr(result, "code")
    if isinstance(result, Mapping):
        code = result.get("code", result.get("exit_code"))
        return code if isinstance(code, int) and not isinstance(code, bool) else None
    return None


def _result_payload(result: Any) -> Any:
    """Expose the actual runtime payload without coupling ``drive`` to RunResult."""
    if hasattr(result, "payload"):
        return dict(getattr(result, "payload"))
    return result


def _pending_from_inspection(inspected: Any) -> Optional[dict]:
    if not isinstance(inspected, Mapping):
        return None
    pending = inspected.get("pending")
    return dict(pending) if isinstance(pending, Mapping) else None


def _gate_details(pending: Mapping[str, Any]) -> tuple[Optional[str], Optional[str], list[str]]:
    """Extract gate id, question, and enum choices from prompt-runtime pending data."""
    gate_id = pending.get("key")
    question_value = pending.get("question")
    options: Any = pending.get("options")
    if isinstance(question_value, Mapping):
        question = question_value.get("prompt", question_value.get("question"))
        options = question_value.get("options", options)
    else:
        question = question_value
    if not isinstance(gate_id, str) or not gate_id:
        gate_id = None
    if not isinstance(question, str) or not question.strip():
        question = None
    else:
        question = question.strip()
    if not isinstance(options, list):
        schema = pending.get("schema")
        options = schema.get("enum") if isinstance(schema, Mapping) else []
    normalized_options = [option for option in options
                          if isinstance(option, str) and option.strip()]
    return gate_id, question, normalized_options


def _canonical_option(answer: str, options: list[str]) -> Optional[str]:
    """Return the declared spelling for a case-insensitive exact enum match."""
    first_line = next((line for line in answer.splitlines() if line.strip()), "")
    cleaned = re.sub(
        r"^\s*(?:answer|my\s+answer\s+is|i\s+choose|option)(?:\s*:\s*|\s+)",
        "", first_line, flags=re.IGNORECASE,
    ).strip()
    previous = None
    while cleaned != previous:
        previous = cleaned
        cleaned = cleaned.strip().strip("\"'`")
    cleaned = cleaned.strip(".,!;:").strip().casefold()
    for option in options:
        if cleaned == option.strip().casefold():
            return option
    return None


def _error_result(result: Any, auto_answers: list[dict], rounds_used: int,
                  message: str, pending: Optional[dict] = None) -> dict:
    return {
        "status": "error",
        "exit_code": 1,
        "result": _result_payload(result),
        "pending": pending,
        "auto_answers": auto_answers,
        "rounds_used": rounds_used,
        "error": message,
    }


def drive(run_fn: Callable[[], Any], inspect_fn: Callable[[], Any],
          resume_fn: Callable[[str, str], Any], *, auto_answer: bool,
          answer_model: Optional[str], max_rounds: int = 2,
          progress_callback: Optional[Callable] = None, run_dir: Optional[str] = None,
          answer_timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Run/resume a prompt workflow through at most ``max_rounds`` automatic gates.

    The three runtime callables make the gate state machine pure and unit-testable:
    no model or resumable-script imports are exercised by its tests.  A successful
    automatic reply is emitted as an ``auto_answer`` control-plane event and
    included in the returned audit list before the resume is attempted.
    """
    auto_answers: list[dict] = []
    rounds_used = 0
    try:
        result = run_fn()
    except Exception as exc:
        return _error_result(None, auto_answers, rounds_used, str(exc))

    while True:
        code = _result_code(result)
        if code is None:
            return _error_result(result, auto_answers, rounds_used,
                                 "workflow result has no integer code")
        if code != SUSPENDED_EXIT_CODE:
            if code == 0:
                return {
                    "status": "completed",
                    "exit_code": 0,
                    "result": _result_payload(result),
                    "pending": None,
                    "auto_answers": auto_answers,
                    "rounds_used": rounds_used,
                }
            return _error_result(result, auto_answers, rounds_used,
                                 f"workflow exited with code {code}")

        try:
            pending = _pending_from_inspection(inspect_fn())
        except Exception as exc:
            return _error_result(result, auto_answers, rounds_used,
                                 f"could not inspect suspended workflow: {exc}")
        if pending is None:
            return _error_result(result, auto_answers, rounds_used,
                                 "suspended workflow has no pending gate")

        if not auto_answer or rounds_used >= max_rounds:
            return {
                "status": "needs_human",
                "exit_code": 2,
                "result": _result_payload(result),
                "pending": pending,
                "auto_answers": auto_answers,
                "rounds_used": rounds_used,
            }

        gate_id, question, options = _gate_details(pending)
        if gate_id is None or question is None:
            return _error_result(result, auto_answers, rounds_used,
                                 "pending gate is missing key or question", pending)

        generation = generate_auto_answer(
            question, options=options or None, answer_model=answer_model or resolve_alias("deepseek"),
            timeout=answer_timeout, run_dir=run_dir, progress_callback=progress_callback,
        )
        answer = generation.get("answer") if isinstance(generation, Mapping) else None
        error = generation.get("error") if isinstance(generation, Mapping) else "invalid answer result"
        if not isinstance(answer, str) or not answer.strip():
            return _error_result(result, auto_answers, rounds_used,
                                 f"auto-answer generation failed: {error or 'empty response'}", pending)
        answer = answer.strip()

        if options:
            canonical = _canonical_option(answer, options)
            if canonical is None:
                retry_context = (
                    f"Your previous reply {answer!r} was not one of the options. "
                    "Reply with exactly one listed option."
                )
                retry = generate_auto_answer(
                    question, options=options, context=retry_context,
                    answer_model=answer_model or resolve_alias("deepseek"), run_dir=run_dir,
                    timeout=answer_timeout, progress_callback=progress_callback,
                )
                retry_answer = retry.get("answer") if isinstance(retry, Mapping) else None
                if not isinstance(retry_answer, str) or not retry_answer.strip():
                    return _error_result(
                        result, auto_answers, rounds_used,
                        "auto-answer retry failed: "
                        f"{retry.get('error') if isinstance(retry, Mapping) else 'invalid answer result'}",
                        pending,
                    )
                canonical = _canonical_option(retry_answer, options)
                if canonical is None:
                    return {
                        "status": "needs_human",
                        "exit_code": 2,
                        "result": _result_payload(result),
                        "pending": pending,
                        "auto_answers": auto_answers,
                        "rounds_used": rounds_used,
                    }
            answer = canonical

        rounds_used += 1
        event = {
            "event": "auto_answer",
            "question": question,
            "answer": answer,
            "round": rounds_used,
            "seam": "gate",
        }
        _safe_callback(progress_callback, event)
        auto_answers.append(event)
        try:
            result = resume_fn(gate_id, answer)
        except Exception as exc:
            return _error_result(result, auto_answers, rounds_used,
                                 f"could not resume gate {gate_id!r}: {exc}", pending)


def _parse_input(value: str) -> Any:
    """Accept JSON input when supplied, otherwise hand a plain text input through."""
    try:
        return json.loads(value)
    except ValueError:
        return value


def _live_models(artifact, state_dir: str, timeout: float) -> ModelSet:
    """Create the thin real-agent ModelSet boundary used only by the CLI.

    ``drive`` remains independent of this wiring.  The worker deliberately uses
    the same full Hermes-agent dispatch contract as ask's other live entrypoints;
    prompt-runtime supplies the conversation and retains its own durable state.
    The durable state directory is deliberately not passed as the dispatcher's
    working directory: journal_store locks it to mode 0700, and Hermes core's
    context-file/git-root discovery can raise PermissionError while inspecting
    such a cwd.  Model tools have no requirement to operate in that state store.
    """
    del state_dir
    model = artifact.model or resolve_alias("deepseek")
    provider = artifact.provider or DEFAULT_PROVIDER

    def worker(conversation, request_id=None):
        del request_id
        prompt = "\n\n".join(
            "%s: %s" % (message.get("role", "user"), message.get("content", ""))
            for message in conversation
        )
        from model_utils import dispatch_single
        dispatched = dispatch_single(model, prompt, "", "all", None, timeout, provider)
        content = dispatched.get("content")
        if not isinstance(content, str):
            raise RuntimeError(dispatched.get("error") or "empty workflow-agent response")
        return content

    return ModelSet(worker=worker, worker_identity=model, provider_identity=provider)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flow", required=True, help="prompt-workflow artifact path")
    parser.add_argument("--state-dir", required=True, help="durable workflow state directory")
    parser.add_argument("--input", default="{}", help="workflow input (JSON when valid, else text)")
    parser.add_argument(
        "--auto-answer", nargs="?", const=resolve_alias("deepseek"), default=None,
        metavar="ANSWER_MODEL",
        help="answer suspended gates with ANSWER_MODEL (default: deepseek, the strongest reasoner)",
    )
    parser.add_argument("--json", action="store_true", help="emit the complete driver result as JSON")
    parser.add_argument("--emit-events", action="store_true",
                        help="emit control-plane events as JSONL on stderr")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"per-model timeout in seconds (default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args(argv)

    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    try:
        artifact = read_prompt_spec(args.flow)
        models = _live_models(artifact, args.state_dir, args.timeout)
        catalog = {(artifact.workflow, artifact.version): artifact}
        input_value = _parse_input(args.input)
    except Exception as exc:
        result = {
            "status": "error", "exit_code": 1, "result": None, "pending": None,
            "auto_answers": [], "rounds_used": 0, "error": str(exc),
        }
    else:
        callback = _make_stderr_event_callback() if args.emit_events else None
        result = drive(
            lambda: run_workflow(artifact, input_value, args.state_dir,
                                 models=models, catalog=catalog),
            lambda: inspect_workflow(args.state_dir),
            lambda gate_id, answer: resume_workflow(
                artifact, args.state_dir, gate_id, answer, models=models, catalog=catalog
            ),
            auto_answer=args.auto_answer is not None,
            answer_model=resolve_alias(args.auto_answer) if args.auto_answer else None,
            progress_callback=callback,
            run_dir=args.state_dir,
            answer_timeout=args.timeout,
        )

    if args.json:
        print(json.dumps(result, default=str, sort_keys=True))
    else:
        print(json.dumps({key: result[key] for key in ("status", "pending", "auto_answers")},
                         default=str, sort_keys=True))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
