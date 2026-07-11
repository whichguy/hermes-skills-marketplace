#!/usr/bin/env python3
"""pipeline — SDLC pipeline wrapper: triage → routing → dispatch → output.

Chains the three-stage skill ecosystem into a single CLI entry point:
1. triage.py classifies the user message into one of 11 categories (~0.5s)
2. routing.py maps the category to a dispatch decision (skill, model, thinking)
3. ask.py dispatches the model via hermes chat -q (or handles inline)

# Architecture
    User message → triage.classify() → routing.route() → dispatch → output
                         ↓                    ↓              ↓
                    Ollama API          COST_TIERS      model_utils
                    (gemma4:12b)        ROUTING_TABLE   dispatch_single

# Usage
    # Auto-route a message through the full pipeline
    python3 pipeline.py "Build a REST API"

    # Dry-run (show triage + routing without dispatching)
    python3 pipeline.py "Build a REST API" --dry-run

    # With cost budget override
    python3 pipeline.py "Debug this error" --cost-budget free

    # JSON output mode for programmatic consumption
    python3 pipeline.py "What is ACID?" --json

Exit codes: 0 = success, 1 = routing/dispatch/delivery failure,
2 = devloop needs human review.
"""

import argparse
import json
import os
import sys
import time
from typing import Optional

# Add scripts and triage to path
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

TRIAGE_DIR = os.path.join(SCRIPTS_DIR, '..', '..', 'triage', 'scripts')
sys.path.insert(0, TRIAGE_DIR)

import triage  # noqa: E402
import routing  # noqa: E402
from model_utils import (  # noqa: E402
    dispatch_single, resolve_alias, DEFAULT_PROVIDER, DEFAULT_TIMEOUT,
    DEFAULT_TOOLSETS, DEFAULT_MAX_TURNS,
    _safe_callback, _make_stderr_event_callback,
    generate_auto_answer, is_question_shaped,
)

# devloop is the SDLC engine for build_code/debug_cascade (the legacy sdlc.* engine was retired after
# the go/no-go spike: 88% auto-solve, 0 false-completes). Imported defensively — the tree-local devloop
# dir is resolved relative to this file; if it can't load (devloop_bridge=None) build/debug fall through
# to a single model dispatch. DEVLOOP_ENABLED is a kill-switch that DEFAULTS ON; set it 0 to disable.
devloop_bridge = None
DEVLOOP_IMPORT_ERROR = None
try:
    import os as _os  # noqa: E402
    import sys as _sys  # noqa: E402
    _dl_dir = _os.environ.get("DEVLOOP_DIR") or _os.path.normpath(_os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)), "..", "..", "..", "software-development", "devloop"))
    if _dl_dir not in _sys.path:
        _sys.path.insert(0, _dl_dir)
    import devloop_bridge  # noqa: E402
except Exception as _dl_err:
    devloop_bridge = None
    DEVLOOP_IMPORT_ERROR = f"{type(_dl_err).__name__}: {_dl_err}"


