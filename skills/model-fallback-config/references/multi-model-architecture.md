# Hermes Multi-Model Architecture

Research from source code audit of Hermes ~v0.17 (June 2026). Covers all four layers where Hermes can route to different models, the configuration mechanism for each, and the constraints.

## The Four Layers

### Layer 1: Main Chat Model

The model that runs the primary agent loop — receives user messages, calls tools, produces responses.

**Config:**
```yaml
model:
  default: glm-5.2:cloud
  provider: ollama-glm
```

**Override at runtime:** `hermes chat -q -m <model> --provider <provider>`

### Layer 2: Delegation (Subagent) Model

The model used by subagents spawned via `delegate_task`. Supports per-task model overrides.

**Config:**
```yaml
delegation:
  model: kimi-k2.7-code:cloud    # default for all subagents
  provider: ollama-glm
```

**Per-task override:**
```python
delegate_task(tasks=[
    {"goal": "plan review", "model": "deepseek-v4-pro:cloud", ...},
    {"goal": "code review", "model": "kimi-k2.7-code:cloud", ...},
])
```

**Constraint:** All tasks share the same `delegation.provider`. Per-task `model` only changes the model name on that provider. Source: `tools/delegate_tool.py:2225` (model) and `:2235` (provider).

### Layer 3: Fallback Chain

Models tried in order when the primary model fails (empty responses, timeouts).

**Config:**
```yaml
fallback_providers:
  - provider: ollama-glm
    model: kimi-k2.7-code:cloud
  - provider: ollama-glm
    model: deepseek-v4-pro:cloud
```

**Constraint:** Fallbacks are tried sequentially. If all fallbacks are on the same provider and that provider has an outage, all fail together.

### Layer 4: Auxiliary Task Routing

Background LLM tasks (vision, compression, web extraction, etc.) can be routed to dedicated models.

**Config:**
```yaml
auxiliary:
  vision:
    provider: ollama-glm
    model: qwen3-vl:8b
  background_review:
    provider: ollama-glm
    model: deepseek-v4-pro:cloud
```

**12 built-in slots:** vision, compression, web_extract, approval, mcp, title_generation, tts_audio_tags, skills_hub, triage_specifier, kanban_decomposer, profile_describer, curator.

**Plugin-extensible:** Plugins can register custom auxiliary tasks via `PluginContext.register_auxiliary_task()`.

## Cross-Layer Constraints

| Constraint | Applies to |
|---|---|
| Provider is shared across all tasks in a batch | Layer 2 (delegation) |
| Config changes don't take effect mid-session (cached at startup) | Layers 1-3 |
| Per-task model overrides bypass config cache (read fresh each call) | Layer 2 |
| Cron jobs support independent model+provider per job | Layer 2 (cron variant) |
| Auxiliary tasks each get their own provider+model config block | Layer 4 |
| Plugin-registered auxiliary tasks get their own config blocks | Layer 4 |

## Jim's Current Setup (June 2026)

```
Layer 1 (main):     glm-5.2:cloud          @ ollama-glm
Layer 2 (default):  kimi-k2.7-code:cloud    @ ollama-glm
Layer 2 (per-task): deepseek-v4-pro:cloud   @ ollama-glm (plan review)
Layer 2 (per-task): qwen3-coder-next:q4_K_M @ ollama-glm (coding)
Layer 3 (fallback): kimi-k2.7-code:cloud    @ ollama-glm
Layer 3 (fallback): deepseek-v4-pro:cloud   @ ollama-glm
Layer 4 (aux):      various                 @ ollama-glm
```

All models route through the same Ollama proxy (`ollama-glm`), so the single-provider constraint on Layer 2 doesn't bite. Cross-provider routing would require separate `delegate_task` calls with different config or `hermes chat -q` invocations.
