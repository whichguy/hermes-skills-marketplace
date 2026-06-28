# Council Run: SDLC Hybrid Plan Review — 2026-06-27

## Context

Jim asked to compare the current SDLC setup against the `hermes-sdlc-loop.html`
guide and get council feedback on a proposed hybrid adoption plan. The comparison
doc is at `/opt/data/projects/kanban-auto-routing/sdlc-comparison.md`.

## Dispatch Method

**Direct Ollama API calls** (not `delegate_task`) because `delegation.model` was
pinned to `qwen3-coder-next:q4_K_M` — all subagents would have been forced to
the same model, breaking council diversity.

```bash
# All 3 panel members dispatched in parallel via background curl
curl -s http://host.docker.internal:11434/api/chat -d '{"model":"deepseek-v4-pro:cloud",...}' > /tmp/council_seat1.txt &
curl -s http://host.docker.internal:11434/api/chat -d '{"model":"kimi-k2.7-code:cloud",...}' > /tmp/council_seat2.txt &
curl -s http://host.docker.internal:11434/api/chat -d '{"model":"glm-5.2:cloud",...}' > /tmp/council_seat3.txt &
wait
```

Consensus synthesis also via direct API call to `deepseek-v4-pro:cloud`.

## Panel

| Seat | Model | Time | Bytes | Confidence |
|------|-------|------|-------|------------|
| Reasoner | deepseek-v4-pro:cloud | ~45s | 7,648 | High |
| Coder | kimi-k2.7-code:cloud | ~40s | 4,754 | Medium-High |
| Generalist | glm-5.2:cloud | ~35s | 4,281 | High |
| Consensus | deepseek-v4-pro:cloud | ~40s | 10,063 | — |

## Questions Asked

1. Is the hybrid approach sound? Are we picking the right things to adopt vs skip?
2. QA profile model choice — local qwen3.6:27b vs cloud glm-5.2:cloud?
3. Metadata vs file handoff — replace files or use both?
4. Orchestrator isolation — restrict default profile to [kanban] toolset only?
5. skills.external_dirs vs rsync — is native approach reliable enough?
6. Circuit breaker threshold — is 2 failures too aggressive for local models?
7. Priority ordering — which adoption items should be done first?

## Consensus Results

### Q1: Hybrid approach sound? → ✅ Yes (High confidence)
All 3 agreed. Adopt metadata handoffs, circuit breakers, crash recovery,
`skills.external_dirs`. Skip architect profile (pragmatic), skip built-in
dashboard (custom is better). Revisit `/learn` capture once pipeline stabilizes.

### Q2: QA profile model → local first, cloud fallback (High confidence)
All 3 agreed: `qwen3.6:27b Q4_K_M` as primary, `glm-5.2:cloud` fallback when
circuit breaker trips or task needs deep reasoning.

### Q3: Metadata vs file handoff → use both (High confidence)
Unanimous. Files = source of truth for humans/audit. Metadata = machine routing
for kanban. Critical: atomic write-then-rename to prevent desync on crash.

### Q4: Orchestrator isolation → do NOT restrict to [kanban] only (High confidence)
All 3 agreed: orchestrator needs read access to project artifacts for intelligent
planning. Enforce no-write on code files. Keep current default profile.

### Q5: external_dirs vs rsync → adopt native, keep rsync as daily backup (Medium confidence)
A & B want rsync retained as daily consistency check. C wants full deprecation
after one sprint. Consensus: adopt `external_dirs` as primary, keep rsync as
daily check for one sprint, then deprecate.

### Q6: Circuit breaker threshold → 3 failures, not 2 (High confidence)
All agreed 2 is too aggressive for local models (OOM, GPU fragmentation, proxy
errors). Set to 3 consecutive failures with 5-min cooldown. Implement
failure-type classification: transient (OOM/timeout) → auto-reload, don't count.
Logic errors → count toward threshold. Cloud models keep threshold of 2.

### Q7: Priority ordering (Medium confidence)
1. Crash recovery + circuit breaker (foundational resilience)
2. Metadata handoff + `review-required:` convention (process integrity)
3. `skills.external_dirs` + 4 custom phase skills (skill freshness)
4. `qa-dev` profile (new agent role)
5. Orchestrator isolation (refinement, do last)

## Key Lessons

1. **Direct API calls work when delegate_task model pinning blocks diversity.**
   Trade-off: no progress visibility, no tool access for panel members, manual
   result collection. Only use when panel members don't need tools.

2. **Consensus model as panel member is acceptable when unavoidable.**
   DeepSeek served as both Seat 1 (Reasoner) and consensus synthesizer. The
   consensus prompt explicitly instructed it to review all responses including
   its own. No self-bias was evident in the output.

3. **3-seat council with diverse models produces strong convergence.**
   All 7 questions had clear consensus. Only Q5 and Q7 had medium confidence
   due to implementation nuance, not fundamental disagreement.

4. **GLM model needs "respond in English only" in every prompt.**
   Without it, GLM defaults to Chinese output. This applies to both panel
   member prompts and consensus synthesis prompts.

## Artifacts

- Comparison doc: `/opt/data/projects/kanban-auto-routing/sdlc-comparison.md`
- Master plan: `/opt/data/projects/kanban-auto-routing/SDLC-MASTER-PLAN.md`
- Raw panel results: `/tmp/council_seat{1,2,3}.txt`
- Consensus: `/tmp/council_consensus.txt`
