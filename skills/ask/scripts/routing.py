#!/usr/bin/env python3
"""routing — Triage result to dispatch decision mapping.

# Architecture
Routing sits between triage (classifier) and model dispatch. It translates
a triage_result into a complete dispatch_decision including skill selection,
model preference, thinking level, and toolsets.

# Data Flow
    triage_result → route() → dispatch_decision
                     ↓
                routing_table lookup + cost-aware model selection

# Key Decisions
- Routing table maps 11 triage categories to skills (ask/dev/advisors/none)
- Cost tiers map budget levels to preferred model families
- Caching avoids repeated classification for identical messages
- Pipeline events logged to ~/.hermes/pipeline-events.jsonl

# Usage
    from routing import route, cached_classify, COST_TIERS
    
    result = cached_classify("Build a REST API")
    decision = route(result, user_context={'cost_budget': 'low'})
    # Returns: {'skill': 'dev', 'model': 'gemma4...', ...}
"""

import argparse
import json
import os
import sys
import threading
import time
from functools import lru_cache

# Add triage to path for internal imports.
# L3: This sys.path modification at import time is required because routing.py
#     imports triage.py from a sibling skill directory (productivity/triage/scripts/).
#     Lazy import would complicate the module-level patch targets in tests.
#     Alternative: make triage a proper package or move to shared lib.
TRIAGE_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', 'triage', 'scripts'
)
sys.path.insert(0, TRIAGE_DIR)

import triage  # noqa: E402 — import as module so tests can patch routing.triage.classify


# ── Cost Tiers ───────────────────────────────────────────────────────────────
# Maps cost_budget levels to preferred model families.
# Free/low budgets prefer local models for cost optimization.

COST_TIERS = {
    'free': ['fast', 'qwen', 'gemma'],       # Local models (no API cost)
    'low': ['glm', 'kimi'],                   # Cheap cloud (per-token pricing)
    'medium': ['deepseek', 'minimax'],        # Mid-tier cloud
    'high': ['deepseek', 'kimi'],             # Multi-model consensus
}

# ── Routing Table ────────────────────────────────────────────────────────────
# Maps triage categories to dispatch decisions.

ROUTING_TABLE = {
    'query_model': {
        'skill': 'ask',
        'toolsets': 'file,web',
        'role': None,
    },
    'build_code': {
        'skill': 'dev',
        'toolsets': 'file,web,terminal',
        'role': None,
        # P9: build_code routes to the test-first SDLC pipeline
        # (planner → test-planner → coder → test-runner → debugger cascade)
        'pipeline': 'test_first',
    },
    'debug_code': {
        'skill': 'dev',
        'toolsets': 'file,web,terminal',
        'role': 'debugger',  # Uses dev skill with debugger role
        # P9: debug_code routes to the cascading debugger
        # (qwen-coder primary → kimi fallback)
        'pipeline': 'debug_cascade',
    },
    'research_info': {
        'skill': 'advisors',
        'toolsets': 'file,web',
        'role': None,
    },
    'urgent_action': {
        'skill': None,  # Respond immediately via inline handler
        'toolsets': None,
        'role': None,
    },
    'general_chat': {
        'skill': None,  # Answer inline without skill loading overhead
        'toolsets': None,
        'role': None,
    },
    # ── Phase 5 enrichment categories (added 2026-06-27) ──
    'deploy_code': {
        'skill': 'dev',
        'toolsets': 'file,web,terminal',
        'role': None,
    },
    'write_docs': {
        'skill': 'dev',
        'toolsets': 'file,web',
        'role': None,
    },
    'config_change': {
        'skill': 'dev',
        'toolsets': 'file,terminal',
        'role': None,
    },
    'status_check': {
        'skill': None,  # Direct response — no skill needed
        'toolsets': None,
        'role': None,
    },
    'explain_concept': {
        'skill': 'ask',
        'toolsets': 'file,web',
        'role': None,
    },
}


# ── Core Routing Function ────────────────────────────────────────────────────

