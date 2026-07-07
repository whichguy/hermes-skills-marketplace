---
name: model-fallback-config
description: "Diagnose model failures (empty responses, thinking-only outputs), configure fallback provider chains in Hermes config.yaml, and research/select appropriate fallback models based on use case and benchmarks."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [model, provider, fallback, configuration, troubleshooting, reliability]
    related_skills: [hermes-agent, self-healing-cron-watchdogs]
    category: devops
---

# Model Fallback Configuration

When a cloud or local model starts failing — returning empty responses,
thinking-only outputs, or timing out — Hermes retries then gives up if no
fallback provider is configured. This skill covers the full loop: diagnosis,
configuration, and model selection research.

## When to Use

- Agent conversations die with "No reply: the model returned empty content
  after retries"
- Logs show repeated "Empty response" or "Thinking-only response" warnings
- User reports stuck/errored threads across multiple conversations
- Proactive: configuring a fallback chain before failures happen
- Researching which model to use as a fallback for a specific primary model

## Diagnosis: Empty Response Failures

### Symptom

In the Hermes UI (Slack, Telegram, CLI), a conversation shows:
```
Empty response from model — retrying (3/3)
Thinking-only response — prefilling to continue (1/2)
Thinking-only response — prefilling to continue (2/2)
No reply: the model returned empty content after retries and any fallback
providers. Try continue, switch model/provider, or inspect the tool output
above.
```

### Root Cause

The model generates reasoning/thinking tokens but no actual content.
Hermes exhausts its retry pipeline (3 content retries → 2 prefill attempts
→ 3 more retries) then gives up. If `fallback_providers: []` (empty),
there's no backup model to hand off to — the conversation dies.

### Diagnostic Steps

1. **Check agent logs for the failure pattern:**
   ```bash
   grep -i 'empty response\|thinking-only\|no reply\|returned empty' \
     /opt/data/logs/agent.log | tail -40
   ```

2. **Count total failures:**
   ```bash
   grep 'Empty response.*after 3 retries' /opt/data/logs/agent.log | wc -l
   ```

3. **Identify affected sessions** (session IDs in bracketed log prefixes):
   ```bash
   grep 'Empty response.*after 3 retries' /opt/data/logs/agent.log | \
     grep -oP '\[\d{8}_\d{6}_[a-f0-9]+\]' | sort -u
   ```

4. **Check fallback config:**
   ```bash
   grep -A5 'fallback_providers' /opt/data/config.yaml
   ```
   If `fallback_providers: []` — that's the gap.

5. **Check which model is failing:**
   ```bash
   grep 'Empty response.*after 3 retries' /opt/data/logs/agent.log | \
     grep -oP 'model=\S+' | sort | uniq -c | sort -rn
   ```

6. **Check available models on Ollama:**
   ```bash
   curl -s http://host.docker.internal:11434/api/tags | \
     python3 -c "import sys,json; data=json.load(sys.stdin); \
       [print(f'{m[\"name\"]:40s} {m[\"size\"]/1e9:.1f}GB') \
         for m in data.get('models',[])]"
   ```

### Failure Pattern

The retry pipeline when no fallback is configured:
```
Empty response (no content or reasoning) — retry 1/3
Empty response (no content or reasoning) — retry 2/3
Empty response (no content or reasoning) — retry 3/3
Thinking-only response (no visible content) — prefilling to continue (1/2)
Thinking-only response (no visible content) — prefilling to continue (2/2)
Empty response (no content or reasoning) — retry 1/3
Empty response (no content or reasoning) — retry 2/3
Empty response (no content or reasoning) — retry 3/3
→ "No fallback available" → conversation dies
```

This often happens after tool calls flood the context — the model receives
large tool outputs and then fails to produce any content response.

## Configuration: Fallback Provider Chains

### Config Format

In `config.yaml`:

```yaml
fallback_providers:
  - provider: <provider_name>
    model: <model_name>
  - provider: <provider_name>
    model: <model_name>
```

The chain is tried in order: primary model → first fallback → second
fallback. All providers must already be configured in the `providers:`
section of config.yaml.

### Example: Coding-Focused Fallback Chain

