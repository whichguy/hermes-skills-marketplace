# Gmail app-password debugging for Hermes Email Gateway

Use this recipe when Hermes email logs show Gmail/Google Workspace IMAP or SMTP auth failures.

## Safe inspection

Never print app passwords. Inspect only metadata:

- `EMAIL_ADDRESS` domain/local-part length
- `EMAIL_IMAP_HOST` and port
- `EMAIL_SMTP_HOST` and port
- whether `EMAIL_PASSWORD` is present
- raw password length
- whether it contains spaces
- spaces-stripped length
- whether spaces-stripped length is 16 characters
- `.env` file mode

## Direct auth probe pattern

From inside the same environment/container as the gateway, parse `/opt/data/.env` and test IMAP/SMTP without printing secrets. For Gmail app passwords, try both raw and spaces-stripped password forms; Gmail accepts normal 16-character app passwords and may also accept the display form with spaces depending on the client path.

Expected healthy IMAP outcomes:

```text
auth_test raw: OK (OK)
auth_test spaces_stripped: OK (OK)
```

If direct probes pass but gateway logs still fail, suspect stale gateway env. Restart/reconnect the gateway and then evaluate only log lines after the restart timestamp.

## Log cutoff discipline

When credentials were recently changed, stale failures are misleading. Check only lines after the change/restart time, e.g. after `19:07 UTC`, and look for:

```text
IMAP connection test passed
SMTP connection test passed
✓ email connected
```

## Self-message caveat

A test email sent from `EMAIL_ADDRESS` to `EMAIL_ADDRESS` can confirm SMTP send and inbox delivery, but Hermes will skip it at dispatch because self-messages are ignored. For full inbound processing, send from a different address listed in `EMAIL_ALLOWED_USERS`.

## Allowlist typo check

When inbound messages do not dispatch, inspect `EMAIL_ALLOWED_USERS` for exact lowercase sender matches and typoed domains. A misspelled allowlisted domain silently blocks full processing even when IMAP/SMTP auth is healthy.
