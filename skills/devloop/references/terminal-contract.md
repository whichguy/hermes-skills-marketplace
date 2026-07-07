# Terminal contract and merge mechanics

## Terminal types

- **COMPLETE** — DoD satisfied + whole-suite green. Work is committed on `devloop/<name>` and
  AUTO-MERGED into the target's current branch, unless `--keep-branch` (verified branch kept
  unmerged by request).
- **HUMAN_REVIEW** — needs-your-input outcome (blocking open questions / gate routing /
  back-off exhausted / test-fault), surfaced with blocking questions AND the partial grounding
  chain. Not an engine failure.
- **NO_TERMINATION** — bug sentinel (`max_passes` exhausted); always an error.

## Result shape

`devloop_result` = `{terminal, branch, worktree, repo, changed_files, merged, kept_branch,
merge_reason, synced, sync_resolved, sync_fixed, code_path, reason, trace_path, grounding,
needs_human, open_questions}`. One shape for every outcome; a fail-closed crash result carries
the same keys, with `needs_human: False`.

## Exit code contract (hard)

- `0` = a real, gate-verified COMPLETE whose outcome landed (merged, or kept under
  `--keep-branch` with the branch actually kept) — nothing else.
- `1` = failure or merge degradation (could not land safely).
- `2` = needs your input (blocking questions / gate routing).

## Pre-merge sync

If the target ADVANCED past the run's fork point, devloop first merges the target into the
run branch in a throwaway checkout and re-runs the whole-suite regression on the COMBINED tree.
Conflicts go to the coder LLM (code-guarded — never test files, no markers may survive) and
a red combination gets ONE bounded LLM fix; the regression gate decides. Fail-safe: dirty
tree / unresolved conflict / red combination / detached HEAD / a checkout that SWITCHED
branches mid-run (the derivation branch is recorded and enforced, 2026-07-03) degrade to a
kept branch-for-review with the reason.

## Lock-free merge landing via git ref-CAS (2026-07-04)

The squash is committed with `git commit-tree` parented on the exact `tip` the combined tree
was verified against, then published with:

```bash
git update-ref refs/heads/<target> <new_commit> <tip>
```

This advances the ref ONLY if it still points at `tip`. A concurrent devloop merge or a
foreign write (e.g. a cron) that moved HEAD off `tip` makes the CAS refuse atomically
(`tip-moved`), leaving the branch for review. No held lock, no serialization wait, no ABA.
This is git's own primitive for the invariant "only land a combination verified against the
current tip."

The ref-CAS landing sprint is recorded in DECISIONS.md (2026-07-04).

## Known residual

The ref-CAS makes the **ref update** atomic but NOT the shared index/worktree squash
transaction. Between `git merge --squash` and the `update-ref` CAS the shared worktree
briefly holds the staged squash; a *concurrent* pipeline scrub would not merely observe it —
`_scrub_scout_debris` runs `reset --hard`/`clean -fdq` and could DESTROY the in-flight squash
(a false empty-delta), and two concurrent mergers share the target index (the CAS serializes
the landing, not the staging). Not reachable under today's workload (chat=scratch, pipelines
sequential, no cron devloop). If such concurrency is introduced, the fix is a temp-index /
`git merge-tree` squash + serializing scout's scrub against merges. The flock is deliberately
not reinstated (600s starvation + ABA for a race that cannot fire today).

## Known limitations (by design)

- The worktree-boundary guard tracks dirty-path membership. It can restore a newly dirtied path,
  but cannot detect content changes to a path that was already dirty before the run.
- Gitignored paths are invisible to that guard. Devloop intentionally writes normal state under
  ignored `.devloop/` and `.worktrees/` directories, so closing that gap would erase legitimate
  runtime output.
- A crash after a squash-merge lands but before PLAN.json records the completed attempt causes
  resume to re-attempt that step. `PROJECT_MAX_ATTEMPTS` bounds the redundancy, and the failure
  direction is honest: re-verification rather than silently skipping work that may not have
  landed.
- The ref-CAS protects the ref update but not the shared index/worktree squash transaction
  (see above).

## Concurrent runs on one repo

Each run is isolated in its own `<repo>/.worktrees/<name>` checkout on branch
`devloop/<name>` cut from the recorded base SHA + start branch; per-run oracle filenames prevent
collisions. The pipeline's clean-tree pre-check and post-scout scrub run directly (the CAS is
the only serialization point); git-status read failures refuse closed. Cross-run SEMANTIC
conflicts still degrade to branch-for-review by design.
