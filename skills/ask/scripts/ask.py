#!/usr/bin/env python3
"""ask — Prompt any model or alias. Captures session ID for follow-ups.

Improvements over prompt_model.py:
- Alias resolution: "deepseek" → deepseek-v4-pro:cloud, "kimi" → kimi-k2.7-code:cloud
- Session capture: extracts session_id from hermes chat output, writes to registry
- Comparison mode: "ask deepseek kimi glm <question>" dispatches N models in parallel
- Inline output: prints to stdout with model badge (no -o needed for conversational use)
- File output: still supported with -o (includes metadata header)

Usage:
    # Single model by alias
    python3 ask.py deepseek "What is ACID compliance?"
    python3 ask.py kimi "Review this code for bugs" --context "$(cat auth.py)"

    # By full model name (still works)
    python3 ask.py deepseek-v4-pro:cloud "Design a REST API"

    # Comparison mode — multiple aliases/models
    python3 ask.py deepseek kimi qwen "Should we use PostgreSQL or MongoDB?"
    python3 ask.py --models deepseek,kimi --prompt "Same question"

    # With file output (metadata header included)
    python3 ask.py deepseek "Plan the architecture" -o /tmp/plan.md

    # With working directory (for models with file/terminal tools)
    python3 ask.py kimi "Review the code" --cwd /opt/data/projects/myproject

    # With structured events to stderr (for programmatic callers)
    python3 ask.py deepseek "Design an API" --emit-events 2>events.jsonl

    # Session registry
    python3 ask.py --sessions          # list all active sessions
    python3 ask.py --session deepseek  # show session for an alias

Exit codes: 0 = success, 1 = error, 2 = timeout, 3 = no models available.

# Interaction Contract

    Ask is a dumb pipe — it forwards prompts to models and returns responses.
    It does NOT orchestrate, evaluate, or manage state between calls.

    ## Which dispatch function to use?

    | Use case                              | Function               | Notes                          |
    |---------------------------------------|------------------------|--------------------------------|
    | Single model, full agent loop         | dispatch_single()      | Standard for ask CLI           |
    | Comparison (2+ models), same prompt    | dispatch_comparison()  | Parallel if no --thinking      |
    | Fast inference, raw Ollama (~0.5s)    | dispatch_single_raw()  | No tools/skills, no agent loop |

    ## progress_callback events

    | Event           | Keys                              | When emitted                  |
    |-----------------|-----------------------------------|-------------------------------|
    | dispatch_start  | model, role, thinking, timestamp  | Before hermes chat / HTTP     |
    | dispatch_end    | model, elapsed, success, chars     | After hermes chat / HTTP      |

    ## What ask IS and IS NOT

    - Ask IS:  A dumb pipe that forwards prompts to models via hermes chat or Ollama API
    - Ask IS NOT: A stateful orchestrator (devloop has that — see skills/software-development/devloop/)
    - Ask IS NOT: An event emitter (use model_utils directly for callbacks)

    For SDLC orchestration, use pipeline.py (build/debug route to the devloop engine), not ask.
    For programmatic use, import from model_utils, not ask.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional, Callable

# ── Add model_utils.py to path for direct imports ───────────────────────────
# NOTE: sys.path.insert expects a DIRECTORY, not a file path. Use dirname()
#       to get the directory containing model_utils.py.
sys.path.insert(0, os.path.dirname(__file__))

from model_utils import (
    clean_output,
    build_prompt,
    NON_ENGLISH_MODELS,
    needs_no_think,
    resolve_alias,
    resolve_alias_fuzzy,
    dispatch_single,  # L1: Import directly — no wrapper needed
    dispatch_comparison,  # Consolidated: use model_utils version (has progress_callback forwarding)
    _safe_callback,  # For raw mode event emission
    _make_stderr_event_callback,  # Compatibility re-export for --emit-events callers
    clean_expired_sessions,
    get_reasoning_effort,
    set_reasoning_effort,
    save_session,
    get_session,
    DEFAULT_PROVIDER,
    DEFAULT_TIMEOUT,
    DEFAULT_TOOLSETS,
    DEFAULT_MAX_TURNS,
    HERMES_BIN,
    ALIASES,
    THINKING_LEVELS,
    is_known_model,
    is_question_shaped,
    generate_auto_answer,
)

# Re-export SESSIONS_FILE for backward compatibility with tests
SESSIONS_FILE = os.path.expanduser("~/.hermes/ask-sessions.json")


# L1: dispatch_single is imported directly from model_utils — no wrapper needed.
# Tests that previously patched ask._dispatch_agent should patch ask.dispatch_single.


def _alias_for_model(model: str) -> Optional[str]:
    """Return the alias key for a full model name, or None.

    Args:
        model: Full model name (e.g., "deepseek-v4-pro:cloud").
    Returns:
        Alias key (e.g., "deepseek") or None if no alias maps to this model.
    Side Effects: None — pure function, reads static ALIASES dict.
    """
    for k, v in ALIASES.items():
        if v == model:
            return k
    return None


def dispatch_single_raw(model: str, prompt: str, context: str, provider: str,
                        timeout: int = 60,
                        progress_callback: Optional[Callable] = None) -> dict:
    """Dispatch a single model call via direct Ollama API.

    No hermes chat subprocess — ~0.5s instead of ~30s.
    No agent loop, no tools, no skills — just raw model inference.

    Args:
        model: Full model name (e.g., "gemma4:12b-mlx-bf16").
        prompt: The prompt text.
        context: Optional context appended via build_prompt().
        provider: Provider name (unused in raw mode — always hits Ollama directly).
        timeout: HTTP request timeout in seconds.
        progress_callback: Optional callback for dispatch events.

    Returns:
        Dict with keys: content, elapsed, error.

    Side Effects:
        - HTTP POST to Ollama API at host.docker.internal:11434.

    # NOTE: This function is used when --mode raw is specified in ask.py.
    """
    # PERF: ~63x faster than agent mode (0.5s vs 30s) — no subprocess, no tools.
    _safe_callback(progress_callback, {
        'event': 'dispatch_start', 'model': model,
        'role': None, 'thinking': 'raw',
        'timestamp': time.time(),
    })

    start = time.time()  # Set early so error path always has a valid start time
    try:
        # Build prompt with /no_think prefix for Qwen models + English directive for non-English models
        english_only = model in NON_ENGLISH_MODELS
        full_prompt = build_prompt(prompt, context, model, english_only=english_only)

        ollama_url = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434/api/chat")
        data = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": full_prompt}],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.1, "num_predict": 512}
        }).encode("utf-8")

        req = urllib.request.Request(
            ollama_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - start
            content = result["message"]["content"].strip()

        _safe_callback(progress_callback, {
            'event': 'dispatch_end', 'model': model,
            'elapsed': elapsed, 'success': True,
            'chars': len(content), 'error': None,
        })

        return {
            "content": content,
            "session_id": None,
            "elapsed": elapsed,
            "error": None,
        }
    except Exception as e:
        elapsed = time.time() - start
        _safe_callback(progress_callback, {
            'event': 'dispatch_end', 'model': model,
            'elapsed': elapsed, 'success': False,
            'chars': 0, 'error': str(e),
        })
        return {
            "content": None,
            "session_id": None,
            "elapsed": elapsed,
            "error": str(e),
        }


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="ask — prompt any model or alias, with session capture and comparison mode"
    )
    # Positional: model alias(es) and prompt
    parser.add_argument("args", nargs="*", help="Model alias(es) followed by the prompt")
    # Explicit --prompt flag (use when prompt contains -- or special chars)
    parser.add_argument("-p", "--prompt", help="Prompt text (use when prompt contains -- or special chars)")
    # Models via --models flag (alternative to positional)
    parser.add_argument("--models", help="Comma-separated model aliases (alternative to positional)")
    parser.add_argument("--context", default="", help="Context to include")
    parser.add_argument("-c", "--context-file", help="Read context from file")
    parser.add_argument("-o", "--output", help="Output file (single model only)")
    parser.add_argument("-t", "--toolsets", default=DEFAULT_TOOLSETS, help=f"Toolsets (default: {DEFAULT_TOOLSETS})")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS, help="Max agent turns (default: Hermes config)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"Timeout seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, help=f"Provider (default: {DEFAULT_PROVIDER})")
    parser.add_argument("--cwd", default=None, help="Working directory for the model's file/terminal tools (single model only)")
    parser.add_argument("--mode", choices=["agent", "raw"], default="agent",
                        help="Execution mode: 'agent' uses hermes chat subprocess; 'raw' uses direct Ollama API (~0.5s). Use --mode agent for tasks requiring tools (file, web) or skills. Use --mode raw only for pure inference without tool access.")
    parser.add_argument("--thinking", choices=list(THINKING_LEVELS.keys()),
                        help="Reasoning effort level (none/minimal/low/medium/high/xhigh). Sets agent.reasoning_effort for this call, restores after.")
    parser.add_argument("--emit-events", action="store_true",
                        help="Emit structured JSON events to stderr (for programmatic callers)")
    parser.add_argument("--resume", metavar="SESSION_ID", help="Resume a previous session by ID")
    parser.add_argument("--sessions", action="store_true", help="List all saved sessions")
    parser.add_argument("--session", metavar="ALIAS", help="Show session info for an alias")
    parser.add_argument("--clean-sessions", action="store_true", help="Remove expired sessions (TTL: 1 hour)")
    parser.add_argument(
        "--auto-answer", nargs="?", const=None, default=False,
        metavar="ANSWER_MODEL",
        help=("Automatically answer up to two clarifying questions in a single-model "
              "agent session. Without ANSWER_MODEL, uses the primary model being asked."),
    )
    # Use parse_known_args so unknown --flags in positional args don't crash
    args, unknown = parser.parse_known_args()

    # ── Session housekeeping ───────────────────────────────────────────
    if args.clean_sessions:
        removed = clean_expired_sessions()
        print(f"Cleaned {removed} expired session(s).")
        return

    # ── Build progress_callback ────────────────────────────────────────
    progress_callback = _make_stderr_event_callback() if args.emit_events else None

    # ── Mode selection ───────────────────────────────────────────────────
    if args.auto_answer is not False and args.mode == "raw":
        parser.error("--auto-answer is available only in single-model --mode agent dispatch")

    if args.mode == "raw":
        return _run_raw_mode(args, unknown, progress_callback=progress_callback)
    else:
        return _run_agent_mode(args, unknown, progress_callback=progress_callback)


def _handle_session_commands(args) -> bool:
    """Handle --sessions and --session CLI commands.

    Args:
        args: Parsed argparse Namespace with .sessions and .session attributes.

    Returns:
        True if a session command was handled (caller should return immediately).
        False if no session command was active.

    Side Effects:
        - Reads SESSIONS_FILE from disk for --sessions listing.
        - Prints session info to stdout.
    """
    if args.sessions:
        sessions_file = os.path.expanduser("~/.hermes/ask-sessions.json")
        if os.path.exists(sessions_file):
            registry = json.load(open(sessions_file))
            if not registry:
                print("No saved sessions.")
                return True
            print(f"Saved sessions ({len(registry)}):\n")
            for alias, info in registry.items():
                print(f"  {alias:<15} {info['model']:<30} session: {info['session_id']}")
                print(f"  {'':15} preview: {info.get('prompt_preview','')[:80]}")
                print(f"  {'':15} {info.get('timestamp','')}\n")
        else:
            print("No saved sessions.")
        return True

    if args.session:
        info = get_session(args.session)
        if info:
            print(f"Alias:   {args.session}")
            print(f"Model:   {info['model']}")
            print(f"Session: {info['session_id']}")
            print(f"Preview: {info.get('prompt_preview', '')[:200]}")
            print(f"Time:    {info.get('timestamp', '')}")
        else:
            print(f"No session found for alias '{args.session}'.")
        return True

    return False


def _parse_models_and_prompt(args, unknown):
    """Parse model aliases and prompt from CLI args.

    Supports two modes:
    1. Explicit: --models + --prompt flags
    2. Positional: model aliases followed by prompt text

    Args:
        args: Parsed argparse Namespace with .prompt, .models, .args attributes.
        unknown: Leftover positional args from parse_known_args().

    Returns:
        Tuple of (models_or_aliases, prompt).
        models_or_aliases: List of resolved full model names.
        prompt: The prompt string (may be empty).

    Side Effects: None — pure parsing, no I/O.
    """
    models_or_aliases = []
    prompt = ""

    if args.prompt:
        prompt = args.prompt
        if args.models:
            models_or_aliases = [resolve_alias_fuzzy(m.strip())[0] for m in args.models.split(",")]
        elif args.args:
            for arg in args.args:
                if is_known_model(arg):
                    models_or_aliases.append(resolve_alias(arg))
    else:
        # Positional parsing: models until first non-model arg, rest is prompt
        prompt_parts = []
        found_prompt = False

        all_positional = list(args.args or []) + (unknown or [])

        for arg in all_positional:
            if not found_prompt:
                if is_known_model(arg):
                    models_or_aliases.append(resolve_alias(arg))
                else:
                    found_prompt = True
                    prompt_parts.append(arg)
            else:
                prompt_parts.append(arg)

        # Fuzzy fallback: if no models were recognized positionally, try fuzzy
        # on the first prompt word. This catches "ask minimax-3 What is..."
        # where "minimax-3" isn't an exact alias but fuzzy-matches "minimax-m3".
        if not models_or_aliases and prompt_parts:
            resolved, was_fuzzy = resolve_alias_fuzzy(prompt_parts[0])
            if was_fuzzy:
                models_or_aliases.append(resolved)
                prompt_parts = prompt_parts[1:]  # Remove the matched word from prompt

        prompt = " ".join(prompt_parts)

    return models_or_aliases, prompt


def _resolve_context(args):
    """Resolve context from --context, --context-file, and stdin.

    Args:
        args: Parsed argparse Namespace with .context, .context_file attributes.

    Returns:
        Context string (may be empty).

    Side Effects:
        - Reads --context-file from disk if specified.
        - Reads from stdin if not a TTY.
    """
    context = args.context
    if args.context_file:
        with open(args.context_file) as f:
            context = f.read()
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read().strip()
        if stdin_data:
            context = (context + "\n\n" if context else "") + stdin_data
    return context


def _run_raw_mode(args, unknown=None, progress_callback: Optional[Callable] = None):
    """Run in raw mode: direct Ollama API call, no hermes subprocess.

    Args:
        args: Parsed argparse Namespace with model, prompt, context, etc.
        unknown: Leftover positional args from argparse (default None).
        progress_callback: Optional callback for dispatch events.

    Returns:
        None. Prints model output to stdout, errors to stderr, exits on failure.

    Side Effects:
        - HTTP POST to Ollama API via dispatch_single_raw().
        - Prints to stdout/stderr.

    # PERF: Raw mode is ~63x faster than agent mode (0.5s vs 50s) — no agent loop.
    # NOTE: Raw mode does NOT support comparison (multiple models) or sessions.
    """
    # Session management commands still work
    if _handle_session_commands(args):
        return

    # ── Parse models and prompt ───────────────────────────────────────
    models_or_aliases, prompt = _parse_models_and_prompt(args, unknown)

    if not models_or_aliases:
        print("Error: specify at least one model or alias.", file=sys.stderr)
        print(f"Available aliases: {', '.join(sorted(ALIASES.keys()))}", file=sys.stderr)
        sys.exit(3)

    # Raw mode only supports single model
    if len(models_or_aliases) > 1:
        print("Error: --mode raw does not support comparison mode (multiple models)", file=sys.stderr)
        print("Use --mode agent for comparison mode.", file=sys.stderr)
        sys.exit(1)

    # NOTE: --thinking is not supported in raw mode (it requires the Hermes
    #       agent loop to set agent.reasoning_effort). Warn the user.
    if args.thinking:
        print("Warning: --thinking is ignored in --mode raw "
              "(requires agent loop). Use --mode agent for thinking support.",
              file=sys.stderr)

    model = models_or_aliases[0]
    context = _resolve_context(args)

    # Dispatch via raw Ollama API
    r = dispatch_single_raw(model, prompt, context, args.provider, args.timeout,
                            progress_callback=progress_callback)

    badge = f"🤖 {model} ({r['elapsed']:.1f}s raw)"
    print(f"\n{badge}\n{'='*60}")
    if r["content"]:
        print(r["content"])
    else:
        print(f"Error: {r.get('error', 'Unknown error')}", file=sys.stderr)
        sys.exit(1)


def _run_agent_mode(args, unknown, progress_callback: Optional[Callable] = None):
    """Run in agent mode: hermes chat subprocess (full agent loop with tools/skills).

    Args:
        args: Parsed argparse Namespace with model, prompt, context, thinking, etc.
        unknown: Leftover positional args from argparse.
        progress_callback: Optional callback for dispatch events.

    Returns:
        None. Prints model output to stdout, errors to stderr, exits on failure.

    Side Effects:
        - Spawns hermes chat subprocess via dispatch_single/dispatch_comparison.
        - Mutates global config if --thinking is set (set → call → restore).
        - Writes to SESSIONS_FILE if session ID captured.

    # NOTE: Agent mode supports sessions, comparison, --thinking, and toolsets.
    # RACE: --thinking in comparison mode serializes (global config mutation).
    """
    # ── Session management commands ────────────────────────────────────
    if _handle_session_commands(args):
        return

    # ── Parse models and prompt ───────────────────────────────────────
    models_or_aliases, prompt = _parse_models_and_prompt(args, unknown)

    if not models_or_aliases:
        print("Error: specify at least one model or alias.", file=sys.stderr)
        print(f"Available aliases: {', '.join(sorted(ALIASES.keys()))}", file=sys.stderr)
        sys.exit(3)

    if not prompt:
        print("Error: no prompt provided. Use --prompt for prompts with special chars.", file=sys.stderr)
        sys.exit(1)

    # Resolve context
    context = _resolve_context(args)

    # ── Warn if --cwd is used in comparison mode ───────────────────────
    if getattr(args, 'cwd', None) and len(models_or_aliases) > 1:
        print("Warning: --cwd is ignored in comparison mode (multiple models).",
              file=sys.stderr)

    # ── Comparison mode (multiple models) ──────────────────────────────
    if len(models_or_aliases) > 1:
        if _auto_answer_enabled(args):
            print(
                "Error: --auto-answer is available only for single-model agent dispatch, "
                "not comparison mode.",
                file=sys.stderr,
            )
            sys.exit(1)
        results = dispatch_comparison(
            models_or_aliases, prompt, context, args.toolsets,
            args.max_turns, args.timeout, args.provider, args.thinking,
            progress_callback=progress_callback,
        )

        for r in results:
            model = r["model"]
            if r["content"]:
                badge = f"🤖 {model} (agent)"
                print(f"\n{'='*60}")
                print(f"{badge} ({r['elapsed']:.1f}s)")
                print(f"{'='*60}")
                print(r["content"])
                if r.get("session_id"):
                    alias_key = _alias_for_model(model)
                    if alias_key:
                        save_session(alias_key, model, r["session_id"], prompt)
            else:
                print(f"\n❌ {model}: {r['error']}", file=sys.stderr)

        # Summary line
        succeeded = sum(1 for r in results if r["content"])
        print(f"\n{'─'*60}", file=sys.stderr)
        print(f"{succeeded}/{len(results)} models responded", file=sys.stderr)
        return

    # ── Single model ───────────────────────────────────────────────────
    model = models_or_aliases[0]
    alias_key = _alias_for_model(model)

    # Check for resume session
    resume_id = args.resume
    if not resume_id and alias_key:
        session_info = get_session(alias_key)
        if session_info:
            resume_id = session_info.get("session_id")

    r = dispatch_single(
        model, prompt, context, args.toolsets,
        args.max_turns, args.timeout, args.provider,
        output_file=args.output,
        resume_session=resume_id,
        alias=alias_key,
        thinking=args.thinking,
        progress_callback=progress_callback,
        cwd=getattr(args, 'cwd', None),
    )

    auto_answer_enabled = _auto_answer_enabled(args)
    auto_answers = []
    rounds_used = 0
    answer_model_arg = getattr(args, 'auto_answer', None)
    answer_model = model if answer_model_arg is None else answer_model_arg

    # A clarification is answered in the existing conversation so the dispatched
    # agent retains its prior context. Never start a new session as a fallback:
    # that would silently change the interaction contract.
    while (
        auto_answer_enabled
        and r.get("content")
        and r.get("error") is None
        and is_question_shaped(r["content"])
        and rounds_used < 2
    ):
        session_id = r.get("session_id")
        if not session_id:
            print(
                "ask: clarification needs a human answer because the dispatched "
                "agent did not provide a resumable session ID.",
                file=sys.stderr,
            )
            break

        generated = generate_auto_answer(
            r["content"],
            context=context,
            answer_model=answer_model,
            provider=args.provider,
            timeout=args.timeout,
            progress_callback=progress_callback,
        )
        answer = generated.get("answer")
        if not answer:
            print(
                "ask: automatic clarification answer failed; a human answer is required: "
                f"{generated.get('error', 'unknown error')}",
                file=sys.stderr,
            )
            break

        rounds_used += 1
        event = {
            "event": "auto_answer",
            "question": r["content"],
            "answer": answer,
            "round": rounds_used,
            "seam": "freetext",
        }
        auto_answers.append(event)
        _safe_callback(progress_callback, event)

        r = dispatch_single(
            model, answer, "", args.toolsets,
            args.max_turns, args.timeout, args.provider,
            output_file=args.output,
            resume_session=session_id,
            alias=alias_key,
            thinking=args.thinking,
            progress_callback=progress_callback,
            cwd=getattr(args, 'cwd', None),
        )

    if auto_answer_enabled:
        # Ask is primarily a conversational CLI, but retain the audit data on
        # its final dispatch result for programmatic callers and test seams.
        r["auto_answers"] = auto_answers

    if r["content"]:
        if args.output:
            print(f"✅ {model} → {args.output} ({r['elapsed']:.1f}s, {len(r['content'])} chars)", file=sys.stderr)
        else:
            badge = f"🤖 {model}"
            print(f"{badge} ({r['elapsed']:.1f}s)")
            print(f"{'─'*40}")
            print(r["content"])
        # M5: Session save is handled by dispatch_single() in model_utils.py
        # (line 630-631) when alias + session_id are both set. No duplicate save here.
    else:
        print(f"❌ {model}: {r['error']}", file=sys.stderr)
        sys.exit(1)

    if (
        auto_answer_enabled
        and r.get("content")
        and r.get("error") is None
        and is_question_shaped(r["content"])
    ):
        print(
            "ask: clarification still needs a human answer after automatic "
            f"answering ({rounds_used}/2 rounds used).",
            file=sys.stderr,
        )
        sys.exit(2)

    # The CLI itself is conversational, but expose the final dispatch payload
    # to programmatic callers so its auto-answer audit is not lost.
    if auto_answer_enabled:
        return r


def _auto_answer_enabled(args) -> bool:
    """Return whether argparse's optional auto-answer flag was explicitly set.

    ``None`` represents the flag without an answer-model override; a string is
    a caller-selected answer model. The narrow type check also keeps legacy
    tests that pass sparse MagicMock argument objects on their historical path.
    """
    if not hasattr(args, "auto_answer"):
        return False
    value = args.auto_answer
    return value is None or isinstance(value, str)


if __name__ == "__main__":
    main()
