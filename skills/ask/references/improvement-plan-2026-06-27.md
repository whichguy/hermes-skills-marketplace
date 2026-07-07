# Skill Ecosystem Improvement Plan

**Created:** 2026-06-27
**Last Updated:** 2026-06-27 (post /no_think research)
**Status:** All phases complete ✅
**Reviewed by:** DeepSeek V4 Pro (see conversation transcript)

## Context

### Current Architecture

```
User message
    │
    ▼
┌──────────────────┐
│ triage            │  gemma4:12b-mlx-bf16, 0.5s, direct Ollama API
│ classify intent   │  structured v2 system prompt, 8 rules, 10 few-shot
│ /no_think prefix  │  3-strategy parser (exact line, last line, last match)
└────────┬─────────┘
         │
    ┌────┴────┬──────────┬──────────┬──────────┐
    ▼         ▼          ▼          ▼          ▼
 query_model build_code debug_code research   general_chat
    │         │          │          │          │
    ▼         ▼          ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│ ask    │ │ dev    │ │ dev    │ │advisors│ │ answer │
│ skill  │ │ skill  │ │ skill  │ │ skill  │ │ inline │
│        │ │planner │ │debugger│ │N models│ │        │
│aliases │ │coder   │ │(kimi)  │ │in paral│ │        │
│sessions│ │qa-test │ │        │ │→synth  │ │        │
│compare │ │        │ │        │ │        │ │        │
│thinking│ │        │ │        │ │        │ │        │
└────────┘ └────────┘ └────────┘ └────────┘ └────────┘
    │            │         │          │
    ▼            ▼         ▼          ▼
┌──────────────────────────────────────────┐
│ model_utils.py (shared dispatch core)   │
│ dispatch_single() → hermes chat -q     │
│ build_prompt() → /no_think for Qwen     │
│ clean_output() → session + Bitwarden    │
└──────────────────────────────────────────┘
```

### Key Learnings (updated 2026-06-27)

| # | Learning | Impact |
|---|----------|--------|
| 1 | `delegate_task` cannot target specific models — always uses `delegation.model` from config | Multi-model dispatch must use `hermes chat -q` subprocesses |
| 2 | `hermes chat -q -m <model> --provider <p> -Q --yolo` works as one-shot agent | Right primitive for all multi-model work |
| 3 | Direct Ollama API is 63x faster than agent loop for classification (0.5s vs 50s) | Triage correctly bypasses the agent loop |
| 4 | `agent.reasoning_effort` is global config, not per-call | `--thinking` flag works but has race condition in parallel mode (FIXED in Phase 1) |
| 5 | Structured system prompt with rules + counter-examples handles edge cases | v2 prompt fixed multi-intent and urgency detection |
| 6 | Test suite: 94 tests, 83 dry-run (no API needed) | Good unit coverage, 11 live API tests |
| 7 | `hermes config show` doesn't display `agent.reasoning_effort` directly | Must read config.yaml file to get current value |
| 8 | `prompt_model.py` and `ask.py` are now unified via `model_utils.py` | Single code path achieved in Phase 3 |
| 9 | **`/no_think` must be first line of user prompt** (not system message) | Qwen3 models: /no_think as first-line prefix in build_prompt() and triage.py |
| 10 | **qwen3:4b ignores /no_think in ALL positions** — always reasons inline | Do NOT use qwen3:4b for triage. Parser fallback (last-line extraction) works but wastes 200+ tokens |
| 11 | **qwen3.6:35b-a3b** is the recommended Qwen model for triage | 3B active params (MoE), 0.55s per call, respects think:false, /no_think optional |
| 12 | **Model compat matrix** for triage: gemma4:12b-mlx-bf16 ✅, qwen3.6:35b-a3b ✅, qwen3:14b ✅, qwen3:1.7b ✅, qwen3-coder-next ✅, qwen3:4b ❌ | Documented in both model_utils.py and triage.py |
| 13 | **3-strategy parser** handles chain-of-thought models: exact line match → last line/word → last match in content | Makes triage robust across model families even when /no_think fails |

---

## Phase 1 — Fix Correctness Bugs ✅ COMPLETE

| # | Task | Status | Commit |
|---|------|--------|--------|
| 1a | Serialize `--thinking` in comparison mode | ✅ Done | `12b7e62` |
| 1b | Add warning log when serialization kicks in | ✅ Done | `12b7e62` |
| 1c | Document need for `--reasoning-effort` CLI flag (TODO in code) | ✅ Done | `12b7e62` |
| 1d | Add 4 TestComparisonMode tests | ✅ Done | `12b7e62` |

**Result:** 57/57 tests passing. Race condition eliminated.

---

## Phase 2 — Safety Net ✅ COMPLETE

| # | Task | Status | Commit |
|---|------|--------|--------|
| 2a | Triage → Ask integration tests | ✅ Done | `82629ff` |
| 2b | Triage → Dev pipeline integration tests | ✅ Done | `82629ff` |
| 2c | Graceful degradation tests | ✅ Done | `82629ff` |

