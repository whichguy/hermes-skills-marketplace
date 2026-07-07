# QMD Model Corruption Troubleshooting

When the QMD MCP server (wiki search) times out at 300s and burns 60-80% CPU
continuously, the root cause is likely corrupt or missing GGUF model files.

## Symptoms

- `mcp_wiki_search_query` times out after 300s (configured MCP timeout)
- QMD MCP worker process (the child `qmd.js mcp` PID, not the parent) shows
  60-80% CPU continuously, never settling
- `qmd doctor` reports `⚠ model cache: invalid` or `⚠ model cache: missing`
- BM25 search (`qmd search`) works fine — it's the vector/LLM-expanded queries
  that hang, because they try to load corrupt model files

## Root Cause

QMD uses three GGUF model files for semantic search:
1. **embeddinggemma-300M-Q8_0.gguf** (~319MB) — query/doc embeddings
2. **qmd-query-expansion-1.7B-q4_k_m.gguf** (~1.2GB) — LLM query expansion
3. **Qwen3-Reranker-0.6B-Q8_0.gguf** (~610MB) — LLM reranking

If any file is corrupt (partial download, 0-byte file, wrong magic bytes) or
if stale `.etag` files linger, the MCP server enters a busy loop trying to
re-download or re-validate on every request. On CPU-only environments (no GPU
acceleration), this compounds — the GPU probe itself spins.

## Fix (verified Jun 24, 2026)

```bash
export HOME=/opt/data/home

# 1. Kill any spinning QMD MCP processes
pkill -9 -f "qmd"

# 2. Delete ALL model files + stale etag files
rm -f /opt/data/home/.cache/qmd/models/*.gguf \
      /opt/data/home/.cache/qmd/models/*.etag \
      /opt/data/home/.cache/qmd/models/*.ipull

# 3. Fresh pull all 3 models
/opt/data/home/.npm-global/bin/qmd pull
# Takes ~30s on fast connection (2.2GB total)

# 4. Verify all models are valid
/opt/data/home/.npm-global/bin/qmd doctor
# Should show: ✓ model cache: 3 active models are downloaded and valid GGUF

# 5. Add QMD_FORCE_CPU=1 to MCP config (see below) to skip GPU probe loop

# 6. Restart Hermes gateway (from outside the container) to pick up config change
```

## QMD_FORCE_CPU=1 Config (prevents GPU probe loop)

On CPU-only environments, QMD wastes cycles probing for GPU backends (Metal,
CUDA, Vulkan) on every start. Setting `QMD_FORCE_CPU=1` makes CPU mode explicit
and skips the probe:

```yaml
mcp_servers:
  wiki-search:
    command: /opt/data/home/.npm-global/bin/qmd
    args:
    - mcp
    env:
      HOME: /opt/data/home
      XDG_CONFIG_HOME: /opt/data/home/.config
      XDG_CACHE_HOME: /opt/data/home/.cache
      QMD_FORCE_CPU: '1'
    enabled: true
```

Apply via: `hermes config set mcp_servers.wiki-search.env.QMD_FORCE_CPU 1`

**Gateway restart required** — config changes don't hot-reload. Cannot restart
from inside the gateway process. Run from the host:
```bash
docker exec -it hermes hermes gateway restart
```

## Diagnostic Commands

| Command | What it shows |
|---------|---------------|
| `qmd doctor` | Model cache validity, device mode, embedding freshness |
| `qmd status` | Index size, doc count, vector count, last updated |
| `qmd search "query"` | BM25-only (no LLM) — should be instant. If this works but `qmd query` hangs, it's a model loading issue |
| `ps aux \| grep qmd` | Check for spinning processes (high %CPU = stuck) |
| `qmd query 'lex:NCW' --limit 3 --no-rerank` | Structured lex-only query (no vector, no LLM) — fastest test |

## Key Insight: BM25 vs Vector/LLM Query Paths

- **BM25 (`qmd search`)** — pure SQLite FTS5, no model loading. Always fast.
- **Vector (`qmd vsearch`)** — loads embedding model (~860ms query once loaded). First load slow on CPU.
- **Full query (`qmd query`)** — loads query-expansion LLM (1.7B) + embedding + reranker. Slowest path on CPU.
- **MCP `query` tool** — uses full query path. If any model is corrupt, the MCP server spins.

When diagnosing timeouts, test BM25 first. If it works, the index is fine —
the problem is model loading, not the data.