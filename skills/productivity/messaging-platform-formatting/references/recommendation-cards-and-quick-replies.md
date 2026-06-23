# Recommendation cards and quick replies for Telegram

Session learning: the user found dense recommendation sections hard to parse, especially around skills, memories, cron changes, and relationship-graph approvals. The user also felt overloaded by many separate questions. Prefer a single recommendation with fast reply options.

## Default shape

```markdown
━━━━━━━━━━━━━━━━━━
🟢 **Recommendation**
━━━━━━━━━━━━━━━━━━

**Do:** <recommended action>
**Risk:** 🟢 Low | 🟡 Medium | 🔴 High | ⚪ Info
**Why:** <one short reason>

## Quick reply

**A** — Approve recommended path
**B** — Show details first
**C** — Stop / change direction
```

## Risk emoji legend

- 🟢 Low: local, reversible, privacy-safe, no external side effects.
- 🟡 Medium: affects memory, routing, recurring behavior, or review state.
- 🔴 High: external messages, credentials, destructive/irreversible changes, sensitive automation, disclosure permissions.
- ⚪ Info: no user action required.

## Guidance

- Put the recommendation first, then evidence.
- Use one approval prompt, not a checklist of questions.
- If multiple actions are needed, group them under numbered options (`1`, `2`, `3`) or letters (`A`, `B`, `C`).
- When approval is required, make the default clear: `A — approve recommended path`.
- For privacy-sensitive workflows, explicitly say what is **not** authorized: no memory write, no cron change, no disclosure, no external action.
- Keep detailed logs/paths in code blocks below the decision card, not before it.
