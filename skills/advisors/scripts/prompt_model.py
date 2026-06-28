#!/usr/bin/env python3
"""
DEPRECATED: This script is now a thin wrapper around model_utils.py.

Use model_utils.py directly or import from it for shared dispatch logic.
This file exists only for backward compatibility with dev.py subprocess calls.

model_utils.py location: /opt/data/skills/productivity/ask/scripts/model_utils.py
"""

import argparse
import os
import sys

# Add model_utils.py to path so we can import it
script_dir = os.path.dirname(os.path.abspath(__file__))
model_utils_path = os.path.join(script_dir, '..', '..', '..', 'productivity', 'ask', 'scripts')
sys.path.insert(0, os.path.normpath(model_utils_path))

from model_utils import (
    clean_output,
    build_prompt,
    NON_ENGLISH_MODELS,
    DEFAULT_PROVIDER,
    DEFAULT_TIMEOUT,
    BITWARDEN_PREFIX,
    resolve_alias,
    dispatch_single
)


def main():
    parser = argparse.ArgumentParser(
        description="prompt-model — prompt a Hermes model, write output to a file"
    )
    parser.add_argument("-m", "--model", required=True, help="Model name (e.g., deepseek-v4-pro:cloud)")
    parser.add_argument("-p", "--prompt", required=True, help="The prompt text")
    parser.add_argument("--context", default="", help="Context to include after the prompt")
    parser.add_argument("-c", "--context-file", help="Read context from a file (overrides --context)")
    parser.add_argument("-o", "--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "-t", "--toolsets", default="",
        help="Comma-separated toolsets (e.g., file,web,terminal)"
    )
    parser.add_argument(
        "-s", "--skills", default="",
        help="Comma-separated skills to preload"
    )
    parser.add_argument(
        "--provider", default=DEFAULT_PROVIDER,
        help=f"Provider name (default: {DEFAULT_PROVIDER})"
    )
    parser.add_argument(
        "--max-turns", type=int, default=None,
        help="Max agent turns (default: Hermes config agent.max_turns)"
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help=f"Timeout in seconds (default: {DEFAULT_TIMEOUT})"
    )
    parser.add_argument(
        "--english-only", action="store_true",
        help="Force 'respond in English only' directive (auto-added for known non-English models)"
    )
    args = parser.parse_args()

    # Resolve context
    context = args.context
    if args.context_file:
        with open(args.context_file) as f:
            context = f.read()
    if not sys.stdin.isatty():
        stdin_data = sys.stdin.read().strip()
        if stdin_data:
            context = (context + "\n\n" if context else "") + stdin_data

    # Resolve model alias
    model = resolve_alias(args.model)

    # Build full prompt with context and English-only directive
    full_prompt = build_prompt(args.prompt, context, model, args.english_only)

    # Dispatch via model_utils.dispatch_single
    result = dispatch_single(
        model=model,
        prompt=full_prompt,
        context="",
        toolsets=args.toolsets,
        max_turns=args.max_turns,
        timeout=args.timeout,
        provider=args.provider,
        output_file=args.output,
        resume_session=None,
        alias=None,
        thinking=None
    )

    # Handle result - exit codes and stdout/stderr matching original behavior
    if result["error"]:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    content = result["content"]
    if not content:
        print("Error: empty output", file=sys.stderr)
        sys.exit(1)

    # Write to stdout or file
    if args.output:
        elapsed = result.get("elapsed", 0)
        chars = len(content)
        header = (
            f"<!--\n"
            f"model: {model}\n"
            f"provider: {args.provider}\n"
            f"elapsed: {elapsed:.1f}s\n"
            f"chars: {chars}\n"
            "-->\n\n"
        )
        with open(args.output, "w") as f:
            f.write(header + content)
        print(f"✅ {model} → {args.output} ({elapsed:.1f}s, {chars} chars)", file=sys.stderr)
    else:
        print(content)


if __name__ == "__main__":
    main()