**Result:** 94 tests (was 57). 83 dry-run + 11 live API. All passing.

---

## Phase 3 — Unify Architecture ✅ COMPLETE

| # | Task | Status | Commit |
|---|------|--------|--------|
| 3a | Extract shared core into `model_utils.py` | ✅ Done | `842f6cd` |
| 3b | Wrap `prompt_model.py` as thin import wrapper | ✅ Done | `842f6cd` |
| 3c | LLM-efficient documentation (docstrings, inline tags) | ✅ Done | `842f6cd` |
| 3d | `/no_think` prefix for Qwen models in `build_prompt()` | ✅ Done | `dbc934f`, `477dad5` |
| 3e | `/no_think` first-line prefix in triage.py + 3-strategy parser | ✅ Done | `b19a1cd`, `477dad5` |
| 3f | Model compatibility matrix documented | ✅ Done | `477dad5` |

**Result:** Single dispatch core. All Qwen models (except qwen3:4b) classify in 3 tokens.

**Remaining Phase 3 items (lower priority):**
- 3g: Add `--mode raw` to ask.py (direct API, no agent loop) — enables triage to use unified code path
- 3h: Migrate advisors.py to import from model_utils.py (currently uses prompt_model.py wrapper)
- 3i: Migrate dev skill to use model_utils.py directly
- 3j: Deprecate prompt_model.py (add deprecation warning)

---

## Phase 4 — Routing Layer ✅ COMPLETE

**Goal:** Close the loop from triage → routing → model dispatch.

Per DeepSeek's review: triage should be a pure classifier. Routing is a separate concern that considers context, cost, and policy.

### 4a — Build `routing.py` ✅ Done

```python
# routing.py — takes triage result + context, returns dispatch decision
def route(triage_result, user_context=None, system_state=None):
    """
    triage_result: {category, confidence, raw_output}
    user_context: {time_of_day, cost_budget, preferred_models}
    system_state: {available_models, api_status, load}

    Returns: {skill, model, thinking, toolsets}
    """
    category = triage_result["category"]
    confidence = triage_result["confidence"]

    ROUTING = {
        "query_model":  {"skill": "ask",    "toolsets": "file,web"},
        "build_code":   {"skill": "dev",    "toolsets": "file,web,terminal"},
        "debug_code":   {"skill": "dev",    "role": "debugger", "toolsets": "file,web,terminal"},
        "research_info":{"skill": "advisors","toolsets": "file,web"},
        "urgent_action":{"skill": None,    "toolsets": None},  # respond immediately
        "general_chat": {"skill": None,    "toolsets": None},  # answer inline
    }

    decision = ROUTING.get(category, {"skill": None})
    # Apply cost-aware overrides
    if user_context and user_context.get("cost_budget") == "low":
        # Prefer local models
        decision["model"] = "fast"
    return decision
```

### 4b — Add cost-aware routing ✅ Done

```python
COST_TIERS = {
    "free":    ["fast", "qwen", "gemma"],           # local models
    "low":     ["glm", "kimi"],                      # cheap cloud
    "medium":  ["deepseek", "minimax"],              # mid cloud
    "high":    ["deepseek", "deepseek", "kimi"],     # multi-model consensus
}
```

Triage result + cost budget → model selection. Don't burn cloud API on simple queries.

### 4c — Add triage result caching ✅ Done

```python
from functools import lru_cache
import hashlib

@lru_cache(maxsize=128)
def cached_classify(message_hash, categories_hash):
    """Cache triage results by message content hash."""
    # Unhash and classify
```

Don't re-classify the same message within a session. LRU with 128 entries.

### 4d — Observability hook ✅ Done

```python
# model_utils.py
def log_pipeline_event(triage_result, routing_decision, model_used,
                       latency, token_count, success):
    """Log pipeline events for observability."""
    event = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "triage_category": triage_result["category"],
        "triage_confidence": triage_result["confidence"],
        "routed_to": routing_decision.get("skill"),
        "model": model_used,
        "latency_s": latency,
        "tokens": token_count,
        "success": success,
    }
    # Append to ~/.hermes/pipeline-events.jsonl
    with open(os.path.expanduser("~/.hermes/pipeline-events.jsonl"), "a") as f:
        f.write(json.dumps(event) + "\n")
```

**Deliverable:** `scripts/routing.py` — routing function with cost awareness and caching.

**Commit:** `6d08f97` — 8 files, +1199/-352 lines. All 4 subagents timed out but partial work was usable; remaining work done directly.

---

## Phase 5 — Enrichment ✅ COMPLETE

### 5a — Add triage categories ✅ Done

