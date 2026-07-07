# Ollama Concurrency Benchmark (2026-06-29)

**Question:** Can the local Ollama proxy handle 3 concurrent requests to the same
model, or will it serialize them internally, negating the parallel speedup?

**Result: 3.25x speedup — Ollama handles concurrent requests without serializing.**

## Benchmark

```
Model: qwen3.6:35b-a3b
Mode: raw (direct Ollama API, no agent loop)
Tasks: 3 independent simple prompts

Sequential (3x dispatch_single, one at a time):
  Task 1: 12.68s
  Task 2: 12.94s
  Task 3: 16.36s
  Total:  41.98s

Parallel (3x dispatch_single, ThreadPoolExecutor):
  Task 1: 12.23s
  Task 2: 12.36s
  Task 3: 12.92s
  Total:  12.92s

Speedup: 3.25x
```

## Implications for v3.1 Concurrent Dispatch

- **Phase 1 speedup is real.** Parallel dispatch of 3 local-model tasks completes
  in ~13s vs ~42s sequential — a 3.25x wall-clock reduction.
- **No Ollama-level serialization.** The proxy handles concurrent requests to the
  same model without queuing or internal serialization.
- **Per-task latency unchanged.** Each task takes ~12-13s regardless of whether
  it runs alone or concurrently — no contention observed.
- **This was the #1 gate for Phase 1.** Without real parallelism, the only benefit
  would be isolation (separate worktrees). With 3.25x speedup, Phase 1 delivers
  both isolation AND speed.

## Script

The benchmark script is at `/tmp/ollama-concurrency-test.py` (one-off, not saved
as a reusable script — the pattern is simple enough to reproduce inline).
