# Kanban Dashboard — Slack Block Kit Visual Design Recommendations

> DeepSeek Pro review, 2026-06-27. 14 recommendations from a Slack Block Kit visual design expert.

## Summary of Applied Changes

10 of 14 recommendations were applied to `kanban-dashboard.py` v2:

| # | Recommendation | Priority | Applied |
|---|---|---|---|
| 1 | Replace ▓░░ progress bar with segmented emoji squares | HIGH | ✅ |
| 2 | Add color-coded status accessories with emoji badges | HIGH | ✅ (emoji + text chips) |
| 3 | Single top-level progress card — remove duplicate sections | HIGH | ✅ |
| 4 | Single-column layout instead of two-column `fields` | HIGH | ✅ |
| 5 | Shape-consistent emoji set + 🚫 for blocked | MEDIUM | ✅ |
| 6 | Strategic `context` blocks for metadata footers | MEDIUM | ✅ |
| 7 | `rich_text` blocks for goal and summary | MEDIUM | Deferred |
| 8 | Per-stage `overflow` menus for details | MEDIUM | Deferred (needs interaction URL) |
| 9 | Hero completion section with primary button | MEDIUM | ✅ |
| 10 | Reduce dividers to major section breaks only | MEDIUM | ✅ |
| 11 | Shorten task labels + emoji for skill categories | LOW | ✅ |
| 12 | Fix `plain_text` header emoji rendering (`emoji: True`) | LOW | ✅ |
| 13 | Compact summary table for completed work | LOW | Deferred (inline summaries used instead) |
| 14 | `image` block accessories for pipeline connector | LOW | Deferred (needs image hosting) |

## Key Design Principles

1. **Single source of truth** — each task appears once, not duplicated in Completed + Pending sections
2. **Mobile-first** — single-column layout reads naturally on both desktop and mobile
3. **Color carries meaning** — green=done, blue=running, yellow=ready, red=blocked
4. **Context blocks for metadata** — smaller gray text separates metadata from content
5. **Minimal dividers** — only at major section breaks; headers already provide separation
6. **Shape consistency** — all squares or all circles, not mixed shapes

## Deferred Items

- **`rich_text` blocks** — Slack's newer format, more reliable than inline mrkdwn. Worth migrating goal/summary blocks when time permits.
- **Overflow menus** — require Slack interaction URL configured. Adds interactivity but needs setup.
- **Image accessories** — need a reliable image host for pipeline connector arrows. Nice polish, not essential.
