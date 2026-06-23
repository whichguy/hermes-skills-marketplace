# Approved memory diff writeback pattern

Use when the user explicitly approves an exact `proposed-memory-diff.md` or equivalent reviewed memory diff for personal-context integration.

## Scope

Approval to write a memory diff means:

- Save only the exact approved durable memory entries.
- Do not create, update, pause, or remove cron jobs.
- Do not promote third-party edges beyond their existing reviewed scope.
- Do not grant disclosure, external-action, or memory-write permissions from third-party relationship records.
- Do not store raw snippets, raw source text, tax amounts/details, health details, credentials, account numbers, or confirmation numbers.

## Writeback steps

1. Re-read the exact approved diff and list entries to be written.
2. Prefer `target='user'` for compact facts about who the user is and stable preferences.
3. Use `target='memory'` for longer operational rules, alert-routing policies, alias lists, or privacy defaults when they would overflow the user profile.
4. If `memory(action='add')` fails because the `user` profile is near the limit:
   - compact older verbose user-preference entries with `memory(action='replace')` only when meaning is preserved;
   - retry the intended entry if it is genuinely user-profile material;
   - otherwise place the approved entry in the durable `memory` notes target;
   - never drop an approved entry silently.
5. If an approved entry duplicates or refines an existing memory, use `replace` instead of adding a near-duplicate.
6. Keep entries declarative, compact, and stable. Do not write task progress, PR/session artifacts, or temporary review state to durable memory.

## Local ledger updates

After memory writes, update local personal-context artifacts:

- `approved-context.yaml`
  - set metadata status such as `tier1_memory_written`;
  - add a `memory_write:` ledger with `written_at`, `approval_source`, source diff path, targets used, and entry labels written;
  - note if longer entries were placed in `memory` notes due profile size limits.
- `STATUS.md`
  - advance the phase;
  - state that approved memory entries have been written;
  - keep cron/jobs as a separate pending approval gate.
- `audit-log.jsonl`
  - append a local event with approval source, changed-file hashes, targets used, and explicit `cron_modified: false` unless cron changes were separately approved.

## Verification checklist

Run or perform:

- local schema validator, e.g. `./validate_personal_context.py`;
- a side-effect check that cron jobs were not modified;
- checks that third-party reviewed records still have `may_disclose_to_subjects: false` and `may_write_memory: false`;
- checks that sensitive/manual-review-only clusters remain unpromoted;
- file permission check for local personal-context artifacts.

If earlier regression test files are absent but the workflow depends on them, recreate a minimal verification test for the current marker/permission invariants before reporting success. Do not claim missing tests passed.

## Reporting

Final response should include:

- entries/categories saved;
- any target split between `user` and `memory` due size limits;
- local files updated;
- verification actually run and observed output;
- recommended next approval checkpoint, usually cron/job refinement using only `approved-context.yaml`.