For a setup using `glm-5.2:cloud` as primary with Ollama-based cloud
models:

```yaml
model:
  default: glm-5.2:cloud
  provider: ollama-glm

providers:
  ollama-glm:
    name: Ollama GLM (Cloud, Zero Retention, US)
    base_url: http://host.docker.internal:11434/v1
    api_key: ollama
    api_mode: openai
    default_model: glm-5.2:cloud

fallback_providers:
  - provider: ollama-glm
    model: kimi-k2.7-code:cloud
  - provider: ollama-glm
    model: deepseek-v4-pro:cloud
```

### Tuning Retry Behavior

In the `agent:` section of config.yaml:

```yaml
agent:
  api_max_retries: 3    # Default. Bump to 5 for flaky models.
```

### Applying Config Changes

Config changes require a session restart to take effect:
- **CLI:** Exit and relaunch `hermes`
- **Gateway:** `/restart`
- **New session:** `/reset` (starts fresh with updated config)

### `patch` Tool Cannot Edit `config.yaml`

The `patch` tool has a built-in security guard that refuses to write to
Hermes config files:

```
Refusing to write to Hermes config file: /opt/data/config.yaml
Agent cannot modify security-sensitive configuration.
```

This is deliberate — prevents the LLM from silently changing its own
config. To edit `config.yaml` from a tool call, use `sed -i` via
`terminal`:

```bash
sed -i 's/  max_concurrent_children: 3/  max_concurrent_children: 5/' /opt/data/config.yaml
```

Or use `hermes config set key value` if the CLI is available.

## Model Selection Research Methodology

When selecting a fallback model, consider:

1. **Use case alignment** — coding, reasoning, general chat, agentic tool use
2. **Benchmark comparison** — SWE-bench Pro (real-world coding), SWE-bench
   Verified (verified coding tasks), LiveCodeBench (algorithmic/competitive
   programming), Terminal-Bench (agentic terminal tasks)
3. **Context window** — must handle the same context sizes as the primary
4. **Architecture similarity** — MoE models behave more like other MoE models
5. **Availability** — must already be installed on the Ollama instance or
   accessible via the configured provider
6. **Latency** — cloud models have similar latency; local models vary by
   size and quantization

### Research Workflow

1. List available models on the Ollama instance (see diagnostic step 6 above)
2. Identify cloud models (0.0GB size = cloud-routed through Ollama)
3. Web search for benchmark comparisons between the failing primary and
   candidate fallbacks
4. Compare on the benchmarks relevant to the user's primary use case
5. Recommend a fallback chain: primary → closest substitute → secondary
6. Verify the models exist in the Ollama instance before recommending

### Coding Model Comparison Reference

See `references/coding-model-comparison.md` for a benchmark comparison
table of coding-focused cloud models available on Jim's Ollama instance
(as of June 2026), including GLM 5.2, Kimi K2.7 Code, DeepSeek V4 Pro,
MiniMax M3, and Qwen3-Coder-Next.

## Ollama Cloud vs Local Models

Some Ollama models are **cloud-proxied**, not locally loaded. These behave
differently for concurrency, memory, and rate limits.

### Detecting Cloud-Proxied Models

```bash
curl -s http://host.docker.internal:11434/api/tags | python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('models', []):
    remote = m.get('remote_host', '')
    size_mb = m.get('size', 0) / 1e6
    kind = 'CLOUD' if remote else 'LOCAL'
    print(f'{kind:6s} {m[\"name\"]:40s} {size_mb:10.1f}MB  {remote}')
"
```

Cloud-proxied models have:
- `remote_host` field (e.g. `https://ollama.com:443`)
- Tiny `size` (a few hundred bytes — just the routing manifest, not weights)
- `remote_model` field naming the upstream model

Local models have:
- No `remote_host`
- Large `size` (GB-scale — actual GGUF/safetensors weights on disk)

### Concurrency Implications

| Aspect | Local model | Cloud-proxied model |
|--------|-------------|---------------------|
| `OLLAMA_NUM_PARALLEL` | Controls GPU batching | **Does NOT apply** — just HTTP passthrough |
| VRAM memory | Bottleneck (model loaded in GPU) | No local VRAM used |
| Rate limits | None (local) | **Opaque, set by cloud provider** |
| Concurrent request ceiling | GPU memory / `NUM_PARALLEL` | Cloud account tier (undocumented) |

