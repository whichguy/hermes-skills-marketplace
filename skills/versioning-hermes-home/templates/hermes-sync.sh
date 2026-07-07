#!/usr/bin/env bash
# hermes-sync — commit & push Hermes customizations to a (private) GitHub repo.
#
# Usage:
#   hermes-sync ["commit message"]   manual: prints status, pushes
#   hermes-sync --quiet              cron:   silent on clean, brief on push
#
# Honors the fail-closed .gitignore — secrets never leave the machine.
# A safety gate aborts the push if any sensitive path is ever staged.
#
# TEMPLATE: set HHOME to the instance's HERMES_HOME, drop in scripts/git-sync/.
set -uo pipefail
HHOME="${HERMES_HOME:-/opt/data}"

QUIET=0; MSG=""
for arg in "$@"; do
  case "$arg" in
    --quiet|-q) QUIET=1 ;;
    *) MSG="$arg" ;;
  esac
done

cd "$HHOME" || { echo "hermes-sync ERROR: $HHOME missing"; exit 1; }
export GH_NO_UPDATE_NOTIFIER=1
export PATH="$HHOME/bin:$PATH"

# Back up the branch that is actually checked out — NOT a hardcoded 'main'.
# (A hardcoded 'origin main' silently no-ops when HEAD is any other branch.)
# Refuse a detached HEAD: no unambiguous branch to push, never guess.
BRANCH=$(git symbolic-ref --quiet --short HEAD || true)
if [ -z "$BRANCH" ]; then
  echo "⚠️ hermes-sync ABORTED — detached HEAD, refusing to push a backup to an ambiguous ref"
  exit 3
fi

git add -A 2>/dev/null

# --- Safety gate: never push sensitive paths ---
DANGER=$(git diff --cached --name-only | grep -iE \
  '^\.env|auth\.json|google_.*\.json|^google/|state\.db|kanban\.db|channel_directory|^whatsapp/|^pairing/|^sessions/|^logs/|^personal-context/|token\.json|client_secret' \
  || true)
if [ -n "$DANGER" ]; then
  echo "⚠️ hermes-sync ABORTED — sensitive files staged, not pushed:"
  echo "$DANGER"
  git reset -q
  exit 2
fi

# --- Nothing changed ---
if git diff --cached --quiet; then
  [ "$QUIET" -eq 1 ] || echo "Nothing to sync — working tree clean."
  exit 0
fi

STAT=$(git diff --cached --stat | tail -1)
[ -n "$MSG" ] || MSG="auto-sync: $(date '+%Y-%m-%d %H:%M %Z')"
[ "$QUIET" -eq 1 ] || { echo "=== changes to sync ==="; git diff --cached --stat | tail -20; }

if ! git commit -q -m "$MSG"; then echo "⚠️ hermes-sync: commit failed"; exit 1; fi

if git push -q origin "$BRANCH"; then
  echo "✅ Hermes config synced to GitHub — $(git rev-parse --short HEAD)"
  echo "   $STAT"
else
  echo "⚠️ hermes-sync: push FAILED (commit $(git rev-parse --short HEAD) is local only)"
  exit 1
fi
