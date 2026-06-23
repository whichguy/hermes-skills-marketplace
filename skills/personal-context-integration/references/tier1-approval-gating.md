# Tier 1 approval gating pattern

Use this reference when a user approves a personal-context review prompt with a broad message like “yes approved” or “go forward.”

## What broad approval means

Broad approval after a Tier 1 review prompt is enough to:

- Update local `approved-context.yaml` for clearly listed Tier 1 items.
- Update `STATUS.md` to reflect the new phase.
- Append a minimal `audit-log.jsonl` event.
- Generate `proposed-memory-diff.md`.

It is **not** enough to:

- Write durable Hermes memory.
- Create, update, pause, or remove cron jobs.
- Promote ambiguous people/items that requested exact role confirmation.
- Store sensitive tax/health/account details.

## Recommended file updates

- `approved-context.yaml`
  - `metadata.status: tier1_approved_memory_diff_pending`
  - `metadata.updated_at`
  - `metadata.tier1_approval` with source, reviewer, timestamp, and scope
  - approved self aliases, people, orgs, and alert sources
  - `sensitive_do_not_store` rules
  - `pending_role_confirmation` for ambiguous people/items
  - `memory_entries_written: []`

- `proposed-memory-diff.md`
  - numbered exact entries to be saved
  - explicit “not proposed for memory yet” section
  - clear approval phrase requested from user

- `STATUS.md`
  - phase changed to memory-diff pending
  - no memory written yet
  - no cron modified yet

- `audit-log.jsonl`
  - one JSON object per event
  - no raw sensitive snippets/details
  - include booleans for `memory_written`, `cron_modified`, `sensitive_details_stored`

## Memory diff style

Keep entries compact and declarative. Good examples:

- `Jim's approved self aliases include ... for self-detection and avoiding misclassification.`
- `Kelly Wiese is an approved family/household contact for Jim.`
- `Wallin CPA / wallin-cpa.com is approved for tax/CPA alert routing only; tax amounts, deadlines, confirmation numbers, account-specific details, and raw tax text should not be stored in memory.`

Avoid:

- Raw snippets or document text.
- Payment amounts/deadlines/confirmation numbers.
- Unreviewed graph guesses.
- Specific people whose role/importance was not confirmed.

## Verification

Before reporting back:

- Parse YAML files.
- Validate JSONL audit entries.
- Confirm local permissions remain restrictive where applicable.
- State explicitly that durable memory and cron jobs were not modified unless they actually were.
