# X (Twitter) MCP Server

X provides an **official MCP server** at `https://api.x.com/mcp`. It's maintained
by the X developer platform team, not a community project.

## Credential Requirements

The X MCP server requires **X Developer Platform** credentials — NOT xAI API keys.
Despite shared ownership, these are separate systems:

| System | Key prefix | Portal | Purpose |
|--------|-----------|--------|---------|
| xAI (Grok) | `xai-` | [console.x.ai](https://console.x.ai) | LLM API access |
| X Developer | varies | [developer.x.com](https://developer.x.com) | X/Twitter API, MCP server |

An `xai-` key will be rejected by the X MCP server.

## Getting Credentials

1. Go to [developer.x.com/en/portal/dashboard](https://developer.x.com/en/portal/dashboard)
2. Create a Project and App (or use an existing one)
3. Under "Keys and tokens", generate either:
   - **Bearer Token** — read-only access (search, fetch posts, user info)
   - **OAuth 2.0 Client ID + Client Secret** — full access (post, DM, etc.)

## Configuring in Hermes

### HTTP Transport (recommended for the official server)

```yaml
mcp_servers:
  x:
    url: "https://api.x.com/mcp"
    headers:
      Authorization: "Bearer AAAAAAAAAAAAAAAAAAAA..."
    timeout: 180
    connect_timeout: 60
```

### Alternative: xurl CLI (already available)

Hermes already has the `xurl` skill for X/Twitter access via CLI. This is a
different approach — CLI-based rather than MCP tools — but covers similar
ground (post, search, DM, media, v2 API). The xurl CLI also needs X Developer
credentials, not xAI keys.

## Tools Provided by the Official MCP Server

The official X MCP server exposes tools for:
- Searching posts and users
- Fetching timelines and user profiles
- Posting and managing tweets
- Direct messages
- Media uploads

Exact tool names follow the `mcp_x_*` naming convention after registration.

## Pitfalls

- **xAI key ≠ X Developer key** — the most common confusion. xAI keys start
  with `xai-` and only work with the Grok API at `api.x.ai`. X Developer keys
  are separate and managed at `developer.x.com`.
- **Bearer token is read-only** — if you need to post or send DMs, you need
  OAuth 2.0 credentials, not just a Bearer token.
- **Free tier has rate limits** — X API v2 free tier is limited. Check the
  [X API documentation](https://developer.x.com/en/docs/x-api) for current
  limits.
