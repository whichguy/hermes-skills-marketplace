# Important-contact review approvals

Use this pattern when the user approves or withholds approval for people who may be important contacts in a local personal-context workspace.

## Trigger

The user gives a scoped decision such as:

- “Approve Travis and Michelle as normal-priority Canyon Creek contacts.”
- “Approve Kevin as normal-priority Canyon Creek contact.”
- “Keep Liz pending / needs more context.”

## Local artifacts

Recommended files under `/opt/data/personal-context/`:

- `important-contacts-reviewed.yaml` — machine-readable reviewed contact decisions.
- `important-contacts-reviewed.md` — concise human-readable review summary.
- `pending-contact-role-review.yaml` — keep unresolved people pending rather than silently promoting.
- `verify_important_contacts_reviewed.py` — explicit fail-closed side-effect/privacy verifier.
- `approved-context.yaml` — only append the approved local/alert-routing context, not memory permissions.
- `STATUS.md` and `audit-log.jsonl` — record scope, timestamps, verification, and changed-file hashes.

## Approval semantics

Treat approval as narrow:

- Approved contacts may be used for local context, routing, and disambiguation according to the user’s stated priority/scope.
- Approval does **not** grant disclosure permission.
- Approval does **not** grant durable Hermes memory-write permission.
- Approval does **not** create or enable an important-contact watcher.
- Approval does **not** create or update cron jobs.
- People explicitly kept pending stay pending with a `needs_more_context`/similar status and no alert-routing approval.

For organization-scoped approvals such as Canyon Creek contacts, use the already-approved broad organization context when present, but do not infer specific roles beyond the user’s wording.

## Suggested reviewed YAML shape

```yaml
schema_version: 1
reviewed_at: "YYYY-MM-DDTHH:MM:SSZ"
reviewed_by: Jim
source: user_approved_chat
approved_contacts:
  - person_id: travis_marsh
    display_name: Travis Marsh
    organization_context: canyoncreekchurch.org
    priority: normal
    status: approved
    approved_use:
      - local_context
      - alert_routing
      - disambiguation
    permissions:
      may_use_for_routing: true
      may_use_for_disambiguation: true
      may_disclose_to_subjects: false
      may_write_memory: false
      may_enable_watcher: false
pending_contacts:
  - person_id: liz_boyadzhyan
    display_name: Liz Boyadzhyan
    status: needs_more_context
    approved_use: []
    permissions:
      may_use_for_routing: false
      may_use_for_disambiguation: false
      may_disclose_to_subjects: false
      may_write_memory: false
      may_enable_watcher: false
```

## Verification checklist

After writing reviewed-contact artifacts:

1. Run the personal-context validator.
2. Run an explicit verifier that checks:
   - expected approved count and pending count,
   - all approved contacts preserve `may_disclose_to_subjects: false`, `may_write_memory: false`, and `may_enable_watcher: false`,
   - pending contacts have no routing/alert permissions,
   - no watcher/cron marker was enabled,
   - no memory-write marker was set.
3. Apply restrictive permissions: data files `600`, verifier scripts `700`, workspace `700` when possible.
4. Append `audit-log.jsonl` with the user approval wording, changed-file hashes, and verification result.
5. Update `STATUS.md` with the current checkpoint and recommended next approval gate.

## Recommended user-facing summary

Report:

- who was approved and at what priority/scope,
- who remains pending,
- which files changed,
- exact verification outcome,
- explicit non-actions: no memory write, no watcher, no cron change, no disclosure permission.

If proposing the next step, make it a separate approval gate, for example: “Create an important-contact watcher for these approved contacts only; Telegram alerts only; no memory writes; no raw snippets; no sensitive details.”