def run_pipeline(message: str, cost_budget: str = 'medium',
                 dry_run: bool = False, json_output: bool = False,
                 timeout: int = DEFAULT_TIMEOUT, max_turns: Optional[int] = DEFAULT_MAX_TURNS,
                 toolsets: str = None, max_retries: int = 1,
                 resume_session: str = None,
                 progress_callback=None,
                 auto_answer: bool = False,
                 answer_model: str = None) -> dict:
    """Run the full SDLC pipeline: triage → routing → dispatch.

    Args:
        message: The user message to classify and dispatch.
        cost_budget: Cost budget for model selection (free/low/medium/high).
        dry_run: If True, skip triage API call and dispatch — return routing only.
        json_output: If True, format output as JSON (for programmatic consumption).
        timeout: Per-dispatch-attempt timeout in seconds (the subprocess timeout in
            dispatch_single). With retries, the dispatch stage can take up to
            (max_retries + 1) × timeout wall-clock; default is DEFAULT_TIMEOUT (3600).
        max_turns: Max agent turns for dispatch.
        toolsets: Override toolsets (default: from routing decision).
        max_retries: Number of times to retry dispatch on transient API errors (P1).
        progress_callback: Optional callable receiving structured progress events.
        auto_answer: If True, answer up to two question-shaped model replies and
            resume the same non-devloop agent session.
        answer_model: Optional model for generating those answers. When omitted,
            uses the model selected by this pipeline's routing decision.

    Returns:
        Dict with keys:
            - message (str): The input message.
            - triage_result (dict): Raw triage classification result.
            - routing_decision (dict): Routing decision from route().
            - dispatch_result (dict|None): Model dispatch result, or None if inline/dry-run.
            - pipeline_elapsed (float): Total wall-clock seconds.
            - pipeline_success (bool): True if all stages succeeded (including dispatch).
            - error (str|None): Error message if any stage failed.
            - pipeline_status (str): 'success', 'needs_human', 'delivery_failed',
              'routing_failed', or 'dispatch_failed'.
            - pipeline_exit_code (int): Process exit code for this outcome. Devloop
              uses 2 for HUMAN_REVIEW and 1 for delivery/runtime failures.
            - dispatch_retries (int): Number of dispatch retries performed (P1).

    Side Effects:
        - HTTP POST to Ollama API via triage.classify() (~0.5s).
        - Spawns hermes chat subprocess via dispatch_single() if not dry-run/inline.
        - Logs to ~/.hermes/pipeline-events.jsonl via log_pipeline_event().
    """
    start = time.time()
    error = None
    dispatch_result = None
    auto_answers = [] if auto_answer else None
    pending_question = None

    # ── Stage 1: Triage ──────────────────────────────────────────────
    if dry_run:
        triage_result = {
            'category': 'general_chat',
            'confidence': 'high',
            'raw_output': '(dry-run)',
            'tokens': 0,
            'elapsed': 0,
            'elapsed_first': 0.0,
            'elapsed_retry': 0.0,
        }
    else:
        triage_result = triage.classify(message, timeout=triage.DEFAULT_TIMEOUT)

    _safe_callback(progress_callback, {
        'event': 'triage_done',
        'category': triage_result.get('category'),
        'confidence': triage_result.get('confidence'),
    })

    # ── Stage 2: Routing ──────────────────────────────────────────────
    try:
        routing_decision = routing.route(
            triage_result,
            user_context={'cost_budget': cost_budget},
        )
    except (ValueError, KeyError) as e:
        routing_decision = {'skill': None, 'model': None, 'thinking': None,
                            'toolsets': None, 'role': None, 'error': str(e)}
        error = f"Routing failed: {e}"

    # P4: Triage confidence override — if triage returned a non-code category
    # (general_chat, urgent_action) but the message contains code keywords,
    # override to build_code so the pipeline dispatches to a coding skill.
    _CODE_KEYWORDS = ('def ', 'function', 'class ', 'script', 'python',
                      'write a', 'build a', 'implement', 'algorithm',
                      'fibonacci', 'palindrome', 'fizzbuzz', 'factorial')
    triage_cat = triage_result.get('category', '')
    if not dry_run and not error:
        skill_val = routing_decision.get('skill')
        if skill_val is None and triage_cat in ('general_chat', 'urgent_action', 'status_check'):
            keyword_hits = sum(1 for kw in _CODE_KEYWORDS if kw in message.lower())
            if keyword_hits >= 2:
                # Override: re-route as build_code
                override_triage = {**triage_result, 'category': 'build_code', 'confidence': 'low'}
                try:
                    routing_decision = routing.route(
                        override_triage,
                        user_context={'cost_budget': cost_budget},
                    )
                    routing_decision['_overridden'] = True  # Flag for observability
                except (ValueError, KeyError):
                    pass  # Keep original inline routing if override fails

    _safe_callback(progress_callback, {
        'event': 'routing_decision',
        'skill': routing_decision.get('skill'),
        'model': routing_decision.get('model'),
        'thinking': routing_decision.get('thinking'),
        'toolsets': routing_decision.get('toolsets'),
    })

    # ── Stage 3: Dispatch (or inline) ────────────────────────────────
    skill = routing_decision.get('skill')
    model = routing_decision.get('model')
    thinking = routing_decision.get('thinking')
    role = routing_decision.get('role')  # P2: pass role to dispatch
    pipeline_mode = routing_decision.get('pipeline')  # P9: test_first or debug_cascade
    dispatch_toolsets = toolsets or routing_decision.get('toolsets', DEFAULT_TOOLSETS)
    dispatch_retries = 0  # P1: track retry count
    devloop_dispatched = False

    # Route build_code/debug_cascade to the devloop engine when the routing decision indicates it.
    if not dry_run and not error and pipeline_mode and skill is not None:
        # devloop is the SDLC engine: build/debug route to it (returning a reviewable branch summary,
        # not inline code). THREE-WAY split, fail-closed (deep review 2026-07-01):
        #   import-broke -> a FAILED dispatch_result. A test_first/debug request must NEVER silently
        #                   degrade to an unverified single-shot labeled success (that was a live
        #                   0-false-complete violation);
        #   kill-switch  -> DEVLOOP_ENABLED=0 is the ONE intentional single-shot fallback;
        #   live         -> through devloop_bridge.call_guarded, so a devloop RUNTIME exception also
        #                   fails closed (HUMAN_REVIEW-shaped error) instead of crashing the pipeline.
        if devloop_bridge is None:
            _reason = f"devloop unavailable (import failed: {DEVLOOP_IMPORT_ERROR}); refusing to silently degrade a {pipeline_mode} request to single-shot"
            dispatch_result = {
                'content': _reason, 'session_id': None, 'elapsed': 0.0, 'error': _reason,
                'devloop_result': {'terminal': 'HUMAN_REVIEW', 'reason': _reason},
                'pipeline_mode': pipeline_mode,
            }
        elif not devloop_bridge.devloop_enabled():
            pipeline_mode = None    # operator kill-switch — intentional single-shot fallback
        elif pipeline_mode == 'test_first':
            # repo=SCRATCH explicitly: a chat-originated build works in a fresh scratch workspace,
            # never the process cwd (which can be inside the ~/.hermes data repo itself).
            devloop_dispatched = True
            _safe_callback(progress_callback, {
                'event': 'devloop_start', 'pipeline_mode': pipeline_mode,
            })
            dispatch_result = devloop_bridge.call_guarded(
                devloop_bridge.run_build, message, timeout=timeout, repo=devloop_bridge.SCRATCH)
            _safe_callback(progress_callback, {
                'event': 'devloop_end', 'pipeline_mode': pipeline_mode,
                'terminal': (dispatch_result.get('devloop_result') or {}).get('terminal'),
            })
        elif pipeline_mode == 'debug_cascade':
            devloop_dispatched = True
            _safe_callback(progress_callback, {
                'event': 'devloop_start', 'pipeline_mode': pipeline_mode,
            })
            dispatch_result = devloop_bridge.call_guarded(
                devloop_bridge.run_debug, message, timeout=timeout, repo=devloop_bridge.SCRATCH)
            _safe_callback(progress_callback, {
                'event': 'devloop_end', 'pipeline_mode': pipeline_mode,
                'terminal': (dispatch_result.get('devloop_result') or {}).get('terminal'),
            })
        else:
            pipeline_mode = None    # unknown pipeline mode -> single dispatch

    if not dry_run and not pipeline_mode and skill is not None and not error:
        # Dispatch to model via hermes chat subprocess.
        # Resolve alias to full model name — routing returns aliases (e.g., 'deepseek')
        # but hermes chat -m expects full model names (e.g., 'deepseek-v4-pro:cloud').
        resolved_model = resolve_alias(model) if model else model
        dispatch_retries = 0

        # P3: Prompt augmentation for code generation tasks.
        # When the dev skill is selected AND role is not 'debugger', append a
        # directive requesting self-contained code output. This prevents the model
        # from outputting code-review diffs or using file tools instead of writing code.
        # P0-A FIX: Do NOT augment when role='debugger' — the debugger directive says
        # "Focus on finding and fixing bugs, not writing new code" which directly
        # contradicts "Output a self-contained Python script". This contradiction
        # caused the model to output just the answer (e.g., "True\nFalse") instead
        # of the actual code.
        dispatch_prompt = message
        if skill == 'dev' and role != 'debugger':
            # P1-B: Detect requested language from the message; default to Python.
            msg_lower = message.lower()
            if any(lang in msg_lower for lang in ('bash', 'shell', 'sh script')):
                code_lang = 'bash'
            elif any(lang in msg_lower for lang in ('javascript', 'js ', 'node', 'npm')):
                code_lang = 'javascript'
            elif any(lang in msg_lower for lang in ('sql', 'query', 'select ', 'postgres')):
                code_lang = 'sql'
            else:
                code_lang = 'python'
            dispatch_prompt = (
                message + "\n\n"
                f"Output your solution as a self-contained {code_lang} script in a "
                f"```{code_lang} code block. Do not use file tools or write to disk."
            )
            # P1-C: Narrow toolsets — P3 says "Do not use file tools" but routing
            # gives dev skill 'file,web,terminal'. Remove file and terminal to
            # match the prompt directive.
            # NOTE: Only narrow when toolsets came from routing (not user override).
            if dispatch_toolsets and not toolsets:
                dispatch_toolsets = ','.join(
                    t for t in dispatch_toolsets.split(',') if t not in ('file', 'terminal')
                ) or 'web'

        # P1: Retry on transient API errors (429 rate limits, connection refused, etc.)
        for attempt in range(max_retries + 1):
            dispatch_result = dispatch_single(
                model=resolved_model,
                prompt=dispatch_prompt,  # P3: augmented prompt for dev skill
                context='',
                toolsets=dispatch_toolsets,
                max_turns=max_turns,
                timeout=timeout,
                provider=DEFAULT_PROVIDER,
                thinking=thinking,
                role=role,  # P2: pass routing role to dispatch
                resume_session=resume_session if attempt == 0 else None,  # P6: only first attempt
                progress_callback=progress_callback,
            )
            # Check if the error is a transient API error worth retrying
            dispatch_err = dispatch_result.get('error', '') or ''
            is_transient = any(p in dispatch_err.lower() for p in
                             ('api error', '429', 'rate limit', 'connection refused',
                              'timeout', 'timed out', 'empty output (exit 0)'))
            if not is_transient or attempt >= max_retries:
                break  # Either success, non-transient error, or out of retries
            # Brief delay before retry (simple backoff)
            print(
                f"pipeline: transient dispatch error (attempt {attempt + 1}/{max_retries + 1} failed), "
                f"retrying: {dispatch_err[:120]}",
                file=sys.stderr,
            )
            _safe_callback(progress_callback, {
                'event': 'dispatch_retry',
                'attempt': attempt + 1,
                'reason': dispatch_err[:200],
            })
            time.sleep(2 ** attempt)
            dispatch_retries += 1

        # P15-8: Mark retried on the FINAL result, not the intermediate one.
        if dispatch_retries > 0 and isinstance(dispatch_result, dict):
            dispatch_result['retried'] = True

        # Free-text clarification seam. This runs only for the ordinary
        # single-model dispatch path above: devloop and inline responses do not
        # enter this branch and retain their existing contracts.
        if (
            auto_answer
            and dispatch_result.get('error') is None
            and dispatch_result.get('content')
            and is_question_shaped(dispatch_result['content'])
        ):
            selected_answer_model = (
                resolve_alias(answer_model) if answer_model else resolved_model
            )
            rounds_used = 0
            while (
                dispatch_result.get('error') is None
                and dispatch_result.get('content')
                and is_question_shaped(dispatch_result['content'])
                and rounds_used < 2
            ):
                session_id = dispatch_result.get('session_id')
                if not session_id:
                    pending_question = dispatch_result['content']
                    break

                generated = generate_auto_answer(
                    dispatch_result['content'],
                    context=message,
                    answer_model=selected_answer_model,
                    provider=DEFAULT_PROVIDER,
                    timeout=timeout,
                    progress_callback=progress_callback,
                )
                answer = generated.get('answer')
                if not answer:
                    pending_question = dispatch_result['content']
                    break

                rounds_used += 1
                event = {
                    'event': 'auto_answer',
                    'question': dispatch_result['content'],
                    'answer': answer,
                    'round': rounds_used,
                    'seam': 'freetext',
                }
                auto_answers.append(event)
                _safe_callback(progress_callback, event)

                dispatch_result = dispatch_single(
                    model=resolved_model,
                    prompt=answer,
                    context='',
                    toolsets=dispatch_toolsets,
                    max_turns=max_turns,
                    timeout=timeout,
                    provider=DEFAULT_PROVIDER,
                    thinking=thinking,
                    role=role,
                    resume_session=session_id,
                    progress_callback=progress_callback,
                )

            if (
                dispatch_result.get('error') is None
                and dispatch_result.get('content')
                and is_question_shaped(dispatch_result['content'])
            ):
                pending_question = dispatch_result['content']

    elif not dry_run and skill is None and not error:
        # Inline response — no model dispatch needed
        dispatch_result = {
            'content': None,
            'session_id': None,
            'elapsed': 0,
            'error': None,
            'inline': True,
            'message': f"Category '{triage_result.get('category')}' handled inline (no skill dispatch).",
        }

    # ── Determine final status ────────────────────────────────────────
    # HUMAN_REVIEW deliberately has error=None, while an undelivered COMPLETE can still carry a
    # reviewable branch. Delegate those semantics to devloop's shared outcome classifier.
    if devloop_dispatched:
        outcome = devloop_bridge.classify_outcome(
            dispatch_result, requested_keep_branch=False)
        pipeline_success = outcome['success']
        pipeline_status = outcome['pipeline_status']
        pipeline_error = outcome['error']
        pipeline_exit_code = outcome['exit_code']
    else:
        # Preserve the existing routing/dispatch contract outside devloop.
        dispatch_error = dispatch_result.get('error') if dispatch_result else None
        pipeline_error = error or dispatch_error
        pipeline_success = pipeline_error is None
        pipeline_status = (
            'success' if pipeline_error is None
            else 'routing_failed' if error
            else 'dispatch_failed'
        )
        pipeline_exit_code = 0 if pipeline_success else 1

    # A free-text question left unanswered after the bounded automatic rounds
    # is a control-plane handoff, not a model-dispatch error.
    if pending_question is not None:
        pipeline_success = False
        pipeline_status = 'needs_human'
        pipeline_error = None
        pipeline_exit_code = 2

    # Log the exact same outcome that the API returns and the CLI exits with.
    if not dry_run:
        routing.log_pipeline_event(
            triage_result=triage_result,
            routing_decision=routing_decision,
            model_used=model,
            latency=time.time() - start,
            token_count=triage_result.get('tokens', 0),
            success=pipeline_success,
        )

    elapsed = time.time() - start
    result = {
        'message': message,
        'triage_result': triage_result,
        'routing_decision': routing_decision,
        'dispatch_result': dispatch_result,
        'pipeline_elapsed': round(elapsed, 3),
        'pipeline_success': pipeline_success,
        'error': pipeline_error,
        'pipeline_status': pipeline_status,
        'pipeline_exit_code': pipeline_exit_code,
        'dispatch_retries': dispatch_retries,
    }
    if auto_answer:
        result['auto_answers'] = auto_answers
    if pending_question is not None:
        result['pending_question'] = pending_question
    return result


