#!/usr/bin/env bash
#
# sync_skills.sh — Sync skills between marketplace GitHub repo and local Hermes skills dir
#
# Usage:
#   ./sync_skills.sh push    — Push local skills to marketplace repo + commit
#   ./sync_skills.sh pull    — Pull marketplace repo skills to local Hermes
#   ./sync_skills.sh check   — Check if local and remote are in sync (exit 0=in sync, 1=drift)
#   ./sync_skills.sh status  — Show diff summary between local and marketplace
#
# Config (override via env vars):
#   MARKETPLACE_REPO  — GitHub repo (default: whichguy/hermes-skills-marketplace)
#   MARKETPLACE_DIR   — Local clone path (default: /opt/data/hermes-skills-marketplace)
#   HERMES_SKILLS_DIR — Local Hermes skills (default: /opt/data/skills)
#

set -euo pipefail

MARKETPLACE_REPO="${MARKETPLACE_REPO:-whichguy/hermes-skills-marketplace}"
MARKETPLACE_DIR="${MARKETPLACE_DIR:-/opt/data/hermes-skills-marketplace}"
HERMES_SKILLS_DIR="${HERMES_SKILLS_DIR:-/opt/data/skills}"

# Skills to sync (custom skills only, not bundled with Hermes)
SYNC_SKILLS=(
  apple-macos-apps
  bfl-api
  computer-use
  cron-llm-review-house-style
  email-utils
  flux-best-practices
  hardware-repair-research
  hermes-config-git-backup
  hermes-ecosystem-research
  hermes-email-gateway
  hermes-whatsapp-gateway
  home-assistant-smart-home-control
  html-artifact
  live-event-status-updates
  messaging-platform-formatting
  personal-context-integration
  scheduled-research-briefs
  script-first-cron-design
  self-healing-cron-watchdogs
  simplify-code
  skill-marketplace
  skill-testing-harness
  usaw-meet-card-parser
  usaw-to-schedule
  versioning-hermes-home
  worldcup-update-template
)

# Category mapping for marketplace directory structure
declare -A CATEGORY_MAP=(
  [apple-macos-apps]=productivity
  [bfl-api]=creative
  [computer-use]=software-development
  [cron-llm-review-house-style]=devops
  [email-utils]=productivity
  [flux-best-practices]=creative
  [hardware-repair-research]=productivity
  [hermes-config-git-backup]=devops
  [hermes-ecosystem-research]=software-development
  [hermes-email-gateway]=productivity
  [hermes-whatsapp-gateway]=productivity
  [home-assistant-smart-home-control]=productivity
  [html-artifact]=creative
  [live-event-status-updates]=research
  [messaging-platform-formatting]=productivity
  [personal-context-integration]=productivity
  [scheduled-research-briefs]=research
  [script-first-cron-design]=devops
  [self-healing-cron-watchdogs]=devops
  [simplify-code]=software-development
  [skill-marketplace]=software-development
  [skill-testing-harness]=software-development
  [usaw-meet-card-parser]=productivity
  [usaw-to-schedule]=productivity
  [versioning-hermes-home]=devops
  [worldcup-update-template]=productivity
)

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

ensure_repo() {
  if [ ! -d "$MARKETPLACE_DIR/.git" ]; then
    log "Cloning marketplace repo..."
    git clone "https://github.com/${MARKETPLACE_REPO}.git" "$MARKETPLACE_DIR" 2>/dev/null || {
      log "ERROR: Could not clone $MARKETPLACE_REPO"
      exit 1
    }
  fi
}

find_local_skill() {
  local skill_name="$1"
  # Search in Hermes skills dir, skip .archive
  find "$HERMES_SKILLS_DIR" -name "SKILL.md" -not -path "*/.archive/*" 2>/dev/null | while read -r f; do
    local dir
    dir="$(dirname "$f")"
    # Check if the directory name or frontmatter name matches
    if [ "$(basename "$dir")" = "$skill_name" ]; then
      echo "$dir"
      return
    fi
    # Check frontmatter name
    local fm_name
    fm_name=$(grep -m1 "^name:" "$f" | sed 's/name: *//' | tr -d '"'"'" 2>/dev/null || true)
    if [ "$fm_name" = "$skill_name" ]; then
      echo "$dir"
      return
    fi
  done
}

