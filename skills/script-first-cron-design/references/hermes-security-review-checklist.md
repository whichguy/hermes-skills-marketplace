# Hermes Security Review Checklist

## Purpose

Use this checklist when reviewing a Hermes setup for inadvertent exposure or risky defaults. It is intentionally non-destructive first: inventory and classify, then apply only reversible local hardening changes that are clearly safe.

## Read-only inventory

Do not print secret values. Report only whether values are set and file modes.

Check:

- `config.yaml` focused security sections: `security`, `privacy`, `approvals`, `gateway`, `dashboard`, `memory`, `skills`, `terminal`, `browser`, `platform_toolsets`, `plugins`, `command_allowlist`.
- `.env` variable names only, never values.
- Credential/file modes: `.env`, `auth.json`, `cron/jobs.json`, Google token/client-secret files, profile config files.
- Cron jobs: name, schedule, script, `no_agent`, enabled toolsets, delivery target, last status.
- Scripts used by cron for side effects: Gmail/Drive/Calendar writes, `docker compose`, filesystem deletes/chmods, network POSTs.
- Listening ports and relevant processes: especially dashboard/API services.
- Dashboard process command line and env flags, especially `--host`, `--insecure`, `HERMES_DASHBOARD_INSECURE`, and bind address.
- Whether `/var/run/docker.sock` is mounted.

## High-signal risks

- Dashboard running with `--insecure` and bound to `0.0.0.0` is high risk unless intentionally protected by a trusted reverse proxy/VPN. Treat `HERMES_DASHBOARD_INSECURE=1` as an explicit break-glass flag.
- Broad messaging-platform toolsets (`terminal`, `file`, `cronjob`, `memory`, `messaging`) make allowed-user/channel controls critical.
- LLM cron jobs with terminal access should have explicit prompt guardrails: no external mutation, no memory writes, no cron edits, no credential disclosure.
- `approvals.mode: off`, broad `command_allowlist`, lazy installs, or threat-scanner fail-open settings increase blast radius.
- Writable group/other permissions on config or credential files should be tightened.

## Safe hardening changes usually OK to apply

These are reversible config/file-mode changes and usually low-risk:

- `privacy.redact_pii: true`
- `memory.write_approval: true`
- `skills.write_approval: true`
- `command_allowlist: []` when it contains broad entries like remote-content piping or script execution bypasses.
- `security.tirith_fail_open: false`
- `security.allow_lazy_installs: false`
- `chmod 600` for config/secret/token files.

Use Hermes config commands for security-sensitive config when direct file patching is guarded, then verify by reading sanitized config. If a CLI writes `command_allowlist` as the string `'[]'`, correct it back to an actual YAML list with a parser-aware write.

## Approval-gated changes

Ask before changes that may break access or require container/service restart:

- Disabling dashboard or changing dashboard bind host.
- Removing `HERMES_DASHBOARD_INSECURE=1` in container/service env.
- Restarting gateway/dashboard/container.
- Disabling major toolsets on Telegram/Slack.
- Revoking tokens, deleting credentials, deleting cron jobs, or changing OAuth scopes.

## Reporting shape

Keep the report concise:

- Biggest finding first, with severity.
- What was hardened immediately.
- What looked good.
- Remaining medium/high risks requiring approval.
- Recommended next step.

Avoid dumping raw config, env values, tokens, or long process output.
