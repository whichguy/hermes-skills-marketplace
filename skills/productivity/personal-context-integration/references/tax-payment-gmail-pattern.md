# Tax payment discovery from Gmail — privacy-safe pattern

This reference captures a reusable pattern from a session where the user asked for outstanding federal and state tax payments and later a broader personal-context discovery pass.

## When to use

Use when the user asks for outstanding taxes, estimated tax installments, state/federal payment schedules, or confirmation of tax payments from email/Workspace records.

## Preconditions

- Treat tax and payment records as sensitive.
- If the user has not granted permission for Gmail/Workspace access in the current task, ask which source to use.
- Use current date from a tool before classifying future vs past obligations.

## Gmail search strategy

Start narrow and expand only as needed:

- Federal: `IRS`, `Internal Revenue Service`, `Direct Pay`, `EFTPS`, `estimated tax`, `payment scheduled`, `payment confirmation`.
- State: agency names and abbreviations such as `FTB`, `Franchise Tax Board`, `state tax`, `estimated tax`, `Web Pay`, `payment scheduled`, `confirmation`.
- Include year and installment terms when known: `2026 estimated tax`, `Sep 15`, `Jan 15`, `quarterly`.

Prefer search results/snippets first. Read full messages only for likely payment confirmations or notices that contain the fields needed to determine amount/date/status.

## Extraction fields

For each candidate record, extract:

- authority/jurisdiction: IRS/federal, state agency, local agency, etc.
- tax year and payment type: estimated tax, balance due, extension, etc.
- scheduled date or due date
- amount
- status: scheduled, completed, cancelled, failed, informational, ambiguous
- evidence: email date, sender, confirmation number if present and safe to show

## Classification rules

- Outstanding = scheduled/future obligation with date after or equal to current date, or explicit unpaid/balance-due notice.
- Completed = confirmation says paid/processed and date is in the past.
- Historical = past installment or prior-year payment; exclude from remaining total unless user asks for history.
- Ambiguous = duplicate-looking, forwarded, reminder-only, missing amount, or status unclear; do not silently include in totals.

## Deduplication checks

Before totaling, dedupe by:

- confirmation number
- same agency + amount + payment date + tax year
- forwarded or repeated notification copies
- calendar reminders derived from an email confirmation

If two records have the same amount/date but different confirmation IDs, list them separately and flag the possibility of duplicate scheduled payments rather than assuming either way.

## Reporting pattern

Use Telegram-friendly bullets:

```text
## Federal / IRS
- Jun 15, 2026: $15,500 — scheduled estimated tax payment; confirmation email Apr 4, 2026

Federal remaining total: $46,500

## California FTB
- Jun 15, 2026: $38,500 — scheduled payment; confirmation 123...

State remaining total: $...

## Grand total outstanding
$...

Notes:
- Excluded completed/past payments: ...
- Ambiguous items: ...
- Privacy: read-only search; no payments made; nothing saved to memory.
```

## Safety notes

- Never initiate, cancel, or modify a tax payment without explicit user approval.
- Never expose full SSNs, bank account numbers, or full tax IDs in the response.
- Do not persist exact amounts or tax details in durable memory unless the user approves a specific memory entry.
