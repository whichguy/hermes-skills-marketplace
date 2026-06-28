# Council Real Run: Kanban SDLC Crash Prevention Plan Review

**Date:** 2026-06-27
**Question:** Review the Kanban SDLC crash prevention plan for quality, completeness, and correctness
**Panel:** 3 models (DeepSeek V4 Pro, Kimi K2.7, GLM 5.2) + consensus synthesis
**Total time:** ~8m 40s (dispatch to consensus)

## Panel

| # | Seat | Model | Time | Confidence | Verdict |
|---|---|---|---|---|---|
| 1 | Reasoner | deepseek-v4-pro:cloud | 4m 42s | High | APPROVE WITH CHANGES |
| 2 | Coder | kimi-k2.7-code:cloud | 1m 29s | High | APPROVE WITH CHANGES |
| 3 | Generalist | glm-5.2:cloud | 16.6s | Medium | APPROVE WITH CHANGES |
| Synthesis | deepseek-v4-pro:cloud | 1m 40s | — | — |

## Key Convergence (3/3 agree)

1. **Fix 3 fallback config syntax is WRONG** — plan proposes `model: primary/fallback:` but Hermes uses `fallback_providers:` list (already in reviewer config). Worse, `fallback_providers` only handles provider/API failures, NOT runtime errors like "pytest not found." Fix 3 would NOT have prevented the T4 crash.
2. **Task-body "DO NOT use pytest" is insufficient** — the model already ignored kanban comments. The script T5 body still says "preferred pytest" and "install via uv." Must rewrite to mention ONLY unittest, remove ALL pytest references.
3. **Script error handling broken** — `2>/dev/null` masks failures, no task-ID validation, JSON parse errors crash silently.
4. **Stuck-task terminology wrong** — plan says `in_progress` but Hermes uses `running`.
5. **7+ missing failure modes** — worker crashes, orchestrator crash mid-cycle, container restart, DB corruption, Ollama proxy SPOF, context-window exhaustion, multi-chain concurrency.

## Consensus Verdict

**APPROVE WITH CHANGES** — 5 must-fix items before execution:
1. Rewrite T4/T5 to mention ONLY unittest (remove all pytest refs)
2. Correct or remove Fix 3 (wrong syntax + wrong semantics)
3. Fix script error handling (remove 2>/dev/null, validate task IDs, add --dry-run)
4. Correct Fix 5 terminology (running not in_progress, leverage built-in diagnostics)
5. Make Fix 2 enforceable (git snapshot before destructive phases)

Plus 3 high-priority additions + 7 missing failure modes to document.

## Lessons

- All 3 models independently found the same 3 critical issues — strong factual convergence
- Kimi (Coder) went deepest: read actual Hermes source code for fallback_providers semantics and kanban DB schema
- DeepSeek (Reasoner) went broadest: identified 7 missing failure modes
- GLM (Generalist) was fastest (16.6s) but added systemic perspective on model non-compliance
- Consensus synthesis was clean — strong agreement made synthesis straightforward
- Subagent had execution issues (couldn't run terminal) but still wrote the consensus doc via file tools