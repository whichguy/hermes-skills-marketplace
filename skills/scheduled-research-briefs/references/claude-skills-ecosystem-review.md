# Claude/Claude Code ecosystem review pattern

Session-derived reference from a Hermes optimization cron-job refinement.

## User signal

The user said the recurring report had too much text and asked for a more blog-like, informational format with explanation, insights, recommendations, pros/cons, and so forth. Treat this as a first-class skill signal: update the scheduled job prompt, not just the final answer.

## Prompt shape that worked

A useful cron prompt for ecosystem research included:

- blog-like executive brief style
- target length 600–900 words
- no raw research dump
- required sections: focus, insights, recommendations, pros/cons, notable workflows, bottom line, suggested action, curated sources
- adopt/adapt/reject/monitor recommendation labels
- explicit report-only rule
- cite only 3–6 high-quality sources

## Tool fallback that worked

The cron run initially reported weak live web/GitHub access. The fix was to update the cron job's enabled toolsets and prompt so it could use terminal/curl/Python against public sources when ordinary web tools were unavailable.

Useful public checks for GitHub ecosystem reviews:

```python
import urllib.request, urllib.parse, json
q = 'claude code skills'
url = 'https://api.github.com/search/repositories?' + urllib.parse.urlencode({
    'q': q,
    'sort': 'updated',
    'order': 'desc',
    'per_page': 5,
})
req = urllib.request.Request(url, headers={
    'Accept': 'application/vnd.github+json',
    'User-Agent': 'hermes-agent-review',
})
with urllib.request.urlopen(req, timeout=20) as r:
    data = json.load(r)
for item in data.get('items', []):
    print(item['full_name'], item['stargazers_count'], item['updated_at'], item['html_url'])
```

For candidate repos, also fetch `/repos/{owner}/{repo}` and `/repos/{owner}/{repo}/readme` to summarize:

- stars/forks
- updated/pushed timestamps
- license
- description
- README headings
- install method
- permissions, hooks, MCP servers, credentials, external access

## Recommendation examples from the session

- **Adopt as research source:** `davepoon/buildwithclaude` — broad discovery hub for Claude skills, agents, commands, hooks, plugins, and marketplaces. Useful to monitor; do not auto-install.
- **Adapt selectively:** enterprise/playbook-style repos with specs, hooks, agents, and templates. Extract patterns; reimplement in Hermes with approval gates.
- **Monitor:** MCP-heavy or multi-agent operating-system packs. High leverage but broad permission surface.
- **Reject for now:** fully autonomous “work continuously through a backlog” skill packs when they conflict with the user's preference for explicit approval before broad automation or external actions.

## Broad approval lesson

When the user later said “I approve all of the next actions,” the safe interpretation was to perform the concrete low-risk next action from the report: run a one-time web-capable review and update the cron job's research capability. It was not approval to install public Claude skills, add MCP servers, grant credentials, or enable autonomous workflows.

## Durable output style preference

For scheduled research/optimization reports, prefer:

- concise Telegram-friendly headings and bullets
- synthesis over source volume
- pros/cons for the main idea
- few curated sources, not a bibliography
- one concrete next action

Avoid:

- long raw excerpts
- giant source lists
- tables in Telegram
- treating low-star newly updated repos as proven quality
- installing anything just to inspect it
