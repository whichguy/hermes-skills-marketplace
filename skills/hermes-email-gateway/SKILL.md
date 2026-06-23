---
name: hermes-email-gateway
description: Configure, verify, and troubleshoot Hermes Gateway email platform via
  IMAP/SMTP.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags:
    - email
    - gateway
    - imap
    - smtp
    - gmail
    - troubleshooting
    - hermes
    created_by: agent
    related_skills:
    - hermes-agent
    - himalaya
    config:
    - key: hermes-email-gateway.enabled
      description: Enable hermes-email-gateway skill behavior
      default: true
      prompt: Enable hermes-email-gateway skill?
    category: productivity
platforms:
- linux
- macos
- windows
---
---

# Hermes Email Gateway

Use this skill when setting up or diagnosing the Hermes Gateway email platform: `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, IMAP/SMTP hosts, app passwords, allowlists, inbound processing, and email log verification.

## Core workflow

1. **Do not print secrets.** When inspecting `.env`, report key presence, counts, lengths, domains, and file mode only. Never echo `EMAIL_PASSWORD`.
2. **Check required env keys:** `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `EMAIL_IMAP_HOST`, `EMAIL_SMTP_HOST`; optional `EMAIL_IMAP_PORT`, `EMAIL_SMTP_PORT`, `EMAIL_ALLOWED_USERS`, `EMAIL_POLL_INTERVAL`.
3. **For Gmail/Google Workspace, use an app password.** Spaces in Gmail app passwords are acceptable; direct Python IMAP/SMTP tests can try both raw and spaces-stripped forms without printing either value.
4. **Restart/reconnect after env changes.** Gateway processes snapshot env at startup; auth fixes may not apply until `/restart` or container/gateway restart.
5. **Read logs with a timestamp cutoff.** Avoid mixing stale auth failures with current state. Ask/check “after <time> UTC” when a restart or credential change occurred.
6. **Verify both SMTP delivery and inbound dispatch.** A sent email appearing in Gmail confirms SMTP and mailbox delivery, but not necessarily Hermes inbound handling.

## Important pitfall: self-message tests are not full inbound tests

Hermes email adapter intentionally skips messages where the sender equals `EMAIL_ADDRESS`:

```python
# Skip self-messages
if sender_addr == self._address.lower():
    return
```

So a test sent from `EMAIL_ADDRESS` to itself can prove SMTP delivery and Gmail receipt, but Hermes will not dispatch it as a user message. For a full inbound test, send from a different allowlisted address, e.g. a personal Gmail alias in `EMAIL_ALLOWED_USERS`, to `EMAIL_ADDRESS`, then look for a log like:

```text
[Email] New message from sender@example.com: <subject>
```

## Verification checklist

- [ ] `.env` exists and has exactly one `EMAIL_PASSWORD=` entry.
- [ ] `.env` permissions are restrictive, ideally `0600`.
- [ ] IMAP login succeeds directly from inside the running Hermes environment.
- [ ] SMTP login/send succeeds directly from inside the running Hermes environment.
- [ ] Gateway logs after the restart show `IMAP connection test passed`, `SMTP connection test passed`, and `✓ email connected`.
- [ ] Full inbound test uses a non-self sender that is present in `EMAIL_ALLOWED_USERS`.

## References

- `references/gmail-app-password-debugging.md` — concise diagnostic recipe for Gmail app-password auth and Hermes inbound/self-message tests.