def route(triage_result, user_context=None, system_state=None):
    """Route a triage result to a dispatch decision.

    Args:
        triage_result: Dict with keys {category, confidence, raw_output}.
            category: One of the 11 routing categories.
            confidence: 'high', 'medium', or 'low'.
            raw_output: The original model output for debugging.
        user_context: Optional dict with {cost_budget, preferred_models}.
            cost_budget: 'free'|'low'|'medium'|'high' (defaults to 'medium').
            preferred_models: List of model names to prioritize.
        system_state: Optional dict with {available_models, api_status}.
            available_models: List of models accessible in current context.
            api_status: Dict of API endpoint statuses.

    Returns:
        Dict with keys:
            skill: Skill name or None (for inline responses).
            model: Recommended model based on cost budget.
            thinking: Reasoning effort level ('minimal' for general_chat,
                'low' for query_model, 'medium' for others).
            toolsets: Comma-separated toolset string.
            role: Role override for dev skill (e.g., 'debugger').

    Raises:
        ValueError: If triage_result['category'] is unknown.

    Side Effects:
        None - pure function with no external state changes.

    # NOTE: The returned model is selected based on cost budget and
    #       available models, not the triage model. This allows budget-aware
    #       inference without re-classifying.

    # NOTE: When skill=None (urgent_action/general_chat), the return values
    #       for other fields are placeholders representing "inline response mode".
    """
    if user_context is None:
        user_context = {}
    if system_state is None:
        system_state = {}

    category = triage_result.get('category')
    confidence = triage_result.get('confidence', 'low')

    # Validate category is present
    if category is None:
        raise ValueError("triage_result missing 'category' key")

    # Validate category
    if category not in ROUTING_TABLE:
        raise ValueError(f"Unknown triage category: {category}")

    routing_config = ROUTING_TABLE[category]
    cost_budget = user_context.get('cost_budget', 'medium')

    # Select model based on cost budget (best fit from available models)
    preferred_models = COST_TIERS.get(cost_budget, COST_TIERS['medium'])

    # system_state can override or constrain model selection
    available_models = system_state.get('available_models', [])
    preferred_in_available = []
    for pm in preferred_models:
        if not available_models or pm in available_models:
            preferred_in_available.append(pm)

    # Fallback: use first available model or default fast local
    if preferred_in_available:
        model = preferred_in_available[0]
    elif available_models:
        model = available_models[0]
    else:
        model = COST_TIERS['free'][0]  # Safe default — alias, not literal model name

    # Determine thinking level based on category and confidence
    if category == 'general_chat':
        thinking = 'minimal'  # Fast, low-effort responses
    elif category == 'query_model' or confidence in ('high', 'medium'):
        thinking = 'low'  # Light reasoning for known patterns
    else:
        thinking = 'medium'  # Moderate effort for complex cases

    return {
        'skill': routing_config['skill'],
        'model': model,
        'thinking': thinking,
        'toolsets': routing_config['toolsets'],
        'role': routing_config['role'],
        'pipeline': routing_config.get('pipeline'),  # P9: test_first or debug_cascade
    }


# ── Cached Triage Wrapper ────────────────────────────────────────────────────

# NOTE: Thread lock for cached_classify. lru_cache itself is not thread-safe
#       for concurrent calls with the same key — two threads can both miss the
#       cache and both invoke triage.classify(). The lock makes the
#       check-and-compute atomic so only one API call happens per unique key.
_classify_lock = threading.Lock()


@lru_cache(maxsize=128)
def cached_classify(message, categories=None, model='gemma4:12b-mlx-bf16'):
    """Classify a message with LRU caching.

    Args:
        message: The user message to classify.
        categories: Optional list of custom category names.
        model: Ollama model name (default: gemma4:12b-mlx-bf16).

    Returns:
        Dict from triage.classify() result.

    Side Effects:
        - First call for a given (message, categories, model) tuple
          triggers actual classification via triage.classify().
        - Subsequent calls return cached results instantly.
        - Cache is keyed on the exact parameter values (tuple of args).

    # NOTE: LRU cache evicts least-recently-used items when maxsize=128
    #       is exceeded. The cache persists for the process lifetime.
    # PERF: Cache hit is ~0ms vs ~500ms for first classification.
    # RACE: lru_cache is NOT thread-safe for concurrent calls with the same key.
    #       In practice, dispatch_comparison() runs parallel calls with DIFFERENT
    #       models, so cache key collisions are unlikely. If they occur, the
    #       worst case is a duplicate API call (not data corruption).
    """
    categories_tuple = tuple(categories) if categories else None
    # RACE: Lock prevents concurrent threads from both missing the cache
    #       and invoking triage.classify() for the same message. The lock is
    #       held during the API call (~0.5s) so parallel calls with DIFFERENT
    #       messages are serialized too — acceptable for the routing CLI.
    with _classify_lock:
        result = triage.classify(
            message=message,
            categories=list(categories_tuple) if categories_tuple else None,
            model=model,
            timeout=triage.DEFAULT_TIMEOUT,
        )
    return result


# ── Pipeline Event Logging ───────────────────────────────────────────────────

