# Subagent Model Routing — Architecture Research

Research from deep-reading `tools/delegate_tool.py` (June 2026, Hermes ~v0.17).
Covers how the `delegate_task` tool resolves the model for child agents, the
per-task model override mechanism, and the provider constraint.

## How Subagent Model Resolution Works

```
config.yaml → delegation.model + delegation.provider
    → _resolve_delegation_credentials(cfg, parent_agent)
        → creds["model"]           # default model for children
        → creds["provider"]         # single provider for ALL children
        → creds["base_url"]
        → creds["api_key"]
        → creds["api_mode"]
```

The `delegate_task()` function calls `_resolve_delegation_credentials()`
once, producing a single credential bundle. That bundle's `model` is the
**default** — per-task overrides take precedence.

## Per-Task Model Override (CONFIRMED WORKING)

At line 2225 of `tools/delegate_tool.py`:

```python
task_model = str(t.get("model") or "").strip() or creds["model"]
```

The handler reads `t.get("model")` from the task dict FIRST. Only falls
back to `creds["model"]` (the config-level `delegation.model`) when the
per-task model is empty/missing.

The tool schema (`DELEGATE_TASK_SCHEMA`) exposes `model` as a per-task
property in the `tasks[]` array items. The LLM can pass per-task model
overrides.

## The Provider Constraint

All tasks in a batch share the same **provider** — `override_provider` is
resolved once from `delegation.provider` at line 2235:

```python
override_provider=creds["provider"],
```

Per-task `model` overrides work as long as the model is available on that
provider. Cross-provider per-task routing is NOT supported — you'd need
separate `delegate_task` calls with different config or `hermes chat -q`
invocations.

In Jim's setup, all cloud models route through `ollama-glm`, so per-task
model overrides work for `deepseek-v4-pro:cloud`, `kimi-k2.7-code:cloud`,
`qwen3-coder-next:q4_K_M`, and `glm-5.2:cloud`.

## Credential Resolution Paths

`_resolve_delegation_credentials()` has three paths:

### Path 1: `delegation.base_url` configured
- Uses direct OpenAI-compatible endpoint
- Auto-detects `api_mode` from URL (e.g. `/anthropic` suffix → anthropic_messages)
- `api_key` inherited from parent if not set in config

### Path 2: `delegation.provider` configured
- Full credential resolution via `resolve_runtime_provider()`
- Supports all Hermes providers (openrouter, nous, zai, kimi-coding, minimax, etc.)
- Returns base_url, api_key, api_mode, provider, command, args

### Path 3: Neither configured
- Returns all None → child inherits everything from parent agent
- `effective_model = model or parent_agent.model`
- `effective_provider = override_provider or parent_agent.provider`

## How to Route Different Models to Subagents

### Per-task model override (works now, preferred)

```python
delegate_task(tasks=[
    {"goal": "Plan auth module", "model": "deepseek-v4-pro:cloud", "toolsets": ["file","web"]},
    {"goal": "Implement auth module", "model": "qwen3-coder-next:q4_K_M", "toolsets": ["terminal","file"]},
    {"goal": "Review auth module", "model": "kimi-k2.7-code:cloud", "toolsets": ["terminal","file"]},
])
```

All three tasks run on different models but share the same provider
(`delegation.provider: ollama-glm`). No config change needed.

### Global delegation switch

Set `delegation.model` to pin a default for all subagents:

```yaml
delegation:
  model: deepseek-v4-pro:cloud
  provider: ollama-glm
```

Per-task overrides still work — they take precedence over this default.

### Cron job model override

Cron jobs support per-job `model` + `provider` overrides
(`cron/jobs.py` line 327-365). Only applies to scheduled tasks.

## Current Config (Jim's setup, June 2026)

```yaml
model:
  default: glm-5.2:cloud          # Main orchestrator
  provider: ollama-glm

delegation:
  model: kimi-k2.7-code:cloud     # Default for subagents
  provider: ollama-glm
  reasoning_effort: medium

fallback_providers:
- provider: ollama-glm
  model: kimi-k2.7-code:cloud     # 1st fallback
- provider: ollama-glm
  model: deepseek-v4-pro:cloud    # 2nd fallback
```

## Key File Locations

- `tools/delegate_tool.py:2225` — per-task model override resolution
- `tools/delegate_tool.py:2235` — provider resolution (shared across batch)
- `tools/delegate_tool.py:1124-1143` — `_build_child_agent` credential resolution
- `hermes_cli/oneshot.py:12-16` — `hermes chat -q` model/provider support
- `cron/jobs.py:327-365` — per-job model+provider override for cron
