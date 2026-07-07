# Routine Cron Audit Pattern (Weekly)

**Established:** 2026-06-25 session

## When to run

Weekly, as part of system hygiene. Can be a `no_agent` cron job or run manually
when the user reports issues ("keeps looping", "getting the same message").

## What to check

### 1. Stdout contamination in latest output files

For each job in `cron/output/`, read the newest output file and check for
`sitecustomize.py` banner text (`[slack-enhancements]`, `[profiling]`, etc.).

```python
for d in sorted(os.listdir(output_dir)):
    files = sorted(os.listdir(f"{output_dir}/{d}"), reverse=True)
    if not files:
        continue
    newest = files[0]
    content = open(f"{output_dir}/{d}/{newest}").read()
    if "slack-enhancements" in content:
        # Still contaminated — fix not live for this job
```

**Key insight:** `last_status: ok` doesn't mean the output is clean. A contaminated
job "succeeds" (exit 0) but delivers banner text as the message.

### 2. Stale schedules (event-bound jobs past event end)

Check for jobs with high-frequency schedules (`* * * * *`, `*/5 * * * *`) that
are event-bound (NCW alerts, World Cup reminders, etc.). These should be paused
after the event ends.

```python
# Check if schedule is every-minute and job hasn't been paused
if job["schedule"] == "* * * * *" and job["enabled"]:
    # Flag: high-frequency job still running — is the event over?
```

### 3. Output file accumulation

Count files per job in `cron/output/`. Flag jobs with >100 files — these are
high-frequency jobs that need periodic cleanup.

```python
for d in os.listdir(output_dir):
    count = len(os.listdir(f"{output_dir}/{d}"))
    if count > 100:
        # Flag: {d} has {count} output files — clean up
```

Cleanup command (keep latest 5):
```bash
ls -t /opt/data/cron/output/<job_id>/ | tail -n +6 | xargs rm -f
```

### 4. Delivery errors from broken platforms

Check `last_delivery_error` in the cron job list. Common patterns:
- `WhatsApp send failed: Cannot connect to host localhost:3000` — bridge down
- `Telegram send failed: RuntimeError` — transient, usually self-heals

Fix: remove the broken platform from `deliver` field (`cronjob action=update`).

### 5. Jobs with `last_status: error`

List all jobs where `last_status != "ok"` and `last_status is not None`.
These need investigation — the self-healing watchdog may have already tried
to fix them.

### 6. Jobs that never ran (`last_status: null`)

Newly created jobs that haven't fired yet. Check if their schedule is correct
and if they have all required dependencies (scripts exist, skills installed).

## Cleanup checklist

- [ ] Pause event-bound jobs past their end date
- [ ] Remove WhatsApp delivery from jobs when bridge is down
- [ ] Clean output files >100 per job (keep latest 5)
- [ ] Delete contaminated output files (banner-only content)
- [ ] Verify `sitecustomize.py` prints to stderr (not stdout)
- [ ] Check errored jobs for new failure patterns

## Integration with self-healing watchdog

The self-healing cron watchdog (pitfall #22) cannot detect stdout contamination
on `last_status: ok` jobs. This audit pattern fills that gap by directly scanning
output files rather than relying on job status. Run weekly or when a user
reports repetitive messages.

## Script implementation

See `${HERMES_HOME}/scripts/skill_curation_watch.py` for a working example of a
`no_agent` audit script that reads system state and reports only actionable
findings (silent when healthy). The cron audit follows the same pattern but
scans `cron/output/` and `cron/jobs.json` instead of skill usage stats.