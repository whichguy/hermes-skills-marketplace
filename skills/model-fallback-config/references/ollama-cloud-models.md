# Ollama Cloud-Proxied Models

Notes on cloud-proxied Ollama models — models where Ollama acts as an
HTTP proxy to a remote inference backend (e.g. ollama.com) rather than
running weights locally on GPU.

## Detection

### Via API

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

### Key Fields

| Field | Cloud-proxied | Local |
|-------|--------------|-------|
| `remote_host` | `https://ollama.com:443` | absent |
| `remote_model` | upstream model name | absent |
| `size` | ~300-400 bytes (routing manifest) | GB-scale (actual weights) |
| `details.quantization_level` | empty | `Q4_K_M`, `Q8_0`, etc. |
| `details.format` | empty | `gguf`, `safetensors` |

### Via `/api/show`

```bash
curl -s http://host.docker.internal:11434/api/show \
  -d '{"name":"glm-5.2:cloud"}' | python3 -m json.tool
```

Cloud-proxied models return `parent_model` pointing to the base model
name and no real quantization/format fields.

## Known Cloud-Proxied Models (as of June 2026)

On Jim's Ollama instance (`host.docker.internal:11434`):

| Model | Remote Host | Upstream | Context |
|-------|-------------|----------|---------|
| `glm-5.2:cloud` | `https://ollama.com:443` | `glm-5.2` (756B) | 1M |
| `glm-5.1:cloud` | `https://ollama.com:443` | `glm-5.1` | 202K |
| `kimi-k2.7-code:cloud` | `https://ollama.com:443` | (Moonshot) | 256K |
| `deepseek-v4-pro:cloud` | `https://ollama.com:443` | (DeepSeek) | 1M |

The `:cloud` suffix in the tag name is the convention — local variants
would have quantization suffixes like `:q4_K_M` or `:q8_0`.

## Concurrency Behavior

### `OLLAMA_NUM_PARALLEL` — Does NOT Apply

This env var controls how many requests Ollama will batch into a single
GPU inference pass for **locally-loaded models**. For cloud-proxied
models, Ollama is just an HTTP reverse proxy — each request is forwarded
individually to the remote backend. The env var has no effect.

### Real Concurrency Ceiling

The limiting factor is the **cloud provider's rate limit**, which is:

- **Not exposed via API** — no `/api/limits` endpoint
- **Account-tier dependent** — free vs paid tiers likely differ
- **Undocumented** — Ollama's cloud docs don't publish concurrent request
  limits

### Impact on Hermes Delegation

When `delegation.max_concurrent_children` is increased, each subagent
makes independent API calls to the model provider. With cloud-proxied
models, peak concurrent requests to the cloud backend:

```
peak = max_concurrent_children   (subagents, each making model calls)
     + 1                         (parent agent, also making model calls)
     + 1-2                       (auxiliary tasks: compression, vision,
                                 session_search, etc. — all hit the same
                                 provider if configured with ollama-glm)
```

With `max_concurrent_children: 5`, peak can reach 7-8 concurrent requests.

### Stress Test

```bash
# Fire N concurrent chat requests to check for 429 throttling
for i in $(seq 1 8); do
  curl -s -o /dev/null -w "%{http_code} " \
    http://host.docker.internal:11434/v1/chat/completions \
    -d '{"model":"glm-5.2:cloud","messages":[{"role":"user","content":"hi"}],"max_tokens":5}' &
done
wait
echo
```

All `200` = no throttling at that concurrency.
Any `429` = throttled, dial back `max_concurrent_children`.

## Config Context

In Jim's `config.yaml` (as of June 2026):

```yaml
delegation:
  max_concurrent_children: 5    # bumped from default 3
  max_async_children: 5

agent:
  parallel_tool_call_guidance: true  # tool-level parallelism (independent
                                      # tool calls in same turn run concurrently)
```

All auxiliary tasks (vision, compression, session_search, approval,
etc.) also route through `ollama-glm` provider → same cloud backend.
This means auxiliary work adds to the concurrent request count.