# The scout → build pipeline (relentless-solve as pathfinder)

**Architecture verdict (user decision 2026-07-03).** Devloop does NOT call relentless-solve
as an inner component — relentless is the skill family's ORCHESTRATE role (acyclic,
orchestrator-at-top). The composition exploits **cost asymmetry**: relentless's cost scales
with *uncertainty* (cheap read-risk scouting → information; a scout's mistake costs one wasted
build attempt), devloop's cost is fixed *rigor* per step (verified merged code; a builder's
mistake is merged wrong code). Scout first, build second, verify always.

The seam is a CLI subprocess + an artifact on disk (`scout-steps.json`), no imports in
either direction — PINNED by the RelentlessContract tests in `tests/test_scout.py` (run flags,
outcome vocabulary, state-dir layout; SKIP when relentless-solve is absent).

## Running the pipeline

```bash
# scout the happy path, then build each step verified (in-container; requires pytest)
devloop-pipeline "<goal>" --repo /path/to/repo

# just the step list (build nothing):
devloop-pipeline "<goal>" --repo /path/to/repo --scout-only

# discard prior scout AND drain state for this request (default: identical request against the
# same repo resumes the earlier scout/drain; the slug hashes request + repo into a 16-hex
# fingerprint, so a different repo always gets fresh state):
devloop-pipeline "<goal>" --repo /path/to/repo --fresh
```

## Mechanics (`scout.py`)

The scout intent demands a read-only investigation whose deliverable is
`$HERMES_HOME/relentless/<slug>/scout-steps.json` — ordered steps with a strict
`success_criterion` each, or an honest `no_path` reason. The scout's own `plan.json` tasks
are its *investigation moves*; the steps artifact is its *findings*.

`load_steps` validates fail-closed (schema, step cap, steps XOR no_path — any violation reads
as scout failure). Build happens ONLY on a **concluded** scout (outcome `success`);
`information-dry` + `no_path` is an honored "no viable path"; capped/dry leftover steps surface
as **UNCONCLUDED** and are never built.

Each step then runs the full verified devloop via the bridge lifecycle (finalize +
auto-merge + trace) under `project.run_project`'s bounded lessons drain. A step counts
achieved ONLY if it COMPLETEd **and merged** (an unmerged COMPLETE downgrades to
`MERGE_DEGRADED` and re-attempts), so ordered steps compose: each merge lands before the next
step's worktree is cut. The step's success criterion rides into the devloop charter; a fuzzy
step is honestly bounced by the vague-goal gate and lands `blocked`.

## Agent-overreach containment

Code gates at BOTH layers (live-caught 2026-07-03):

- **Scout layer:** a scout task executor trial-implemented the feature in the target repo and
deleted a test file while "verifying feasibility".
- **Devloop layer:** a phase dispatcher escaped its `.worktrees` checkout mid-run and deleted a
tracked file from the target repo's main working tree.

The bridge now snapshots repo status before every run and restores any NEWLY dirty main-tree
path afterwards (legitimate output only ever arrives as commits; pre-existing user dirt is
never touched — `devloop_result.boundary_restored`).

The pipeline refuses a repo with uncommitted changes up front (it merges verified steps into
that repo anyway, and the scrub needs a clean baseline). After the scout, any repo
modification is hard-restored (`reset --hard` + `clean -fd`) and the breach reported visibly;
a restore that FAILS fails the whole scout closed. The intent additionally tells the agent to
experiment only on copies outside the repo, but the git gate is the guarantee.

## Exit contract

- `0` = every step built AND merged, or a clean informational stop (`--scout-only` /
  concluded no-path)
- `1` = blocked/pending steps or an unconcluded scout
- `2` = usage / scout failure

## Receipts

- Drain state: `<write-safe>/devloop-pipelines/<slug>/.devloop/` (PLAN.json + LESSONS.jsonl —
  re-running the same request against the same repo resumes)
- Bundle: `<write-safe>/devloop-traces/pipeline-<slug>/` (scout-steps.json + report.md)
- Full scout state: `$HERMES_HOME/relentless/<slug>/`

## Drain resume validation

PLAN.json must use schema version 1 and its root purposes must exactly match the current run's
purposes. Corrupt or foreign state refuses closed with a non-empty `blocked` result and an
informative report instead of reseeding or blindly resuming. `--fresh` clears both scout and
drain state; both deletions are verified and refuse closed if the state directory remains.

## Deferred

- Closed feedback loop (devloop failure reasons folded back into the scout ledger for
  automatic re-scouting).
- Any relentless-side devloop engine/route.

Both wait until this explicit seam proves its step grain live.