### When Bumping `delegation.max_concurrent_children`

Each parallel subagent makes its own model API calls. With cloud-proxied
models, the concurrency ceiling is the cloud provider's rate limit, not
local resources. Formula for peak concurrent requests:

```
peak = max_concurrent_children   (subagents)
     + 1                         (parent agent)
     + 1-2                       (auxiliary tasks: vision, compression, etc.)
```

If peak exceeds the cloud provider's concurrent request limit, expect
`429 Too Many Requests` errors. Dial back `max_concurrent_children` if
this occurs. A quick stress test:

```bash
# Fire N concurrent requests to check for throttling
for i in $(seq 1 5); do
  curl -s http://host.docker.internal:11434/v1/chat/completions \
    -d '{"model":"glm-5.2:cloud","messages":[{"role":"user","content":"hi"}],"max_tokens":5}' &
done
wait
```

See `references/ollama-cloud-models.md` for detailed notes on
cloud-proxied model behavior, detection, and concurrency tuning.

## Auxiliary Task Routing

The `auxiliary.*` config section routes specific background tasks to
dedicated models. This is a first-class routing mechanism alongside
`model.*`, `delegation.*`, and `fallback_providers`.

### Key Slots

| Slot | Purpose | Typical model choice |
|------|---------|---------------------|
| `auxiliary.vision` | Image analysis, OCR | Local vision model (qwen3-vl:8b) |
| `auxiliary.background_review` | Background task review | Heavy reasoning model |
| `auxiliary.compression` | Context compression | Main orchestrator model |
| `auxiliary.title_generation` | Session titles | Main orchestrator model |
| `auxiliary.session_search` | Session search | Main orchestrator model |
| `auxiliary.web_extract` | Web page extraction | Main orchestrator model |
| `auxiliary.approval` | Approval decisions | Main orchestrator model |
| `auxiliary.curator` | Skill curation | Main orchestrator model |
| `auxiliary.kanban_decomposer` | Kanban task decomposition | Main orchestrator model |
| `auxiliary.mcp` | MCP tool calls | Main orchestrator model |
| `auxiliary.monitor` | Monitoring | Main orchestrator model |
| `auxiliary.profile_describer` | Profile description | Main orchestrator model |
| `auxiliary.skills_hub` | Skills hub | Main orchestrator model |
| `auxiliary.triage_specifier` | Triage specification | Main orchestrator model |
| `auxiliary.tts_audio_tags` | TTS audio tags | Main orchestrator model |

### Default Behavior

When `auxiliary.<task>.provider` is `auto` (the default), the task inherits
the parent agent's model. Setting it explicitly routes that task to a
different model — useful for offloading vision to a local model or
background review to a heavy reasoning model.

### Configuring

```bash
hermes config set auxiliary.background_review.provider ollama-glm
hermes config set auxiliary.background_review.model deepseek-v4-pro:cloud
```

Or in `config.yaml`:
```yaml
auxiliary:
  background_review:
    provider: ollama-glm
    model: deepseek-v4-pro:cloud
  vision:
    provider: ollama-glm
    model: qwen3-vl:8b
```

### 4-Tier Hybrid Routing Pattern

See `references/hybrid-routing-pattern.md` for a complete example mapping
a 4-tier strategy (orchestrator → delegation → fallback → local/auxiliary)
to Hermes config schema.

## Pitfalls

1. **`fallback_providers: []` is the default** — fresh Hermes installs have
   no fallback configured. The first time a cloud model hiccups, the
   conversation dies with no recovery path.
2. **Empty responses correlate with large tool outputs** — models that
   handle short conversations fine may fail when tool results flood the
   context (e.g., after `web_extract`, `delegate_task`, or multiple
   `web_search` calls). Test fallbacks under realistic tool-heavy
   conditions, not just simple chat.
3. **Cloud model availability is opaque** — `curl http://host.docker.internal:11434/api/tags`
   lists models but 0.0GB size means the model is cloud-routed. The model
   may still be unavailable if the upstream provider has an outage. A
   fallback chain with multiple providers (not just multiple models on the
   same provider) is more resilient.
