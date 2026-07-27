# Handler Sync

These three Python handlers are hand-synced by copy-paste, with no build step:
`plan-review-cleanup.py`, `plan-unknowns-gate.py`, `plan-worktree-gate.py`.

They are synced across:

1. **hermes-skills-marketplace** `plugins/plan-review/handlers/` (this repo)
2. **claude-craft** `plugins/planning-suite/handlers/`

After the 2026-07 plan-review consolidation (retired `.review-ready` ExitPlanMode
gates; "was this plan reviewed?" owned by plan-oversight/soft_exit), both trees
must carry the same three files + `CANONICAL.sha256`. Either repo may land a
change first; the other must copy and re-verify before merge.

To change a handler:

1. Edit the `.py` file in one repo.
2. `sha256sum plan-review-cleanup.py plan-unknowns-gate.py plan-worktree-gate.py > CANONICAL.sha256`
3. Run `bash run-tests.sh` (or the per-handler `*.test.sh`).
4. Copy the three `.py` files + `CANONICAL.sha256` (+ tests if changed) into the peer repo.
5. Run `bash verify-sync.sh` in both repos; `diff` the two `CANONICAL.sha256` files.

`claude-craft` CI fails if its `CANONICAL.sha256` diverges from hermes `main`.
