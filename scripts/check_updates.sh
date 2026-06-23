#!/usr/bin/env bash
#
# check_updates.sh — Check if marketplace repo has updates that local doesn't
#
# Exits 0 if up-to-date (silent), 1 if updates available (prints summary)
# Designed for cron: silent when nothing to report, verbose when updates exist
#

set -euo pipefail

MARKETPLACE_DIR="${MARKETPLACE_DIR:-/opt/data/hermes-skills-marketplace}"

# Ensure repo exists and fetch latest
if [ ! -d "$MARKETPLACE_DIR/.git" ]; then
  echo "Marketplace repo not initialized at $MARKETPLACE_DIR"
  echo "Run: $MARKETPLACE_DIR/scripts/sync_skills.sh pull"
  exit 1
fi

cd "$MARKETPLACE_DIR"
git fetch --quiet 2>/dev/null || true

LOCAL_SHA=$(git rev-parse --short HEAD)
REMOTE_SHA=$(git rev-parse --short "origin/$(git branch --show-current)" 2>/dev/null || echo "unknown")
BRANCH=$(git branch --show-current)

if [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then
  # In sync — exit silently
  exit 0
fi

# Updates available — print what's new
NEW_COMMITS=$(git rev-list --count "HEAD..origin/$BRANCH" 2>/dev/null || echo "?")

echo "📦 Marketplace updates available: $NEW_COMMITS new commit(s)"
echo "   Local:  $LOCAL_SHA"
echo "   Remote: $REMOTE_SHA"
echo ""
echo "Recent changes:"
git log --oneline "HEAD..origin/$BRANCH" 2>/dev/null | head -5
echo ""
echo "To sync: $MARKETPLACE_DIR/scripts/sync_skills.sh pull"
exit 1