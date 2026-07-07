# Real Run: Advisor Review of ContextVar Hook Fix (2026-07-06)

## Context

The unified-messaging hook's Phase 3 interception was only catching 1/48
`adapter.send()` calls because it used emoji detection (⚙️/💬 only) to
identify progress messages. The progress system uses 13+ tool-specific emoji
prefixes, so most progress messages passed through as separate bubbles.

The proposed fix: use `contextvars.ContextVar` to tag the stream consumer's
asyncio task, then check the ContextVar in the patched `adapter.send()` to
distinguish consumer sends (let through) from progress sends (intercept).

## Panel

3-seat panel using `dispatch_advisors.py`:

| Seat | Model | Role | Toolsets |
|---|---|---|---|
| 1 | deepseek-v4-pro:cloud | Reasoner/architectural | file |
| 2 | kimi-k2.7-code:cloud | Code-level/debug | file |
| 3 | qwen3-coder-next:q4_K_M (local) | Local lens, different lineage | file |

## Key Findings

### Unanimous: ContextVar approach is sound

All 3 seats confirmed the approach is correct. `asyncio.create_task()` gives
each task an isolated `contextvars.Context` — mutations in one task are
invisible to siblings. This is a CPython 3.7+ language guarantee.

### DeepSeek: False-positive risk → dual-gate design

DeepSeek identified that ContextVar alone risks false positives: non-progress
sends during the agent-turn window also have the flag unset. Recommended a
dual-gate design: ContextVar as primary signal, emoji detection as fallback
for false-positive prevention.

### Kimi: Thread safety confirmed

Kimi confirmed the sync worker thread only does `queue.put()`, never calls
`adapter.send()`. No thread-safety concerns with the ContextVar approach.

### Qwen: ContextVar-only argument (outvoted)

Qwen argued for ContextVar-only (no emoji fallback) on simplicity grounds.
Outvoted 2:1 — the dual-gate design was the consensus.

## Outcome

The 3-change fix (ContextVar import + set in consumer.run() + check in
_maybe_intercept()) was applied and verified working via debug log. All three
paths confirmed: consumer sends let through, progress sends intercepted,
non-progress sends let through.

## Meta: Using Advisors for Hook Review

This was Pattern 1 (advisors) applied to hook code review. The panel caught
the false-positive risk that a single-model review would have missed. The
3-model split (reasoner + coder + local lens) provided complementary
perspectives: architectural soundness, implementation correctness, and
simplicity critique.