def iterate(message: str, error_feedback: str,
            prev_session_id: str = None, prev_code: str = None,
            **kwargs) -> dict:
    """Run a pipeline iteration with error feedback (P6).

    Feeds the error from a previous attempt back through the pipeline so the
    model can fix its code. If prev_session_id is provided, the model has
    context from the previous attempt.

    Args:
        message: The original user message/idea.
        error_feedback: Error output from the previous execution attempt.
        prev_session_id: Session ID from the previous dispatch (optional).
        prev_code: The code from the previous attempt (optional, P2-A).
            When provided, the model can fix it directly instead of guessing.
        **kwargs: Passed through to run_pipeline() (cost_budget, timeout, etc.).

    Returns:
        Same dict as run_pipeline().
    """
    # P2-A: Structured prompt with previous code so the model can fix it
    # directly instead of guessing what to write.
    parts = [f"## Original Request\n{message}"]
    if prev_code:
        parts.append(f"## Previous Code\n```python\n{prev_code}\n```")
    parts.append(f"## Error Output\n{error_feedback}")
    parts.append("## Instructions\nFix the code so it produces the correct output.")
    prompt = "\n\n".join(parts)
    return run_pipeline(prompt, resume_session=prev_session_id, **kwargs)


def main():
    """CLI entry point for the SDLC pipeline.

    Usage:
        python3 pipeline.py "Build a REST API"
        python3 pipeline.py "Debug this error" --cost-budget free
        python3 pipeline.py "What is ACID?" --dry-run
        python3 pipeline.py "hello" --json
    """
    parser = argparse.ArgumentParser(
        description="pipeline — SDLC pipeline: triage → routing → dispatch"
    )
    parser.add_argument('message', help='Message to classify, route, and dispatch')
    parser.add_argument('--cost-budget', choices=['free', 'low', 'medium', 'high'],
                        default='medium',
                        help='Cost budget for model selection (default: medium)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Skip triage API call and dispatch — show routing only')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON (for programmatic consumption)')
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT,
                        help=f'Dispatch timeout in seconds (default: {DEFAULT_TIMEOUT})')
    parser.add_argument('--max-turns', type=int, default=DEFAULT_MAX_TURNS,
                        help='Max agent turns (default: Hermes config)')
    parser.add_argument('--toolsets', default=None,
                        help='Override toolsets (default: from routing decision)')
    parser.add_argument('--emit-events', action='store_true',
                        help='Emit JSONL progress events to stderr')
    parser.add_argument(
        '--auto-answer', nargs='?', const=None, default=False,
        metavar='ANSWER_MODEL',
        help=('Automatically answer up to two clarifying questions in a regular '
              'agent session. Without ANSWER_MODEL, uses the routed model.'),
    )
    args = parser.parse_args()

    auto_answer_enabled = args.auto_answer is not False
    answer_model = args.auto_answer if auto_answer_enabled else None

    result = run_pipeline(
        message=args.message,
        cost_budget=args.cost_budget,
        dry_run=args.dry_run,
        json_output=args.json,
        timeout=args.timeout,
        max_turns=args.max_turns,
        toolsets=args.toolsets,
        progress_callback=_make_stderr_event_callback() if args.emit_events else None,
        auto_answer=auto_answer_enabled,
        answer_model=answer_model,
    )

    if args.json:
        # JSON output — print the full result dict
        print(json.dumps(result, indent=2, default=str))
    else:
        # Human-readable output
        triage_r = result['triage_result']
        routing_r = result['routing_decision']
        dispatch_r = result['dispatch_result']

        print(f"┌─ Stage 1: Triage")
        print(f"│  Category:  {triage_r.get('category', '?')}")
        print(f"│  Confidence: {triage_r.get('confidence', '?')}")
        print(f"│  Elapsed:  {triage_r.get('elapsed', 0)}s")

        print(f"├─ Stage 2: Routing")
        print(f"│  Skill:    {routing_r.get('skill', 'None (inline)')}")
        print(f"│  Model:    {routing_r.get('model', 'N/A')}")
        print(f"│  Thinking: {routing_r.get('thinking', 'N/A')}")
        print(f"│  Toolsets: {routing_r.get('toolsets', 'N/A')}")

        if dispatch_r:
            print(f"├─ Stage 3: Dispatch")
            if dispatch_r.get('inline'):
                print(f"│  (Inline — no model dispatch)")
            elif dispatch_r.get('content'):
                print(f"│  Content:  {len(dispatch_r['content'])} chars")
                print(f"│  Elapsed:  {dispatch_r.get('elapsed', 0):.1f}s")
            else:
                print(f"│  Error:    {dispatch_r.get('error', 'Unknown')}")

        print(f"└─ Pipeline: {'✅' if result['pipeline_success'] else '❌'} "
              f"{result['pipeline_elapsed']:.3f}s total")

        if result['error']:
            print(f"\nError: {result['error']}", file=sys.stderr)
        elif result.get('pending_question'):
            print(
                f"\nHuman answer required: {result['pending_question']}",
                file=sys.stderr,
            )

    sys.exit(result.get('pipeline_exit_code', 0 if result['pipeline_success'] else 1))


if __name__ == '__main__':
    main()
