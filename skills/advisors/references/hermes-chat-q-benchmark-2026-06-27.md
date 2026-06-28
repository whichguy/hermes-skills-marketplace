# hermes chat -q Benchmark — 2026-06-27

## Discovery

`hermes chat -q "<prompt>" -m <model> --provider <provider> -Q --yolo` runs a
full Hermes agent as a one-shot subprocess. This gives per-seat model selection
with full tool access — exactly what the council pattern needs and what
`delegate_task` (pinned to a single model) cannot provide.

## Test Setup

```python
import subprocess, concurrent.futures, time

PROMPT = "In one sentence, what is the most important consideration when choosing a database for a financial application? respond in English only"

seats = [
    ("Reasoner", "deepseek-v4-pro:cloud"),
    ("Coder", "kimi-k2.7-code:cloud"),
    ("Generalist", "glm-5.2:cloud"),
]

def run_seat(role, model):
    cmd = ["hermes", "chat", "-q", PROMPT, "-m", model,
           "--provider", "ollama-glm", "-Q", "--yolo", "--max-turns", "3"]
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    elapsed = time.time() - start
    lines = [l for l in result.stdout.strip().split("\n")
             if not l.startswith("Bitwarden") and not l.startswith("session_id:")]
    return role, model, "\n".join(lines).strip(), elapsed, None

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    futures = {executor.submit(run_seat, r, m): (r, m) for r, m in seats}
    for future in concurrent.futures.as_completed(futures):
        role, model, content, elapsed, error = future.result()
        print(f"{role} ({model}): {elapsed:.1f}s — {content[:100]}...")
```

## Results

| Seat | Model | Time | Response |
|---|---|---|---|
| Reasoner | deepseek-v4-pro:cloud | 6.7s | ACID compliance — specifically strong transactional guarantees... |
| Coder | kimi-k2.7-code:cloud | 5.9s | The most important consideration is ACID compliance... |
| Generalist | glm-5.2:cloud | 22.6s | The most important consideration is data integrity... |

**Total wall time:** 22.6s (parallel, bounded by slowest seat)
**All 3 completed successfully.** No errors, no timeouts.

## Key Findings

1. **Model diversity works.** Three genuinely different models ran in parallel
   with different outputs — not correlated copies of the same answer.
2. **Full agent capability.** Each seat had tool access, skills, and multi-turn
   reasoning (capped at 3 turns for this test).
3. **Subprocess isolation.** Each `hermes chat -q` is a separate process —
   gateway restarts don't kill them, they don't share state.
4. **Bitwarden warning contamination.** The CLI prints a Bitwarden warning to
   stdout. Must filter it out when collecting results.
5. **GLM is slower.** glm-5.2:cloud took 22.6s vs 5.9-6.7s for the others.
   This is consistent — GLM is a larger model with higher latency.

## Flags Reference

| Flag | Purpose |
|---|---|
| `-q "<prompt>"` | One-shot mode, non-interactive |
| `-m <model>` | Per-seat model selection |
| `--provider <name>` | Inference provider |
| `-Q` | Quiet mode — suppress banner, spinner, tool previews |
| `--yolo` | Auto-approve all tool calls |
| `--max-turns N` | Cap agent loop (prevents runaway exploration) |

## Provider Note

All models route through `ollama-glm` provider (`host.docker.internal:11434/v1`).
The provider name is cosmetic — it's the same Ollama endpoint. The `-m` flag
selects the actual model.
