# Local Model Turn Benchmarks

Benchmarked 2026-06-29 on Mac host with Ollama, Hermes in Docker (host.docker.internal:11434).

## Per-Model Turn Times

| Model | Size | Per-Turn (avg) | Practical Max Turns | 120-Turn Wall Time |
|---|---|---|---|---|
| `qwen3.6:35b-a3b` | 35B MoE | 5–20s | **10–15** | 10–20 min |
| `qwen3-coder-next:q4_K_M` | 80B MoE | 15–17s | **5–8** | 30+ min |
| `gemma4:12b-mlx-bf16` | 12B | ~3–5s (est.) | **15–20** | ~10 min |

## Raw Mode (No Agent Loop)

Direct Ollama API call — no tools, no skills, no system prompt:

| Model | Wall Time |
|---|---|
| `qwen3.6:35b-a3b` | **0.3–0.5s** |

## Key Insight

The 120-turn Hermes config default is a **safety ceiling**, not a target. Local models practically use 1–5 turns for most tasks. Wall time is the real constraint — each turn is a full inference cycle on the Mac.

**Recommendation:** When dispatching local models via `ask`, consider explicit `--max-turns` caps:
- `qwen3.6:35b-a3b`: `--max-turns 15`
- `qwen3-coder-next:q4_K_M`: `--max-turns 8`
- `gemma4:12b-mlx-bf16`: `--max-turns 20`

These prevent runaway dispatches while still giving the model enough headroom for multi-tool tasks.
