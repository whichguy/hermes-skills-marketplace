# qmd Setup Notes — Jim's Deployment (Jun 2026)

## Install

```bash
# Correct package: @tobilu/qmd (NOT the dead stub "qmd")
npm install -g @tobilu/qmd --prefix /opt/data/home/.npm-global
# Binary: /opt/data/home/.npm-global/bin/qmd
# Version: 2.5.3 (ae5de6b) as of Jun 2026
```

## File locations

| File | Path |
|------|------|
| Binary | `/opt/data/home/.npm-global/bin/qmd` |
| Config (index.yml) | `/opt/data/home/.config/qmd/index.yml` |
| SQLite index | `/opt/data/home/.cache/qmd/index.sqlite` |
| npm global prefix | `/opt/data/home/.npm-global` |

## Collection

```bash
/opt/data/home/.npm-global/bin/qmd collection add wiki /opt/data/wiki
# Pattern: **/*.md  |  17 files indexed at install
```

`index.yml` content:
```yaml
collections:
  wiki:
    path: /opt/data/wiki
    pattern: "**/*.md"
models:
  embed: hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf
  generate: hf:tobil/qmd-query-expansion-1.7B-gguf/qmd-query-expansion-1.7B-q4_k_m.gguf
  rerank: hf:ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF/qwen3-reranker-0.6b-q8_0.gguf
```

## MCP server config (config.yaml)

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
    enabled: true
```

**Why the env block is required:** Hermes spawns MCP stdio subprocesses with a filtered env (only PATH, HOME, USER, LANG, etc. from the *process* env, not the user's shell). The agent process runs as `hermes` user with `HOME=/opt/data/home`, but without explicit `XDG_CACHE_HOME`, qmd looks for its SQLite DB at a path that doesn't exist → "0 collections" in MCP status. The three `XDG_*` vars pin all three qmd paths to the correct location.

## Key pitfall: wrong npm package name

`npm install -g qmd` installs a completely different dead package (v0.0.0, no binary, no `bin` entry in package.json). Always use `@tobilu/qmd`.

## Auto re-index on wiki ingest

`wiki_ingest_precheck.py` runs this silently after emitting queue context:
```python
import subprocess as _sp
_sp.run(
    ["/opt/data/home/.npm-global/bin/qmd", "index", str(root)],
    capture_output=True, timeout=30
)
```
Failure is non-fatal (BM25 still works). The `index` subcommand updates changed files without full rebuild.

## Semantic search activation (ACTIVE as of Jun 2026)

Embeddings were activated at 37 documents (23 wiki pages + raw files). The ~50-page threshold in the skill description is a soft guideline — activating earlier is fine when semantic search is needed for agent memory or episodic lookup.

```bash
/opt/data/home/.npm-global/bin/qmd embed
```

Downloads ~333MB of GGUF models:
- `embeddinggemma-300M-Q8_0.gguf` (333MB, the main embedding model)
- `qmd-query-expansion-1.7B-q4_k_m.gguf` (query expansion)
- `Qwen3-Reranker-0.6B-Q8_0.gguf` (reranking)

**Activation experience (Jun 2026):**
- Download took ~3-4 minutes on a fast connection
- Embedding 56 chunks from 37 documents took ~3m50s
- After activation: `mcp_wiki_search_status()` shows `vector index: yes`, `needsEmbedding: 0`
- **First semantic query may time out** (the embedding model loads into memory on first use). Subsequent queries are faster. If a `mcp_wiki_search_query` call times out on first use, wait 30s and retry.
- BM25 search continues to work alongside semantic search (hybrid mode)

**Re-embedding after new pages:** Run `qmd embed` again after adding significant new content (10+ pages). The `wiki_ingest_precheck.py` auto-re-indexes changed files via `qmd index` (BM25 only); a full `qmd embed` is needed to update vector embeddings.

The weekly hygiene guard (`hygiene_guard.py`) alerts when `wiki/index.md > 60 lines` → consider re-running `qmd embed` to refresh embeddings for new content.

## MCP tool names (after Hermes restart)

After config.yaml update + Hermes restart, MCP tools register as:
- `mcp_wiki_search_query` — BM25 + semantic search
- `mcp_wiki_search_get` — retrieve doc by path/docid
- `mcp_wiki_search_multi_get` — retrieve multiple docs
- `mcp_wiki_search_status` — index health (shows collection count, doc count, embedding status)
- `mcp_wiki_search_list_resources` — list available resources

Verify with `mcp_wiki_search_status()` — should show `totalDocuments > 0` and collection name `wiki`.
