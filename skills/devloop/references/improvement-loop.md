# Improving devloop (the improvement loop)

Devloop is the SDLC engine, so it is developed the same disciplined way it asks callers to
work — test-first, one purposefully-chosen change at a time, with each step's learning
captured.

## Standing procedure

1. **Develop in a bind-mounted worktree, not the live branch.** The deployed devloop lives in
   the `~/.hermes` checkout, where sync-crons commit continuously — editing there interleaves
   cron commits into the work and risks the engine editing its own running copy. Instead cut a
   worktree UNDER `~/.hermes` so it is bind-mounted into the container and in-container testable
   (`git -C ~/.hermes worktree add ~/.hermes/<wt> -b <branch> <base>` → visible at
   `/opt/data/<wt>`, auto-ignored by the root `/*` whitelist, invisible to the cron's
   `git add -A`). All edits + subagents scope to the worktree; the main checkout stays put.
2. **Iterate:** discover (read-only Explore / Codex sweep) → **pin a purposefully-chosen test**
   (the test states the invariant BEFORE the change) → improve (an implementation worker scoped
   to the worktree) → run **only that test + the merge smoke set** (TESTING.md names it) →
   commit to the worktree branch with explicit-path staging.
3. **Capture the learning every iteration** (and on every non-trivial failure): write down what
   the test revealed, why the change is correct — *not merely green* — and any new corner case.
   On a non-trivial failure, **diagnose the root cause; never patch to green.** A red result is a
   real defect, a test bug, or a design signal — decide which, record the reasoning, then act.
   Durable lessons promote to `DECISIONS.md` + the `project_devloop_redesign` memory.
4. **Seal once, exhaustively:** run the full `tiers.py fast` suite + the full mutation guard
   (`0 survived / 0 stale`) + an independent Codex cross-check on the change; then merge the
   worktree branch back into the deployed branch (do NOT blind-ff — the cron may have advanced
   it; `merge` and resolve), push, and **tear down the worktree + branch**.

## Two execution modes

- **Interactive** sprints run **inline, in one session** — the accumulated working context and
  the warm prompt cache ARE the value, and `/loop` would summarize them away between
  iterations. Reserve **`/loop`** for *autonomous/unattended* improvement cycles, where surviving
  compaction across sessions with no human in the loop is the whole point. (The ref-CAS
  landing sprint — 2026-07-04 — was the inline kind; see DECISIONS.md.)

## Merge smoke set

The per-iteration cadence deliberately runs only the targeted test + the merge smoke set (the
fast, high-signal core of the `worktree-merge` group):

- `test_merge_branch_happy_fast_path_merges_deletes_branch`
- `test_merge_branch_cas_landing_parents_tip_single_parent_and_clean_tree`
- `test_merge_branch_cas_landing_sync_path_leaves_clean_tree`
- `test_merge_branch_refuses_when_foreign_write_moves_head_during_verify`
- `test_merge_branch_cas_refuses_when_head_moves_after_precheck_before_ref_update`
- `test_merge_branch_real_squash_conflict_resets_clean_and_keeps_branch`

Run it: `uv run --with pytest python3 tests/tiers.py suite worktree-merge` or
`uv run --with pytest python3 -m pytest tests/test_worktree_more.py -k merge_branch`.

## Mutant registry integrity

An iteration that changes a guarded code line or edits `tests/mutants.py` MUST also run the
mutant-registry integrity check (`tests/test_mutants_registry.py`, or
`python3 tests/mutants.py` which checks the registry before running). A landing-mechanism
change can silently STALE a mutant whose `old` text you removed, and the unit suite alone will
not catch it (learned 2026-07-04). Registry integrity is cheap.

## Scoped mutant rule

A killing mutant in `tests/mutants.py` is REQUIRED only for a **critical-surface** guard — a
guard whose removal would let a run reach a COMPLETE / merged / exit-0 outcome it should not.
Critical surfaces: merge landing & honesty, scout→build gating, CLI exit contract, drain
honesty, and the loop's completion gates. Routine shape/type guards rely on their direct unit
test. See TESTING.md's "Invariant for changes" for the full breakdown.

## Token caps and timeouts

Per project policy, token caps and per-call timeouts are sourced from the Hermes runtime config
at call time, never hardcoded low to "fix" a slow model. Read `config.py` and `evidence.py`.