cmd_push() {
  ensure_repo
  cd "$MARKETPLACE_DIR"
  git pull --rebase --quiet 2>/dev/null || true
  
  local changed=0
  for skill in "${SYNC_SKILLS[@]}"; do
    local category="${CATEGORY_MAP[$skill]}"
    local local_path
    local_path=$(find_local_skill "$skill")
    local target="skills/${category}/${skill}"
    
    if [ -z "$local_path" ]; then
      log "SKIP: $skill not found locally"
      continue
    fi
    
    # Remove old and copy new
    rm -rf "$target"
    mkdir -p "$(dirname "$target")"
    cp -r "$local_path" "$target"
    
    # Check if anything changed
    if ! git diff --quiet -- "$target" 2>/dev/null; then
      git add "$target"
      changed=$((changed + 1))
      log "UPDATED: $skill → $target"
    fi
  done
  
  # Update index.json
  python3 scripts/generate_index.py --quiet 2>/dev/null || true
  if ! git diff --quiet -- ".well-known/skills/index.json" 2>/dev/null; then
    git add ".well-known/skills/index.json"
    changed=$((changed + 1))
    log "UPDATED: .well-known/skills/index.json"
  fi
  
  if [ "$changed" -gt 0 ]; then
    git commit -m "sync: ${changed} skill(s) updated from local ($(date -u +%Y-%m-%d))"
    git push origin "$(git branch --show-current)" 2>/dev/null || {
      log "WARNING: Could not push (may need auth)"
    }
    log "✅ Pushed $changed change(s) to $MARKETPLACE_REPO"
  else
    log "✅ Everything up to date — no changes to push"
  fi
}

cmd_pull() {
  ensure_repo
  cd "$MARKETPLACE_DIR"
  git pull --rebase --quiet 2>/dev/null || {
    log "WARNING: git pull failed — trying fetch + reset"
    git fetch --quiet
    git reset --hard origin/$(git branch --show-current) --quiet
  }
  
  local updated=0
  for skill in "${SYNC_SKILLS[@]}"; do
    local category="${CATEGORY_MAP[$skill]}"
    local source="skills/${category}/${skill}"
    local target
    target=$(find_local_skill "$skill")
    
    if [ ! -d "$source" ]; then
      log "SKIP: $skill not in marketplace"
      continue
    fi
    
    if [ -z "$target" ]; then
      # Install to local skills dir under category
      target="${HERMES_SKILLS_DIR}/${category}/${skill}"
      mkdir -p "$(dirname "$target")"
      cp -r "$source" "$target"
      updated=$((updated + 1))
      log "INSTALLED: $skill → $target"
    else
      # Compare and update if different
      if ! diff -rq "$source" "$target" >/dev/null 2>&1; then
        rm -rf "$target"
        cp -r "$source" "$target"
        updated=$((updated + 1))
        log "UPDATED: $skill → $target"
      fi
    fi
  done
  
  if [ "$updated" -gt 0 ]; then
    log "✅ Pulled $updated skill(s) from marketplace to local"
  else
    log "✅ All skills up to date"
  fi
}

cmd_check() {
  ensure_repo
  cd "$MARKETPLACE_DIR"
  git fetch --quiet 2>/dev/null || true
  
  local local_sha remote_sha
  local_sha=$(git rev-parse HEAD)
  remote_sha=$(git rev-parse origin/$(git branch --show-current) 2>/dev/null || echo "")
  
  if [ "$local_sha" = "$remote_sha" ]; then
    log "IN SYNC: local and remote match ($local_sha)"
    exit 0
  else
    log "DRIFT: local=$local_sha remote=$remote_sha"
    git log --oneline "${local_sha}..${remote_sha}" 2>/dev/null | head -5
    exit 1
  fi
}

cmd_status() {
  ensure_repo
  cd "$MARKETPLACE_DIR"
  git fetch --quiet 2>/dev/null || true
  
  local local_sha remote_sha
  local_sha=$(git rev-parse --short HEAD)
  remote_sha=$(git rev-parse --short origin/$(git branch --show-current) 2>/dev/null || echo "unknown")
  
  echo "Marketplace: $MARKETPLACE_REPO"
  echo "Local SHA:   $local_sha"
  echo "Remote SHA:  $remote_sha"
  echo ""
  
  if [ "$local_sha" = "$remote_sha" ]; then
    echo "Status: IN SYNC ✅"
  else
    echo "Status: DRIFT DETECTED ⚠️"
    echo ""
    echo "Commits behind remote:"
    git log --oneline "HEAD..origin/$(git branch --show-current)" 2>/dev/null | head -10
    echo ""
    echo "Commits ahead of remote:"
    git log --oneline "origin/$(git branch --show-current)..HEAD" 2>/dev/null | head -10
  fi
  
  echo ""
  echo "Skills tracked: ${#SYNC_SKILLS[@]}"
  
  # Count actual skill dirs
  local count
  count=$(find skills/ -name "SKILL.md" 2>/dev/null | wc -l)
  echo "Skills in marketplace: $count"
}

case "${1:-}" in
  push)   cmd_push ;;
  pull)   cmd_pull ;;
  check)  cmd_check ;;
  status) cmd_status ;;
  *)
    echo "Usage: $0 {push|pull|check|status}"
    echo ""
    echo "  push   — Push local skills to marketplace repo + commit"
    echo "  pull   — Pull marketplace repo skills to local Hermes"
    echo "  check  — Check if local and remote are in sync"
    echo "  status — Show sync status summary"
    exit 1
    ;;
esac