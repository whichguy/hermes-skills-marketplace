#!/usr/bin/env python3
"""
WhatsApp Bridge Health Watchdog
================================
Cron schedule: every 15 minutes
Delivery: Slack (origin)
no_agent: true (script-only, zero tokens on healthy path)

Checks WhatsApp bridge health via two signals:
1. GET http://localhost:3000/health — bridge HTTP endpoint
2. Tail /opt/data/whatsapp/bridge.log for "Logged out" / "device_removed"

Silent when bridge is connected and healthy.
Alerts when:
  - Health endpoint returns disconnected / unreachable
  - Bridge log shows "Logged out" (session invalidated, needs re-pair)
  - Bridge log shows "device_removed" (WhatsApp server killed the session)

State: /opt/data/cron/state/wa_bridge_health.json
  - last_alert_type: dedup so we don't spam the same alert every 15 min
  - last_alert_at: epoch timestamp
  - cooldown_seconds: 3600 (1h) — don't re-alert same type within 1h

Wiki: [[hermes-whatsapp-gateway]]
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HEALTH_URL = "http://localhost:3000/health"
BRIDGE_LOG = "/opt/data/whatsapp/bridge.log"
STATE_FILE = "/opt/data/cron/state/wa_bridge_health.json"
COOLDOWN_SECONDS = 3600  # 1 hour between same-type alerts
ALERT_TYPES = {
    "logged_out": "❌ WhatsApp bridge session is **logged out** — needs re-pairing",
    "device_removed": "❌ WhatsApp server **removed the linked device** — needs re-pairing",
    "bridge_down": "❌ WhatsApp bridge is **not responding** on port 3000",
    "disconnected": "⚠️ WhatsApp bridge reports **disconnected** status",
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_alert_type": None, "last_alert_at": 0, "consecutive_failures": 0}

def save_state(state):
    Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def should_alert(state, alert_type):
    """Returns True if we should send this alert (cooldown check)."""
    if state.get("last_alert_type") != alert_type:
        return True
    elapsed = time.time() - state.get("last_alert_at", 0)
    return elapsed > COOLDOWN_SECONDS

def check_health_endpoint():
    """Returns (status_str, ok_bool). status_str is the raw health response."""
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "5", HEALTH_URL],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip()
        if not output:
            return None, False
        try:
            data = json.loads(output)
            return data.get("status", "unknown"), data.get("status") == "connected"
        except json.JSONDecodeError:
            return output, False
    except (subprocess.TimeoutExpired, Exception):
        return None, False

def check_bridge_log():
    """Returns (alert_type_or_None, detail_str).
    Scans the last 50 lines of bridge.log for death signals."""
    try:
        result = subprocess.run(
            ["tail", "-50", BRIDGE_LOG],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    except Exception:
        return None, ""

    for line in lines:
        if "device_removed" in line:
            return "device_removed", line[:200]
        if "Logged out" in line:
            return "logged_out", line[:200]

    return None, ""

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    state = load_state()

    # Check 1: Bridge log for death signals (most specific)
    log_alert, log_detail = check_bridge_log()

    # Check 2: Health endpoint
    health_status, health_ok = check_health_endpoint()

    # Determine alert type (priority: device_removed > logged_out > bridge_down > disconnected)
    alert_type = None
    if log_alert:
        alert_type = log_alert
    elif not health_ok:
        if health_status is None:
            alert_type = "bridge_down"
        elif health_status == "disconnected":
            alert_type = "disconnected"
        # "unknown" or other — only alert if also failing repeatedly
        elif health_status != "connected":
            alert_type = "bridge_down"

    if alert_type is None:
        # Healthy — reset state
        if state.get("consecutive_failures", 0) > 0 or state.get("last_alert_type"):
            state["consecutive_failures"] = 0
            state["last_alert_type"] = None
            save_state(state)
        # Silent — empty stdout
        return

    # We have an alert — check cooldown
    if not should_alert(state, alert_type):
        # Still in cooldown, stay silent
        return

    # Build alert message
    msg_parts = [
        ALERT_TYPES.get(alert_type, f"⚠️ WhatsApp bridge issue: {alert_type}"),
        "",
    ]

    if health_status is not None:
        msg_parts.append(f"**Bridge health:** `{health_status}`")
    else:
        msg_parts.append("**Bridge health:** _not responding_")

    if log_detail:
        msg_parts.append(f"**Log signal:** `{log_detail}`")

    msg_parts.append("")
    msg_parts.append("**Re-pair from Mac host:**")
    msg_parts.append("```bash")
    msg_parts.append("# 1. Kill stuck bridge + clear dead session")
    msg_parts.append('docker exec -it hermes bash -c \'pkill -f "node.*bridge.js" || true\'')
    msg_parts.append("docker exec -it hermes rm -rf /opt/data/whatsapp/session/")
    msg_parts.append("")
    msg_parts.append("# 2. Pair using gateway's own bridge (prints QR to terminal)")
    msg_parts.append("docker exec -it hermes /opt/hermes/bin/hermes whatsapp")
    msg_parts.append("")
    msg_parts.append("# 3. On Jeeves phone: WhatsApp → Settings → Linked Devices → Link a Device → scan QR")
    msg_parts.append("")
    msg_parts.append("# 4. Restart gateway + verify")
    msg_parts.append("docker exec -it hermes /opt/hermes/bin/hermes gateway restart")
    msg_parts.append("docker exec -it hermes curl -s http://localhost:3000/health")
    msg_parts.append("```")
    msg_parts.append("")
    msg_parts.append(f"_Cooldown: next alert in {COOLDOWN_SECONDS // 60}m unless type changes_")

    # Update state
    state["last_alert_type"] = alert_type
    state["last_alert_at"] = time.time()
    state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
    save_state(state)

    # Print alert (delivered verbatim by cron scheduler)
    print("\n".join(msg_parts))

if __name__ == "__main__":
    main()