```python
DEFAULT_CATEGORIES = [
    "query_model",
    "build_code",
    "debug_code",
    "research_info",
    "urgent_action",
    "general_chat",
    # New:
    "deploy_code",    # "Deploy to staging", "Roll back the release"
    "write_docs",     # "Write README", "Document the API"
    "config_change",  # "Update the config", "Change the timeout"
    "status_check",   # "Is the server up?", "Check deployment status"
    "explain_concept",# "What is the capital of France?", "How does DNS work?"
]
```

**Commit `a3c2c35`** — 3 files, +111/-20 lines. Triage and routing now synchronized at 11 categories.

### 5a-fix — Sync triage+routing categories ✅ Done (2026-06-27, this session)

**Bugs found and fixed:**

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| Routing missing 5 categories | Subagent added 4 to triage but routing table stayed at 6 | Added all 5 to `ROUTING_TABLE` (now 11 total) |
| `explain_concept` missing from triage | Subagent added `config_change` but not `explain_concept` | Added category, examples, prompt rules, few-shot |
| `config_change` missing from routing | Was in triage but not in routing table | Added to `ROUTING_TABLE` → `dev` skill |

**End-to-end pipeline verified:** 11/11 messages correctly classified and routed, all high confidence, ~0.45s per message. Test suite: 118/118 (94 ask + 24 routing).

### 5b — Triage think:true fallback (~20 min, lower priority)

When confidence is low, retry with `think: true` and higher `num_predict`:

```python
if result["confidence"] == "low":
    # Retry with thinking enabled
    data["think"] = True
    data["options"]["num_predict"] = 50
    # Re-classify
```

### 5c — Session expiry (~20 min, lower priority)

```python
SESSION_TTL = 3600  # 1 hour

def clean_expired_sessions():
    """Remove sessions older than TTL."""
    # Check timestamp, remove old entries
```

### 5d — Triage model warm-up cron (~15 min, lower priority)

```bash
# Cron job: ping triage every 5 minutes to keep model loaded
*/5 * * * * python3 triage.py "warmup" --json > /dev/null 2>&1
```

### 5e — Delete old council skill (~5 min, lower priority)

The council skill at `skills/autonomous-ai-agents/council/` is broken (uses non-existent `delegate_task` model overrides). Delete or redirect to advisors.

### 5f — Petition for `--reasoning-effort` CLI flag (~30 min, lower priority)

File feature request for `hermes chat --reasoning-effort <level>` CLI flag. This would:
- Eliminate the race condition workaround (Phase 1)
- Allow parallel comparison mode with thinking levels
- Make thinking levels per-call instead of global

**Deliverable:** Enriched triage, operational hygiene, cleanup.

---

## Effort Summary

| Phase | Tasks | Est. Hours | Status |
|---|---|---|---|
| 1 — Fix bugs | 4 | ~1 hr | ✅ Complete |
| 2 — Safety net | 3 | ~2.5 hr | ✅ Complete |
| 3 — Unify | 6+4 | ~3 hr | ✅ Complete (3a-3f), 3g-3j lower priority |
| 4 — Routing | 4 | ~2.5 hr | ✅ Complete |
| 5 — Enrich | 6+1 | ~2 hr | ✅ Complete (5a + 5a-fix), 5b-5f lower priority |
| **Total** | **23+4** | **~11 hr** | |

## Dependencies

```
Phase 1 (done) ──→ Phase 2 (done) ──→ Phase 3 (done)
                                           │
                                           ▼
                                      Phase 4 (routing) ←── in progress
                                           │
                                           ▼
                                      Phase 5 (enrich) ←── in progress
```

Phase 5 items are independent and can be done in parallel with Phase 4.

## Test Coverage Plan

| Phase | New Tests | Running Total |
|---|---|---|
| 1 (done) | +4 comparison mode | 57 |
| 2 (done) | +37 integration | 94 |
| 3 (done) | +0 (refactor, no new tests) | 94 |
| 4 (done) | +5 routing | 99 |
| 5 (done) | +19 routing + sync | 118 |

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-27 | Use `hermes chat -q` subprocess for multi-model dispatch | `delegate_task` can't target models |
| 2026-06-27 | Use direct Ollama API for triage | 63x faster than agent loop |
| 2026-06-27 | Serialize `--thinking` in comparison mode | Race condition on global config |
| 2026-06-27 | Keep triage as pure classifier, routing separate | Context/cost/policy belong in routing, not classification |
| 2026-06-27 | Extract shared core before unifying | Avoids breaking advisors/dev during migration |
| 2026-06-27 | Add `--mode raw` to ask.py | Enables triage to use unified code path eventually |
| 2026-06-27 | `/no_think` as first-line prefix of user prompt | Qwen3 training-time directive; system message approach less effective |
| 2026-06-27 | qwen3.6:35b-a3b is recommended Qwen model for triage | 3B active params (MoE), 0.55s, respects think:false, /no_think optional |
| 2026-06-27 | qwen3:4b blacklisted for triage | Ignores /no_think in all positions; always reasons inline |
| 2026-06-27 | 3-strategy parser for category extraction | Handles models that ignore /no_think (last-line fallback catches correct category) |