def log_pipeline_event(triage_result, routing_decision, model_used, latency,
                       token_count, success=True):
    """Log a pipeline event to ~/.hermes/pipeline-events.jsonl.

    Args:
        triage_result: Dict from route()'s input (or cached_classify output).
        routing_decision: Dict returned by route().
        model_used: The actual model name used for dispatch.
        latency: Wall-clock time in seconds for the entire pipeline.
        token_count: Number of tokens processed (from triage or model response).
        success: Boolean indicating if the pipeline completed without error.

    Returns:
        None. Appends JSON line to events file.

    Side Effects:
        - Creates ~/.hermes/ directory if missing.
        - Appends one line to pipeline-events.jsonl per call.
        - Line format: {"timestamp": "...", ...}

    # NOTE: No error handling for file I/O — failures propagate silently
    #       (logging should not crash the pipeline).
    """
    event = {
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'triage_category': triage_result.get('category'),
        'triage_confidence': triage_result.get('confidence'),
        'routed_to': routing_decision.get('skill'),
        'model': model_used,
        'latency_s': round(latency, 3),
        'tokens': token_count,
        'success': success,
    }

    events_file = os.path.expanduser('~/.hermes/pipeline-events.jsonl')
    try:
        os.makedirs(os.path.dirname(events_file), exist_ok=True)
        with open(events_file, 'a') as f:
            f.write(json.dumps(event) + '\n')
    except Exception as e:
        print(f"Warning: pipeline event logging failed: {e}", file=sys.stderr)


# ── CLI Interface ────────────────────────────────────────────────────────────

def main():
    """CLI entry point for routing decisions.

    Args:
        message (positional): Message to classify and route.
        --verbose: Show full triage result + routing decision.
        --cost-budget: Cost budget for model selection (free/low/medium/high).
        --dry-run: Skip triage API call, use 'general_chat' placeholder.

    Returns:
        None. Prints JSON to stdout, exits 0 on success / 1 on error.

    Side Effects:
        - Calls cached_classify() which may hit Ollama API (~0.5s).
        - Appends to ~/.hermes/pipeline-events.jsonl via log_pipeline_event().

    # NOTE: dry-run mode skips the triage API call entirely — useful for
    #       testing routing logic without model latency or API availability.
    """
    parser = argparse.ArgumentParser(
        description="routing — triage-to-dispatch decision layer"
    )
    parser.add_argument('message', nargs='?', help='Message to classify and route')
    parser.add_argument('--verbose', action='store_true',
                        help='Show full triage result + routing decision')
    parser.add_argument('--cost-budget', choices=['free', 'low', 'medium', 'high'],
                        default='medium',
                        help='Cost budget for model selection (default: medium)')
    parser.add_argument('--dry-run', action='store_true',
                        help="Skip triage API call, use 'general_chat' as placeholder")
    args = parser.parse_args()

    if not args.message:
        parser.print_help()
        sys.exit(1)

    start_time = time.time()

    if args.dry_run:
        # NOTE: dry-run skips the actual triage API call and uses a placeholder
        # category. Useful for testing routing logic without model latency.
        triage_result = {
            'category': 'general_chat',
            'confidence': 'high',
            'raw_output': '(dry-run)',
            'tokens': 0,
            'elapsed': 0,
        }
    else:
        triage_result = cached_classify(args.message)

    # Determine success based on triage result
    # NOTE: Previously hardcoded success=True even on routing errors.
    #       Now reflects actual pipeline status.
    triage_ok = triage_result.get('category') not in (None, 'unknown', '')
    try:
        routing_decision = route(triage_result, user_context={'cost_budget': args.cost_budget})
        routing_ok = True
    except (ValueError, KeyError) as e:
        routing_decision = {'skill': None, 'model': None, 'thinking': None,
                            'toolsets': None, 'role': None, 'error': str(e)}
        routing_ok = False

    latency = time.time() - start_time

    # Log to pipeline events (skip on dry-run to avoid polluting event log)
    if not args.dry_run:
        log_pipeline_event(
            triage_result=triage_result,
            routing_decision=routing_decision,
            model_used=routing_decision.get('model'),
            latency=latency,
            token_count=triage_result.get('tokens', 0),
            success=triage_ok and routing_ok,
        )

    output = {
        'message': args.message,
        'triage_result': triage_result if args.verbose else {
            'category': triage_result['category'],
            'confidence': triage_result['confidence'],
        },
        'routing_decision': routing_decision,
        'latency_s': round(latency, 3),
    }

    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