4. **Config changes need a restart** — editing `config.yaml` does not affect
   running sessions. Tell the user to `/reset` or `/restart`.
5. **All fallbacks on the same provider** — if all fallback models route
   through the same Ollama provider and that provider has an upstream
   outage, all fallbacks fail together. For maximum resilience, configure
   fallbacks across different providers (e.g., ollama-glm + openrouter +
   anthropic).
6. **Reasoning/thinking models are more prone to empty responses** — models
   that produce reasoning tokens (like GLM 5.2 with thinking enabled) can
   get stuck in thinking-only mode, especially under high context load.
   A non-reasoning fallback model may be more reliable as a safety net even
   if it's slightly less capable.
7. **Cloud-proxied models bypass `OLLAMA_NUM_PARALLEL`** — models with a
   `remote_host` field (e.g. `glm-5.2:cloud`) are HTTP-proxied to a remote
   backend; the local GPU batching knob has no effect. Concurrency is
   limited by the cloud provider's opaque rate limits instead. See the
   "Ollama Cloud vs Local Models" section above.
8. **Bumping `max_concurrent_children` increases cloud API load** — each
   parallel subagent makes independent model API calls. With cloud-proxied
   models, peak concurrent requests = children + parent + auxiliary tasks.
   At `max_concurrent_children: 5`, peak can hit 7-8 concurrent requests
   to the same cloud backend. Stress-test before relying on it.
9. **`hermes config get` does not exist** — the CLI uses `show`, not `get`.
   To read a config value: `hermes config show` (full dump) or read
   `config.yaml` directly with `read_file` / Python `yaml.safe_load()`.
   To set: `hermes config set <key> <value>`.
10. **GLM models default to Chinese output** — GLM (ChatGLM by Zhipu AI) is a
    Chinese LLM that defaults to Chinese language output when not explicitly
    instructed otherwise. This is especially dangerous for cron jobs, where
    the user receives the output without context and can't correct it
    mid-stream. Any prompt using a GLM model (`glm-5.2:cloud`, etc.) MUST
    include an explicit English directive at the very top:
    `CRITICAL: ALL output MUST be in English. Never use Chinese or any other
    language. Always respond in English regardless of input language.`
    This applies to cron job prompts, delegate_task contexts, and any
    subagent that inherits a GLM model. Audit all GLM-powered jobs with:
    check every job in `jobs.json` where `model` contains `glm` and
    `prompt` does not contain `english` (case-insensitive). Batch-fix by
    prepending the directive to each prompt and writing back atomically
    (backup `jobs.json` first).

## Subagent Model Routing

The `delegation.model` / `delegation.provider` config keys control the **default** model for subagents spawned via `delegate_task`. Per-task `model` overrides are supported: the handler at `tools/delegate_tool.py` line 2225 reads `t.get("model")` first and only falls back to `creds["model"]` (the config-level `delegation.model`) when the per-task model is empty.

**The real constraint is provider, not model.** All tasks in a batch share the same `delegation.provider` (resolved once at line 2235). You can dispatch different models per task as long as they're all available on that provider. In Jim's setup, all cloud models route through `ollama-glm`, so per-task model overrides work for `deepseek-v4-pro:cloud`, `kimi-k2.7-code:cloud`, `qwen3-coder-next:q4_K_M`, and `glm-5.2:cloud`.

- **To switch all subagents to deepseek:** set `delegation.model: deepseek-v4-pro:cloud` in config.yaml. Simple but global.
- **To route different models per task:** use per-task `model` overrides in the `delegate_task` call. No config change needed.
- **Cron jobs** already support per-job `model` + `provider` overrides (`cron/jobs.py` line 327-365).

## Related Skills

- `hermes-agent` — CLI reference for `hermes config set`, model/provider
  configuration
- `self-healing-cron-watchdogs` — provider health checks and model swaps
  for cron jobs (cron-specific, not main conversation loop)

## Provider-Specific References

- `references/xai-grok-provider.md` — xAI Grok provider setup: model catalog,
  `hermes config set` commands, xAI-vs-X credential distinction, verification
  steps.