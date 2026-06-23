# Multi-account profile graph and routing lessons

Use this when a personal-context graph or ambient alert routing spans more than one Google Workspace account.

## Durable pattern

- Treat account access, profile graph generation, and cron routing as three separate checks.
- Successful OAuth/authentication is not enough: verify which account each workflow searches.
- Successful cron `last_status: ok` is not enough: statically audit the prompt for explicit account routing.
- Keep per-account profile graph outputs in separate directories and never overwrite the canonical personal graph with nonprofit/business artifacts.
- Keep raw discovery audits local-only, permission-restricted, and delete them once counts/review queues are sufficient.

## Account-scoped profile generation

Prefer an explicit wrapper shape:

```bash
python build_profile_graph_for_account.py \
  --account nonprofit \
  --replace \
  --build-third-party-edges
```

Required wrapper behavior:

1. Resolve the account alias through the Google Workspace account registry, not hard-coded token paths.
2. Point the underlying legacy builder at the selected account token.
3. Write outputs to an account-scoped directory, e.g. `/opt/data/personal-context/nonprofit-profile-audit*`.
4. Set directory permissions to `700` and file permissions to `600`.
5. Remove `discovery-audit-3yr.json` unless the user explicitly asks to retain raw audit data.
6. Optionally run candidate third-party edge and cluster proposal builders after profile generation.

## CPA/tax cross-account routing

Jim uses the same CPA context for both personal and Non-Profit purposes. For approved tax/CPA alerting:

- Search both `personal` and `nonprofit` Google account aliases.
- Preserve account provenance internally (`account`, `account_scoped_id`).
- Telegram summaries should include only minimal source/action/urgency.
- Do not expose tax amounts, account-specific notice details, confirmation numbers, raw snippets, attachments, or notice text.

## Governance verification pitfall

When a personal-context workspace has a manifest, do not infer tests exist from `__pycache__`, prior runs, or memory of having written them. Before claiming verification:

1. Confirm each manifest-listed `test_*.py` source file exists.
2. Run `verify_all.py` and require nonzero unit-test counts.
3. If source test files are missing but the workflow depends on them, restore/recreate focused tests before continuing.
4. Re-run the local validator, side-effect checks, and permission checks.

## Cron routing follow-up

For multi-account ambient jobs, update prompt text before relying on scheduled runs:

- Morning brief: use both accounts and preserve provenance.
- Calendar/travel alerts: use `personal` unless explicitly expanded.
- Tax/CPA watch: use both `personal` and `nonprofit` after Jim's approval that the same CPA applies to both.

Do not run delivery-producing cron jobs merely to test routing unless the user explicitly approves. Prefer connector-level read probes and static prompt audit first.

## Proof package when the user asks for both cron and graph verification

When the user says both the cron prompts and account-scoped graph update must work, produce a two-part proof package rather than a narrative status update:

1. **Cron prompt proof:** list the actual relevant cron jobs, confirm each prompt has explicit Google account routing, run the non-mutating multi-account routing diagnostic, and report auth/provenance/search-probe results. Do not treat `last_status: ok` as proof of correct account coverage.
2. **Graph refresh proof:** run the account-scoped graph wrapper for the requested account, generate candidate third-party edges and cluster proposals, delete raw discovery audits unless retention was explicitly approved, and report count-only scan/output totals.
3. **Side-effect proof:** explicitly verify no memory writes, no watcher enablement, no disclosure permission escalation, and no cron changes beyond the approved prompt edits.
4. **Durable audit:** append a compact `audit-log.jsonl` entry with approval source, changed-file hashes, count-only graph stats, and verification commands/results; update `STATUS.md` with the current checkpoint and next approval gate.
5. **Final answer shape:** give concise “proved / updated / not done / recommended next step” sections. The next step should be a narrow approval gate, e.g. approve safe neutral clusters for local routing only.

If continuing after context compaction or an interrupted run, re-read current files/job definitions and re-run verification before making claims; do not rely on remembered state from the prior context window.
