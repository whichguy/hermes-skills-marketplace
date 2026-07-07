# 4-Tier Hybrid Local/Cloud Routing Pattern

Complete example of mapping a 4-tier model routing strategy to Hermes
config schema. Applied June 2026 on Jim's setup (Ollama with cloud-proxied
models + local models on macOS host).

## The 4 Tiers

| Tier | Role | Model | Config Mechanism |
|------|------|-------|-----------------|
| 1. Orchestrator | Main conversation brain, structural planning | glm-5.2:cloud (1M ctx) | `model.default` + `model.provider` |
| 2. Delegation | Subagent debugger/fixer, code analysis | kimi-k2.7-code:cloud | `delegation.model` + `delegation.provider` |
| 3. Fallback | Heavy reasoning safety net | deepseek-v4-pro:cloud | `fallback_providers[]` |
| 4. Local/Auxiliary | Fast local coding, vision, background review | qwen3-coder:30b, qwen3-vl:8b, deepseek-v4-pro | `providers.ollama-local` + `auxiliary.*` |

## Full Config

```yaml
# ── Tier 1: Main Orchestrator ──
model:
  default: glm-5.2:cloud
  provider: ollama-glm

agent:
  reasoning_effort: high
  max_turns: 120

# ── Tier 2: Subagent Delegation ──
delegation:
  model: kimi-k2.7-code:cloud
  provider: ollama-glm
  reasoning_effort: medium
  max_iterations: 90
  max_concurrent_children: 5
  max_spawn_depth: 1

# ── Tier 3: Fallback Chain ──
fallback_providers:
  - provider: ollama-glm
    model: kimi-k2.7-code:cloud
  - provider: ollama-glm
    model: deepseek-v4-pro:cloud

# ── Tier 4: Local Speed + Auxiliary Routing ──
providers:
  ollama-local:
    name: Ollama Local (Coding & Speed)
    base_url: http://host.docker.internal:11434/v1
    api_key: ollama
    api_mode: openai
    default_model: qwen3-coder:30b
  ollama-glm:
    name: Ollama GLM-5.2 (Cloud, Zero Retention, US)
    base_url: http://host.docker.internal:11434/v1
    api_key: ollama
    api_mode: openai
    default_model: glm-5.2:cloud

auxiliary:
  vision:
    provider: ollama-glm
    model: qwen3-vl:8b          # Local vision model
  background_review:
    provider: ollama-glm
    model: deepseek-v4-pro:cloud  # Heavy reasoning for bg tasks
  # All other auxiliary slots default to glm-5.2:cloud (inherited)
```

## How Requests Flow

```
User message
  → Tier 1: glm-5.2:cloud (orchestrator)
    → spawns subagent via delegate_task
      → Tier 2: kimi-k2.7-code:cloud (debugger)
    → vision task
      → Tier 4: qwen3-vl:8b (local vision)
    → background review
      → Tier 4: deepseek-v4-pro:cloud (heavy reasoning)
  → If glm-5.2 fails:
    → Tier 3: kimi-k2.7-code:cloud (1st fallback)
    → Tier 3: deepseek-v4-pro:cloud (2nd fallback)
```

## Key Design Decisions

1. **Orchestrator uses GLM-5.2** for its 1M context window — handles
   long conversations and large tool outputs without truncation.
2. **Subagents use Kimi K2.7 Code** — medium reasoning, good at code
   analysis and stack trace debugging. Faster than deepseek for routine
   coding tasks.
3. **Fallback chain is Kimi → DeepSeek** — if GLM-5.2 is down, Kimi
   handles most tasks; DeepSeek is the last-resort heavy lifter.
4. **Local coding model is qwen3-coder:30b** — fast, zero cloud cost,
   good for autocomplete-style tasks. The 80B variant (qwen3-coder-next)
   is available but overkill for speed-tier work.
5. **Vision stays local** — qwen3-vl:8b handles OCR and screenshots
   without cloud latency or privacy concerns.
6. **Background review gets deepseek** — background tasks benefit from
   heavy reasoning without blocking the main conversation.

## What Hermes Does NOT Support (Yet)

- **Per-task subagent model routing**: `delegate_task` uses a single
  `delegation.model` for all subagents. No per-task model override in
  the tool schema. See `references/subagent-model-routing.md` for the
  code-level gap and patch options.
- **Multiple profiles**: Hermes has no `profiles.*` config section.
  The 4-tier pattern uses the existing mechanisms (model, delegation,
  fallback, auxiliary) instead.

## Verification

```bash
# Check config validity
hermes config check

# List available models on Ollama
curl -s http://host.docker.internal:11434/api/tags | \
  python3 -c "import sys,json; [print(f'{m[\"name\"]}') for m in json.load(sys.stdin)['models']]"

# Read current routing config
python3 -c "
import yaml
with open('/opt/data/config.yaml') as f:
    c = yaml.safe_load(f)
print('model:', c.get('model'))
print('delegation:', {k:v for k,v in c.get('delegation',{}).items() if k in ('model','provider','reasoning_effort')})
print('fallback:', c.get('fallback_providers'))
print('auxiliary:', {k:v for k,v in c.get('auxiliary',{}).items() if v.get('provider') != 'auto'})
"
```
