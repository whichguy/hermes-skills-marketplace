#!/usr/bin/env bash
# setup.sh — one-command setup for a fresh clone of a Hermes deployment.
#
# Usage:
#   git clone <repo-url> ~/.hermes && cd ~/.hermes && ./setup.sh
#
# What it does:
#   1. Verifies prerequisites (Docker, npm)
#   2. Creates .env from template if missing
#   3. Installs generated dependencies (npm install for WhatsApp bridge, etc.)
#   4. Sets file permissions on sensitive files
#   5. Prints next-step instructions
#
# Idempotent — safe to re-run on an existing deployment.
# Adapt the dependency sections to match what your repo excludes from git.

set -euo pipefail

HERMES_HOME="$(cd "$(dirname "$0")" && pwd)"
echo "🚀 Hermes Agent setup — HERMES_HOME=$HERMES_HOME"
echo ""

# ---- 1. Prerequisites ----
echo "=== Checking prerequisites ==="
MISSING=0

if command -v docker &>/dev/null; then
  echo "  ✅ Docker: $(docker --version)"
else
  echo "  ❌ Docker not found — install Docker or OrbStack first"
  MISSING=1
fi

if command -v npm &>/dev/null; then
  echo "  ✅ npm: $(npm --version)"
else
  echo "  ⚠️  npm not found — WhatsApp bridge won't work without it"
  echo "     Install Node.js 18+ from https://nodejs.org/"
  MISSING=1
fi

if [ "$MISSING" -ne 0 ]; then
  echo ""
  echo "❌ Prerequisites missing. Fix the above and re-run."
  exit 1
fi
echo ""

# ---- 2. .env file ----
echo "=== Environment file (.env) ==="
if [ -f "$HERMES_HOME/.env" ]; then
  echo "  ✅ .env exists — leaving as-is"
else
  echo "  ⚠️  .env not found — creating from template"
  cat > "$HERMES_HOME/.env" << 'ENVEOF'
# Hermes Agent — Environment Variables
# ============================================================
# Add your API keys here. At minimum, one LLM provider key.
# This file is gitignored and NEVER committed.

# --- LLM Providers (add at least one) ---
# OPENROUTER_API_KEY=*** ANTHROPIC_API_KEY=*** GOOGLE_API_KEY=*** DEEPSEEK_API_KEY=*** XAI_API_KEY=*** --- Optional integrations ---
# EXA_API_KEY=*** search)
# GROQ_API_KEY=*** Whisper STT)

# --- WhatsApp bridge (if using WhatsApp) ---
# WHITELIST_USERS=       (comma-separated phone numbers)
ENVEOF
  chmod 600 "$HERMES_HOME/.env"
  echo "  ✅ Created .env (chmod 600) — EDIT IT to add your API keys"
fi
echo ""

# ---- 3. Generated dependencies ----
# Add a section per dependency dir that's excluded from git.
echo "=== Generated dependencies ==="

# WhatsApp bridge
BRIDGE_DIR="$HERMES_HOME/scripts/whatsapp-bridge"
if [ -f "$BRIDGE_DIR/package.json" ]; then
  if [ -d "$BRIDGE_DIR/node_modules" ]; then
    echo "  ✅ WhatsApp bridge: node_modules exists — skipping"
  else
    echo "  📦 WhatsApp bridge: installing npm dependencies..."
    (cd "$BRIDGE_DIR" && npm install --production 2>&1 | tail -3)
    echo "  ✅ WhatsApp bridge: dependencies installed"
  fi
else
  echo "  ⚠️  No WhatsApp bridge at $BRIDGE_DIR — skipping"
fi

# Add more dependency sections here as needed:
# if [ -f "$HERMES_HOME/some-other/package.json" ]; then ...
# if [ -d "$HERMES_HOME/vendor" ] && [ ! -d "$HERMES_HOME/vendor/composer" ]; then ...
echo ""

# ---- 4. File permissions ----
echo "=== Securing sensitive files ==="
for f in .env auth.json google_client_secret.json google_token.json channel_directory.json; do
  if [ -f "$HERMES_HOME/$f" ]; then
    chmod 600 "$HERMES_HOME/$f" 2>/dev/null || true
    echo "  ✅ $f → 600"
  fi
done
echo ""

# ---- 5. Next steps ----
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env and add your API keys:"
echo "     $HERMES_HOME/.env"
echo ""
echo "  2. Start the stack:"
echo "     cd $HERMES_HOME && docker compose up -d"
echo ""
echo "  3. Watch startup logs:"
echo "     docker compose logs -f hermes"
echo ""
echo "  4. Pair messaging platforms (Telegram, WhatsApp, Slack, etc.):"
echo "     hermes gateway setup"
echo ""
echo "  5. Verify health:"
echo "     hermes doctor"
echo ""