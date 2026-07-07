# devloop — locked decisions (2026-06-29)

This skill consolidates the legacy SDLC engine (`productivity/ask/scripts/sdlc.py` v5
~2,251 LOC + `sdlc_state.py` v6 ~2,151 LOC + `sdlc_parallel.py` ~515 LOC ≈ 4,917 core
LOC) into a lean **DoD-Oracle Loop on the Native Runtime + Thin Trust Kernel**.

## Locked constraints (user)
- **Scope**: real multi-file project changes (worktree isolation + blast-radius are REQUIRED, not YAGNI).
- **Optimize for**: output correctness / quality.
- **Appetite**: bold simplification (~86% cut of the core engine; control flow rides the native `conversation_loop`).

## The 5 locked decisions
1. **Spike acceptance bar** (gates the whole migration): ≥5 real multi-file tasks, ≥2 runs each,
   **0** phase-skips/wandering, gated stop honored. If unmet → fall back to a thin ~300-LOC code
   sequencer instead of betting on the native loop.
2. **Ambiguity / autonomy = correctness-biased**: PROCEED only if there is no blocking open-question
   **and** `min(assumption.confidence) ≥ 0.7`; otherwise route to HUMAN_REVIEW (async Telegram).
3. **Council timing = every merge** in v1 (the final semantic DoD gate). Optimize to borderline-only later.
4. **LEARNINGS in back-off = static table + read-time last-20** in v1. Per-task LEARNINGS-seeded
   appends deferred to a fast-follow.
5. **LEARNINGS IO home = reuse `worktree.learning_commit`** (no duplicate learnings module).

## Tweaks adopted from the adversarial gut-check
- Honest LOC baseline: ~4,917 core LOC → ~680 code + ~300 prose. Native `conversation_loop` (~4,800 LOC) now carries control flow.
- **Holdout split pulled earlier**: must be live **before canary (migration step 4)**, not a post-deletion fast-follow.
- **Assertion judge = 2-model agreement** + deterministic escalation (no self-reported-confidence gating).
- **Council gate checks completeness AND satisfaction** ("do these criteria fully deliver `interpreted_intent`?").
- Shadow mode suppresses side-effects (no Telegram/merge/cron); HUMAN_REVIEW gets a staleness/timeout policy; rollback to v6 is per-new-task only.

## Token caps & timeouts — DO NOT hardcode
Per project policy, token caps and per-call timeouts are sourced from the Hermes runtime config
at call time, never hardcoded low to "fix" a slow model. See `config.py` and `evidence.py`.

## Superseded (2026-07-01 deep review — this file is the ORIGINAL locked-decision record)
- Decision 2's floor value moved: read `CONFIDENCE_FLOOR` from `config.py` (spike-recalibrated).
- Decision 3 (council every merge): council was DE-ADVERTISED — `gate.council_gate` exists + is
  tested but is NOT wired into the stop; coverage + distinct judges + evidence + the whole-suite
  regression gate are the verification.
- Decision 5 (`worktree.learning_commit`): LEARNINGS IO actually lives in `state.py`
  (`append_learning`/`read_learnings`, consumed by the project outer loop).
- The holdout split was DELETED (the coder reads test files off disk; prompt-hiding cannot work).
- The "native loop carries control flow" bet was superseded: `loop.run_v1` is a CODE-owned
  controller (the prose-orchestrator thesis did not survive contact; see SKILL.md).

## Status
SHIPPED: devloop is the default SDLC engine (routing -> pipeline.py -> devloop_bridge, kill-switch
DEVLOOP_ENABLED). The legacy v5/v6 engine was deleted 2026-07-01 (commit 0344872; rollback anchor =
its parent). See SKILL.md for the honest runtime contract.

## 2026-07-04 — lock-free merge landing
- Removed the flock merge-lock. Landing is lock-free via Git ref-CAS: `commit-tree` parents the
  squash on the verified tip, then atomic `update-ref` publishes it with that tip as expected-old.
  This closes both devloop-vs-devloop and foreign-writer races.
- Removed the scout pipeline lock too: once `merge_branch` dropped the flock it excluded nothing.
  Scout's dirty-baseline precondition and scrub-failure refusal remain the real, lock-independent
  guards.
- **KNOWN RESIDUAL** (sharpened by a 2026-07-04 Codex concurrency cross-check — dormant under
  today's workload, NOT a live defect): the ref-CAS makes the *ref update* atomic, but NOT the
  shared index/worktree squash transaction. Two vectors, both requiring concurrent same-repo
  activity that does not occur today (chat uses scratch space, pipelines are sequential, no cron
  devloop):
  1. **A concurrent pipeline scrub is DESTRUCTIVE, not passive.** `_scrub_scout_debris` runs
     `git reset --hard` / `git clean -fdq`; if it fired during `merge_branch`'s staged-squash
     window (between `git merge --squash` and `write-tree`/`update-ref`) it could clobber the
     in-flight squash — potentially a false empty-delta (branch deleted, `merged=True`, nothing
     landed). A scrub and a merge do not overlap today (one pipeline run at a time; the merge is
     that run's own tail).
  2. **Two concurrent mergers share the target index.** The CAS serializes the LANDING (only one
     `update-ref` against `tip` succeeds; the other refuses `tip-moved`), but overlapping
     `merge --squash` + `write-tree` on the shared index are not mutually excluded. Concurrent
     same-repo mergers do not occur today.
  If either concurrency is ever introduced, build the squash tree in a temporary index
  (`GIT_INDEX_FILE`) or via `git merge-tree` so the shared worktree is never staged, and serialize
  scout's scrub against merges — keeping the ref-CAS as the guard against foreign ref writers. The
  flock is intentionally NOT reinstated for the current single-threaded workload (it carried a
  600s starvation risk + an ABA history for a race that cannot fire today).
