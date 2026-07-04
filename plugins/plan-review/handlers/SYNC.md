# Handler Sync

These three Python handlers are hand-synced by copy-paste, with no build step: `plan-review-cleanup.py`, `plan-unknowns-gate.py`, `plan-worktree-gate.py`.

They are synced across three repos:
- `hermes` (this repo), the canonical source of truth
- `claude-craft`'s `planning-suite` plugin
- local `claude-investigate-plan`

To change a handler, edit it here in `hermes` first, then run:
`sha256sum plan-review-cleanup.py plan-unknowns-gate.py plan-worktree-gate.py > CANONICAL.sha256`
Run `bash run-tests.sh` for a single pass/fail check of sync integrity + both gate suites.

Copy the three handler `.py` files and `CANONICAL.sha256` verbatim into the other two handler directories.
Run `bash verify-sync.sh` in all three repos to confirm each copy matches its own manifest, then diff the three `CANONICAL.sha256` files against each other to confirm they are identical.

This is a lightweight staleness tripwire: it catches in-place handler edits without re-syncing, but cannot detect a downstream repo that simply has not pulled a `hermes` change yet.
