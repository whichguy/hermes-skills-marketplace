# Daily update hyperlink pattern

When a scheduled daily/update job delivers to Telegram or another chat surface, raw URLs are usually less useful than linked action text. The preferred shape is standard Markdown:

```markdown
Source: [ESPN scoreboard](https://www.espn.com/soccer/scoreboard/_/league/fifa.world) · [standings](https://www.espn.com/soccer/standings/_/league/fifa.world)
Open: [Google Calendar event](https://calendar.google.com/...)
Open: [Gmail Inbox search](https://mail.google.com/mail/u/0/#search/...)
```

## Rules

- Prefer the human-usable interface URL over the API URL used by the precheck.
- Link descriptive text, not the bare URL.
- Keep the label short and action-oriented: `Open`, `Source`, `Docs`, `Gmail Inbox search`, `Google Calendar event`, `Drive doc`.
- In LLM-driven cron jobs, add this to the prompt as a hard formatting rule.
- In `no_agent: true` script-only jobs, patch the script directly because stdout is delivered verbatim.
- If no interface URL is available, omit the link rather than inventing one.

## Common interface URL mappings

- Google Calendar event: `event.htmlLink` from Calendar API output.
- Google Drive file: `webViewLink` from Drive API output.
- Gmail search fallback: `https://mail.google.com/mail/u/0/#search/` plus URL-encoded Gmail query.
- Public web data source: canonical web page for the source, not the JSON/API endpoint.
