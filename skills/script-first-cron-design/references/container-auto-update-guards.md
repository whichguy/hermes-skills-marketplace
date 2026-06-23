# Container auto-update guards for Hermes cron

Use this reference when a user wants a Dockerized service, especially Hermes itself, kept current automatically.

## Pattern

Split the system into two pieces:

1. **Host-side updater** performs mutation: `docker pull`, `docker compose up -d`, Watchtower, or a host systemd timer. Containers normally cannot safely recreate themselves unless granted host Docker access.
2. **Hermes no-agent guard** performs verification: a script-only cron that checks version/digest state, prints nothing when healthy, and emits a concise alert when the host updater is missing or ineffective.

## Safety rules

- Ask explicit approval before mounting `/var/run/docker.sock`; it grants host-level Docker control.
- Prefer Watchtower `--label-enable` and per-container labels so only approved services auto-update.
- Schedule verification after the updater window, not at the same minute.
- Keep guard output silent on success. In no-agent cron, any stdout becomes a user-visible message.
- Dedupe alerts by digest and/or day so broken update paths are visible without spamming.

## Compose shape

```yaml
services:
  hermes:
    image: nousresearch/hermes-agent:latest
    labels:
      - "com.centurylinklabs.watchtower.enable=true"

  watchtower:
    image: containrrr/watchtower:latest
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    command:
      - --schedule
      - "0 30 10 * * *"
      - --cleanup
      - --label-enable
    environment:
      - TZ=UTC
```

## Guard script behavior

A robust guard should:

- Query the upstream image digest for the current architecture.
- Check whether Docker is available from the runtime.
- If Docker is unavailable but the local `hermes --version` no longer reports an update, stay silent.
- If Docker is unavailable and Hermes still reports an update, alert with the host activation/manual commands.
- If Docker is available, compare local and upstream digests, pull/recreate only if needed, and report only actual changes or failures.

## Verification

- Syntax-check the script.
- Run it once manually and verify healthy path stdout is empty.
- Re-list cron job after update to confirm `no_agent: true`, schedule, script, and delivery.
- After the host command is run, verify version changed and the daily guard is silent.
