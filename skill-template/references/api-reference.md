# API Reference

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/search` | GET | Search for facilities |
| `/v1/details/{id}` | GET | Get facility details |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SKILL_API_KEY` | Yes | — | API authentication key |
| `SKILL_API_ENDPOINT` | No | `https://api.example.com/v1/search` | API base URL |
| `SKILL_SEARCH_RADIUS_KM` | No | `10` | Default search radius |
| `SKILL_TIMEZONE` | No | `UTC` | Timezone for results |
| `SKILL_OUTPUT_FORMAT` | No | `markdown` | Output format |

## Rate Limits

- 1000 requests/day on free tier
- 100 requests/minute burst limit
- 429 response → exponential backoff

## Error Codes

| Code | Meaning | Action |
|------|---------|--------|
| 401 | Invalid API key | Check SKILL_API_KEY in .env |
| 429 | Rate limited | Back off and retry |
| 500 | Server error | Retry with delay |