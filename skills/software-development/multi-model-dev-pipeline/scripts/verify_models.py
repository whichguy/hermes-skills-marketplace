#!/usr/bin/env python3
"""Pre-flight model availability check for the multi-model dev pipeline.

Verifies that all pipeline models are available on the Ollama proxy before
starting Stage 3 (Coding). If the primary coding model (qwen3-coder-next:q4_K_M)
is unavailable, recommends the fallback (kimi-k2.7-code:cloud).

Usage:
    python3 scripts/verify_models.py
    python3 scripts/verify_models.py --base-url http://host.docker.internal:11434

Exit codes:
    0 — all models available
    1 — one or more models missing (fallback recommended in output)
    2 — cannot reach Ollama proxy (check connection)
"""

import json
import sys
import urllib.request
import urllib.error
from typing import Set

# ── Pipeline model requirements ──────────────────────────────────────────────
REQUIRED_MODELS = {
    "deepseek-v4-pro:cloud": "Stage 1 (Planning) + Stage 2 (Review) + Stage 5 (Test Planning)",
    "kimi-k2.7-code:cloud": "Stage 4 (Code Review) + Stage 6 (Test Execution)",
    "glm-5.2:cloud": "Orchestrator (main model)",
}

# Stage 3 has a fallback chain
CODING_MODEL_PRIMARY = "qwen3-coder-next:q4_K_M"
CODING_MODEL_FALLBACK = "kimi-k2.7-code:cloud"
CODING_STAGES = "Stage 3 (Coding)"


def get_available_models(base_url: str) -> Set[str]:
    """Fetch available model IDs from the Ollama proxy."""
    url = f"{base_url}/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        return {m["id"] for m in data.get("models", [])}
    except urllib.error.URLError as exc:
        print(f"ERROR: Cannot reach Ollama proxy at {base_url}: {exc}")
        sys.exit(2)
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"ERROR: Invalid response from Ollama proxy: {exc}")
        sys.exit(2)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify pipeline model availability")
    parser.add_argument(
        "--base-url",
        default="http://host.docker.internal:11434",
        help="Ollama proxy base URL (default: http://host.docker.internal:11434)",
    )
    args = parser.parse_args()

    print(f"Checking Ollama proxy at {args.base_url}...")
    available = get_available_models(args.base_url)

    if not available:
        print("ERROR: No models found on the proxy.")
        return 2

    print(f"Found {len(available)} models on the proxy.\n")

    # ── Check required models ───────────────────────────────────────────────
    missing = []
    all_ok = True

    for model, stages in REQUIRED_MODELS.items():
        if model in available:
            print(f"  ✓ {model:40s} → {stages}")
        else:
            print(f"  ✗ {model:40s} → {stages} — MISSING")
            missing.append(model)
            all_ok = False

    # ── Check coding model with fallback ─────────────────────────────────────
    print()
    if CODING_MODEL_PRIMARY in available:
        print(f"  ✓ {CODING_MODEL_PRIMARY:40s} → {CODING_STAGES}")
    else:
        print(f"  ⚠ {CODING_MODEL_PRIMARY:40s} → {CODING_STAGES} — not available")
        if CODING_MODEL_FALLBACK in available:
            print(f"    → Fallback: {CODING_MODEL_FALLBACK} (available ✓)")
            print(f"    → Stage 3 will use {CODING_MODEL_FALLBACK}")
        else:
            print(f"  ✗ {CODING_MODEL_FALLBACK:40s} → Fallback also MISSING")
            missing.append(CODING_MODEL_PRIMARY)
            all_ok = False

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    if all_ok:
        print("✓ All pipeline models are available. Safe to proceed.")
        return 0
    elif not missing or all(
        m == CODING_MODEL_PRIMARY and CODING_MODEL_FALLBACK in available
        for m in missing
    ):
        print("⚠ Primary coding model unavailable, but fallback is available.")
        print(f"  Stage 3 will use {CODING_MODEL_FALLBACK} instead of {CODING_MODEL_PRIMARY}.")
        return 0
    else:
        print(f"✗ {len(missing)} model(s) missing. Pipeline cannot run.")
        print("  Install missing models on the Ollama proxy or update model assignments.")
        return 1


if __name__ == "__main__":
    sys.exit(main())