#!/usr/bin/env bash
# Cron entrypoint for the daily Hermes GitHub backup. WATCHDOG pattern:
#   - SILENT on success (empty stdout => no_agent cron sends nothing)
#   - ALERTS only on failure (so you hear about it when backup breaks)
#
# Why watchdog and not "ping on success": cron/jobs.json rewrites its
# next_run_at/last_run_at timestamps on EVERY scheduler tick, so a
# success-ping backup would fire daily on meaningless churn.
#
# Register as a no_agent cron. The cron `script` field needs a path RELATIVE
# to $HERMES_HOME/scripts/ and CANNOT pass args — so this wrapper hardcodes
# --quiet. Point it at the real script via its absolute path below.
out=$("${HERMES_HOME:-/opt/data}/scripts/git-sync/hermes-sync.sh" --quiet 2>&1)
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "⚠️ Daily Hermes GitHub backup FAILED (exit $rc):"
  echo "$out"
  exit "$rc"
fi
exit 0   # success => silent
