# Coding Model Comparison (June 2026)

Benchmark comparison of coding-focused cloud models available on Jim's
Ollama instance. All models route through the `ollama-glm` provider
(http://host.docker.internal:11434/v1).

## Primary Model

| Attribute | GLM 5.2 |
|---|---|
| Vendor | Z.ai |
| Released | June 13, 2026 |
| Parameters | 744B total, ~40B active (MoE) |
| Context window | 1M tokens |
| SWE-bench Pro | **62.1%** (highest open-weight) |
| SWE-bench Verified | — |
| LiveCodeBench | — |
| Key strength | Long-horizon coding on large contexts |

## Fallback Candidates

### Kimi K2.7 Code (recommended primary fallback)

| Attribute | Value |
|---|---|
| Vendor | Moonshot AI |
| Released | June 12, 2026 |
| Parameters | ~1T total, 32B active (MoE, 8 experts active) |
| Context window | 256K tokens |
| SWE-bench Pro | ~62% (Kimi Code Bench v2: 62.0%) |
| Key strength | Purpose-built for agentic coding (tool calls, multi-step tasks) |
| Ollama tag | `kimi-k2.7-code:cloud` |
| License | Modified MIT |

**Why as primary fallback:** Closest profile to GLM 5.2 — both are MoE
architectures tuned for coding, released same week, similar agentic
capabilities. Strong at multi-step tool-call workflows, which is exactly
where GLM 5.2 tends to fail (empty responses after tool results pour in).

### DeepSeek V4 Pro (recommended secondary fallback)

| Attribute | Value |
|---|---|
| Vendor | DeepSeek |
| Released | April 24, 2026 |
| Parameters | 1.6T total, 49B active (MoE) |
| Context window | 1M tokens |
| SWE-bench Pro | 55.4% |
| SWE-bench Verified | **80.6%** (highest open-weight, tied with Gemini 3.1 Pro) |
| LiveCodeBench | **93.5%** (#1 globally, open or closed) |
| Key strength | Algorithmic/competitive programming, deep reasoning |
| Ollama tag | `deepseek-v4-pro:cloud` |
| License | MIT |

**Why as secondary fallback:** Different vendor from GLM 5.2 and Kimi
(DeepSeek vs Z.ai vs Moonshot), so upstream outages are less correlated.
Best-in-class on algorithms and math — complements GLM 5.2's strength
on SWE-bench-style real-world coding tasks.

### MiniMax M3

| Attribute | Value |
|---|---|
| Vendor | MiniMax |
| Released | June 1, 2026 |
| Parameters | — |
| Context window | 1M tokens |
| SWE-bench Pro | 59.0% |
| Terminal-Bench 2.1 | 66% |
| BrowseComp | 83.5 |
| Key strength | Long context + agentic + native multimodal |
| Ollama tag | `minimax-m3:cloud` |

### Qwen3-Coder-Next

| Attribute | Value |
|---|---|
| Vendor | Alibaba (Qwen team) |
| Released | February 2026 |
| Parameters | 80B total, 3B active (MoE) |
| Context window | 256K tokens |
| SWE-bench Pro | 44.3% |
| SWE-bench Verified | 70%+ (via SWE-Agent) |
| Key strength | Extremely efficient (3B active), runs on consumer hardware |
| Ollama tag | `qwen3-coder-next:cloud` |

## Recommended Chain

```
GLM 5.2 (primary, SWE-bench Pro 62.1%)
  → Kimi K2.7 Code (fallback 1, agentic coding specialist)
  → DeepSeek V4 Pro (fallback 2, algorithms + reasoning, different vendor)
```

## Sources

- MarkTechPost: Kimi K2.7-Code release (June 2026)
- CodingFleet: GLM-5.2 vs DeepSeek V4 Pro benchmark comparison
- Regolo.ai: GLM 5.2 vs Kimi K2.7 Code definitive guide
- LushBinary: MiniMax M3 developer guide
- Qwen.ai blog: Qwen3-Coder-Next model card
- Fireworks AI: Best LLMs for coding 2026 roundup