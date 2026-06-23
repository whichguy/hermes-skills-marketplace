# Account-scoped personal-context graph generation

Session-derived pattern for generating personal-context / relationship-graph drafts from multiple Google accounts without mixing account evidence.

## When to use

Use when the user has more than one Google Workspace account and wants profile, relationship, or approved-context work for a specific account, such as `personal` vs `nonprofit`.

## Key lesson

A multi-account Google connector is not enough by itself. Personal-context graph generation must also be account-scoped at the output layer so a nonprofit graph never overwrites or contaminates the personal graph.

## Recommended wrapper shape

Create or use a wrapper like:

```bash
python build_profile_graph_for_account.py \
  --account nonprofit \
  --replace \
  --build-third-party-edges
```

The wrapper should:

1. Resolve the selected Google account alias through the Google Workspace account resolver.
2. Point the existing builder at that account's token.
3. Write outputs to a separate directory, e.g. `/opt/data/personal-context/nonprofit-profile-audit-formal/`.
4. Refuse to replace the canonical personal-context root.
5. Lock permissions to directory `700`, files `600`.
6. Delete raw discovery audits unless the user explicitly asks to keep them.
7. Optionally generate candidate third-party edges and review clusters before deleting the raw audit.
8. Emit a summary with account, output directory, generated files, scan counts, privacy status, and permissions.

## Verification pattern

After generation, verify:

- Gmail, Calendar, Drive metadata, and Contacts API statuses are `ok` or explicitly explained.
- Contacts may legitimately return zero connections; that is not an access failure if the API call succeeds.
- Raw `discovery-audit*.json` was removed unless explicitly retained.
- Candidate edges have no `may_write_memory` or `may_disclose_to_subjects` escalation.
- Sensitive clusters remain manual-review-only.
- `verify_all.py` passes and fails closed on missing test source files.

## CPA/tax cross-account routing

If the user confirms the same CPA applies to both personal and nonprofit contexts, record account scope in local approved context and durable memory only at the routing level:

- approved people/org/domain: CPA contacts and CPA domain
- `account_scope: [personal, nonprofit]`
- `approved_use: [alert_routing, local_context]`
- tax amounts, deadlines, confirmation numbers, account-specific details, and raw tax text remain do-not-store

This approval does not authorize cron changes, watcher creation, memory writes for inferred contacts, or disclosure permissions.

## Pitfalls

- Do not trust `__pycache__` as evidence that regression tests exist; restore source `test_*.py` files and run them.
- Do not write relationship outputs into the canonical personal-context directory when auditing a nonprofit account.
- Do not promote safe-neutral third-party clusters or sensitive clusters automatically; they remain review-only until user approval.
