# xAI Grok Provider

xAI provides Grok models via an OpenAI-compatible API at `https://api.x.ai/v1`.

## Credential Distinction

**xAI API keys start with `xai-`** — these are for the Grok model API, NOT for
X/Twitter developer access. Despite shared ownership (both are Elon Musk
companies), they are separate systems with separate credentials:

| System | Key prefix | Portal | Purpose |
|--------|-----------|--------|---------|
| xAI (Grok) | `xai-` | [console.x.ai](https://console.x.ai) | LLM API access |
| X Developer | varies | [developer.x.com](https://developer.x.com) | X/Twitter API, MCP server |

An `xai-` key will NOT work for the X MCP server or any X/Twitter API endpoint.

## Adding to Hermes

Use `hermes config set` (NOT direct config.yaml editing — the `patch` tool
refuses to write to config.yaml):

```bash
hermes config set providers.xai.name "xAI Grok"
hermes config set providers.xai.base_url "https://api.x.ai/v1"
hermes config set providers.xai.api_key '${XAI_API_KEY}'
hermes config set providers.xai.api_mode "openai"
hermes config set providers.xai.default_model "grok-4.3"
```

The `${XAI_API_KEY}` env-var reference is resolved at runtime from `.env`.

## Available Models

| Model | Context | Notes |
|-------|---------|-------|
| `grok-4.3` | 1M tokens | Latest Grok, general reasoning (default) |
| `grok-4.20-reasoning` | 1M tokens | Deep reasoning, thinking tokens |
| `grok-4.20-non-reasoning` | 1M tokens | Fast responses, no thinking overhead |
| `grok-build-0.1` | 256K | Coding (alias: `grok-code-fast`) |
| `grok-imagine-image` | — | Image generation |
| `grok-imagine-video` | — | Video generation |

## Verification

```bash
# List available models (confirms key works)
curl -s https://api.x.ai/v1/models \
  -H "Authorization: Bearer $XAI_API_KEY" | python3 -m json.tool

# Quick chat test
hermes chat --provider xai --model grok-4.3 -q "Reply with exactly: connected"
```

## Usage

```bash
# Ad-hoc chat
hermes chat --provider xai --model grok-4.3 "your question"

# In cron jobs: provider=xai, model=grok-4.3
# In delegate_task: model="grok-4.3" (if provider is xai)
```

## Rate Limits & Pricing

xAI pricing and rate limits are documented at [docs.x.ai](https://docs.x.ai).
As of July 2026, Grok models are competitively priced against GPT-4o and
Claude Sonnet 4. Check current pricing before relying on it for high-volume
cron or delegation workloads.
