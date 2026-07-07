#!/usr/bin/env python3
"""Shared presentation helpers for Hermes cron job output.

Goal: one consistent, pretty, Telegram-friendly house style across every
script-only cron job. Import these helpers instead of hand-formatting each
script so the look can be tuned in a single place.

Deploy: copy into the deployment scripts dir (e.g. ${HERMES_HOME}/scripts/) so
sibling cron scripts can ``import cron_style as cs``.

Design rules:
- Friendly local time (Pacific), never raw UTC/ISO in user-facing text.
- Tasteful emojis: one per heading + small status icons. Do not overdo it.
- Hyperlink key references with descriptive Markdown link text so the user
  can click back to the source item: ``[Open in Gmail](url)``.
- No tables (Telegram has no table syntax). Use headings + bullets.
- Keep it scannable: short headings, bold labels, compact bullets.

All helpers return strings so callers assemble a message and ``print`` it once.
``render(blocks)`` joins a list of pieces.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# Risk / status icon vocabulary — keep consistent across all jobs.
ICON_OK = "🟢"
ICON_WARN = "🟡"
ICON_HIGH = "🔴"
ICON_INFO = "⚪"

DIVIDER = "━━━━━━━━━━━━━━━"


def _parse(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def local_time(value, with_date: bool = True) -> str:
    """Friendly Pacific label, e.g. 'Sat, Jun 13 at 3:00 PM PDT'."""
    dt = _parse(value)
    if not dt:
        return str(value) if value else "unknown time"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(LOCAL_TZ)
    if with_date:
        return local.strftime("%a, %b %-d at %-I:%M %p %Z")
    return local.strftime("%-I:%M %p %Z")


def now_label() -> str:
    return datetime.now(timezone.utc).astimezone(LOCAL_TZ).strftime(
        "%A, %B %-d · %-I:%M %p %Z"
    )


def link(text: str, url) -> str:
    """Markdown hyperlink with descriptive label; falls back to plain text."""
    if url:
        return f"[{text}]({url})"
    return text


def header(emoji: str, title: str, subtitle=None) -> str:
    if subtitle:
        return "\n".join([f"{emoji} *{title}*", f"_{subtitle}_", DIVIDER])
    return "\n".join([f"{emoji} *{title}*", DIVIDER])


def section(emoji: str, title: str) -> str:
    return f"\n{emoji} *{title}*"


def bullet(text: str, icon=None) -> str:
    return f"{icon + ' ' if icon else ''}• {text}"


def kv(label: str, value: str, icon=None) -> str:
    prefix = f"{icon} " if icon else ""
    return f"{prefix}• *{label}:* {value}"


def footer(text: str) -> str:
    return f"\n{text}"


def render(blocks) -> str:
    return "\n".join(b for b in blocks if b is not None)
