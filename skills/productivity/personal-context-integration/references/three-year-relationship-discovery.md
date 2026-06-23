# Three-year relationship discovery pattern

Use this when the user asks to deepen a personal-context graph beyond an initial 6-12 month pass.

## Trigger

- User asks to search farther back for key identifiers, relationships, aliases, roles, organizations, or routing sources.
- User provides a new identity fact during review (for example an alternate email address or job/organization role).

## Workflow

1. Capture user-provided identity facts in `approved-context.yaml` immediately as `source: user_provided`, but do not write durable Hermes memory until the exact memory diff is approved.
2. Generate or adapt a read-only discovery script with a longer window, usually ~1095 days / 3 years.
3. Keep privacy scope narrow:
   - Gmail: metadata/snippets only; Inbox and Sent are usually enough for relationship graphing.
   - Calendar: metadata only.
   - Drive: metadata only; no document downloads.
   - Contacts: names/emails/orgs only; avoid phone numbers.
4. Preserve the earlier shorter-window artifacts. Write long-window outputs with a suffix such as `-3yr` instead of overwriting `relationships.yaml`, `domains.yaml`, `review-queue.md`, or `discovery-audit.json`.
5. Add the newly provided self aliases to self-detection before running the graph, otherwise the user's own org email may appear as an external contact.
6. Add organization-specific topic keywords and domain overrides when the user confirms a role, for example `fortifiedstrength.org` -> `organization_led_by_user`.
7. After the run, create a cleaned review queue instead of asking the user to inspect raw graph output.

## Clean review queue structure

Group candidates by how they should be reviewed:

- Approved/user-provided identifiers to include in the memory diff.
- Organization/role-specific contacts discovered from the longer pass.
- Family/personal candidates needing exact labels.
- Church/nonprofit or community candidates needing roles.
- Alert-routing-only candidates such as CPA/tax, home vendors, travel, insurance, finance, or admin sources.
- Sensitive/local-only sources such as health/medical, tax amounts/details, finance account details, raw snippets, account numbers, and credentials.

For each person, include compact evidence counts only:

```text
- Name <email> — proposed role; contexts; signal N: inbox X, sent Y, cc Z, calendar W, contacts true/false; flags: CC-heavy / sensitive
```

Do not include raw snippets in the review queue.

## Pitfalls

- A longer window increases keyword pollution. Do not promote candidates directly to memory just because the signal count is high.
- CC-heavy contacts are often thread participants rather than relationships. Flag them and require manual confirmation.
- Vendor/no-reply senders can become high-signal nodes; keep them as alert-routing candidates, not relationships.
- Organization roles discovered from an alias or domain should be saved as broad org context first; specific people still need role confirmation.
- Tax/health/finance/legal details remain local-only unless the user explicitly approves a very narrow alerting use.

## Verification

After the run:

- YAML/JSON/JSONL artifacts parse successfully.
- Local files remain restrictive (`700` directory, `600` files where supported).
- `STATUS.md` records the phase and next approval checkpoint.
- `audit-log.jsonl` records the run without raw sensitive content.
- Durable memory is still untouched until the user approves the exact diff.
