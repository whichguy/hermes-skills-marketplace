# Model Assignment Rationale

## Stage → Model Mapping

| Stage | Model | Why This Model |
|---|---|---|
| 1 Code Planning | `deepseek-v4-pro:cloud` | Architecture and planning need heavy reasoning. DeepSeek V4 Pro excels at structured analysis, design tradeoffs, and multi-step planning. Cloud = no context length limits. |
| 2 Plan Review | `deepseek-v4-pro:cloud` | Adversarial review needs the same reasoning depth as planning. Same model to avoid "I didn't write this so I'll be harsh" bias — the model reviews its own output style critically. Prompt explicitly demands adversarial critique to counter groupthink. |
| 3 Coding | `qwen3-coder-next:q4_K_M` | 80B MoE with ~3B active parameters — fast for autocomplete-style coding. Local on Ollama = free, no token cost, no rate limits. MoE architecture means only relevant expert paths activate, giving good code quality at low compute. Fallback: `kimi-k2.7-code:cloud` if Qwen unavailable or too slow for large tasks. |
| 4 Code Review | `kimi-k2.7-code:cloud` | Kimi is code-specialized — trained on code review, bug detection, and security analysis. Cloud version has full context window. Read-only stage means no risk of file mutation. |
| 5 Test Planning | `deepseek-v4-pro:cloud` | Test strategy is a reasoning task (edge case enumeration, coverage analysis, mock design). DeepSeek's structured thinking excels here. |
| 6 Test Execution | `kimi-k2.7-code:cloud` | Running tests, reading failures, fixing code — Kimi's code specialization handles the debug-fix-rerun loop efficiently. |

## Why Not Use the Same Model for Everything?

- **Cost:** DeepSeek and Kimi are cloud models with token costs. Qwen is local
  and free. Using Qwen for coding (the most token-intensive stage) minimizes
  cost.
- **Specialization:** Kimi is specifically tuned for code tasks. DeepSeek is
  better at reasoning/architecture. Using each model where it's strongest
  produces better results than any single model.
- **Speed:** Local Qwen has no network latency. Cloud models have round-trip
  delay. For the coding stage (many small tool calls), local is faster.
- **Parallelism:** Different models on the same Ollama proxy can run
  concurrently without rate-limit contention (the proxy handles multiplexing).

## Why DeepSeek Reviews Its Own Plan (Stage 1 → Stage 2)

Same model for planning and review is a deliberate choice:

- **Pro:** The model understands its own plan structure and can find gaps it
  knows it tends to leave. The adversarial prompt explicitly demands "find EVERY
  problem" to counter the natural tendency to approve one's own work.
- **Con:** Risk of groupthink — the model may not catch fundamental flaws in
  its own reasoning style.
- **Mitigation:** The Stage 2 prompt includes explicit adversarial instructions
  and requires verification against the actual codebase (not just the plan).
  If groupthink is observed in practice, swap Stage 2 to a different model
  (e.g., `kimi-k2.7-code:cloud`).

## Fallback Chain

### Stage 3 (Coding) fallback

```
Primary: qwen3-coder-next:q4_K_M (local, free)
   ↓ (if unavailable or too slow)
Fallback: kimi-k2.7-code:cloud (cloud, code-specialized)
```

Detection logic (orchestrator):
1. Pre-flight check via `scripts/verify_models.py`
2. If Qwen not in model list → use Kimi for Stage 3
3. If Stage 3 subagent times out or hits max_iterations → re-dispatch with Kimi

### Stage-level fallback (all stages)

`delegate_task` inherits the parent's `fallback_providers` chain. If the
primary model fails (rate limit, 500, auth), Hermes automatically swaps to the
next provider in the chain. Current chain:

```yaml
fallback_providers:
  - {provider: ollama-glm, model: kimi-k2.7-code:cloud}
  - {provider: ollama-glm, model: deepseek-v4-pro:cloud}
```

This is turn-scoped: next message tries primary again.

## How to Swap Models

### Temporary (single run)

Override in the `delegate_task` call:
```python
delegate_task(
    goal="...",
    model="kimi-k2.7-code:cloud",  # override any stage
    toolsets=["terminal", "file"]
)
```

### Permanent (all future runs)

Edit the skill's frontmatter `config` section:
```yaml
config:
    coding_model: kimi-k2.7-code:cloud  # changed from qwen3-coder-next
```

Then update the model assignments in the stage sections of SKILL.md.

### Adding a new model

1. Install the model on the Ollama proxy
2. Verify it appears in `curl http://host.docker.internal:11434/v1/models`
3. Update the model assignment in SKILL.md and this file
4. Run `scripts/verify_models.py` to confirm availability