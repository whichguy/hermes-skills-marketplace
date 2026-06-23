---
name: bfl-api
description: BFL (Black Forest Labs) API integration guide for FLUX models. Covers
  endpoints, pricing, polling pattern, webhooks, image input for editing, and rate
  limits for FLUX.2 and FLUX.1 families.
metadata:
  author: Black Forest Labs
  version: 1.0.0
  tags:
  - flux
  - bfl
  - api
  - image-generation
  - endpoints
  hermes:
    config:
    - key: bfl-api.enabled
      description: Enable bfl-api skill behavior
      default: true
      prompt: Enable bfl-api skill?
    tags:
    - bfl
    category: creative
platforms:
- linux
- macos
- windows
version: 1.0.0
author: Fortified Strength
license: MIT
---
---
# BFL API Integration Guide

## Critical Notes
- **Image URLs expire in 10 minutes** — download immediately after generation
- **API key required** — set `BFL_API_KEY` environment variable
- Authentication header: `x-key: YOUR_API_KEY`

## Base Endpoints
| Region | Endpoint | Use Case |
|---|---|---|
| Global | `https://api.bfl.ai` | Default, automatic failover |
| EU | `https://api.eu.bfl.ai` | GDPR compliance |
| US | `https://api.us.bfl.ai` | US data residency |

## Model Endpoints & Pricing
> 1 credit = $0.01 USD | FLUX.2 uses megapixel-based pricing

### FLUX.2 (Megapixel-Based)
| Model | Path | 1MP T2I | 1MP I2I | Best For |
|---|---|---|---|---|
| FLUX.2 [klein] 4B | `/v1/flux-2-klein-4b` | $0.014 | $0.015 | Real-time, high volume |
| FLUX.2 [klein] 9B | `/v1/flux-2-klein-9b` | $0.015 | $0.017 | Balanced quality/speed |
| FLUX.2 [pro] | `/v1/flux-2-pro` | $0.030 | $0.045 | Production, fast turnaround |
| FLUX.2 [max] | `/v1/flux-2-max` | $0.070 | $0.100 | Maximum quality |
| FLUX.2 [flex] | `/v1/flux-2-flex` | $0.050 | $0.100 | Typography, adjustable controls |
| FLUX.2 [dev] | — | Free | Free | Local dev (non-commercial) |

### FLUX.1 (Flat Per-Image)
| Model | Path | Price | Best For |
|---|---|---|---|
| FLUX.1 Kontext [pro] | `/v1/flux-kontext` | $0.04 | Image editing with context |
| FLUX.1 Kontext [max] | `/v1/flux-kontext-max` | $0.08 | Max quality editing |
| FLUX1.1 [pro] | `/v1/flux-pro-1.1` | $0.04 | Standard T2I, fast & reliable |
| FLUX1.1 [pro] Ultra | `/v1/flux-pro-1.1-ultra` | $0.06 | Ultra high-resolution |
| FLUX1.1 [pro] Raw | `/v1/flux-pro-1.1-raw` | $0.06 | Candid photography feel |
| FLUX.1 Fill [pro] | `/v1/flux-pro-1.0-fill` | $0.05 | Inpainting |

> All FLUX.2 models support image editing via `input_image` — no separate editing endpoint needed.

## Basic Request Flow
```
1. POST to model endpoint
   └─> Response: { "polling_url": "..." }
2. GET polling_url (repeat until complete)
   └─> Response: { "status": "Pending" | "Ready" | "Error", ... }
3. When Ready, download result URL immediately (expires in 10 min)
```

## Quick Start (cURL)
```bash
# 1. Submit
curl -s -X POST "https://api.bfl.ai/v1/flux-2-pro" \
  -H "x-key: $BFL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "A serene mountain landscape at sunset", "width": 1024, "height": 1024}'
# Response: { "id": "abc123", "polling_url": "https://api.bfl.ai/v1/get_result?id=abc123" }

# 2. Poll
curl -s "POLLING_URL" -H "x-key: $BFL_API_KEY"
# When ready: { "status": "Ready", "result": { "sample": "https://...", "seed": 1234 } }

# 3. Download
curl -s -o output.png "IMAGE_URL"
```

## Image Input for Editing
Prefer URLs — API fetches them directly (no base64 needed):
```bash
curl -X POST "https://api.bfl.ai/v1/flux-2-pro" \
  -H "x-key: $BFL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Change the background to a sunset", "input_image": "https://example.com/photo.jpg"}'
```

Multi-reference (up to 4 images for klein, 8 for pro/max/flex):
```json
{
  "prompt": "The person from image 1 in the environment from image 2",
  "input_image": "https://example.com/person.jpg",
  "input_image_2": "https://example.com/background.jpg"
}
```

## Rate Limits
- **24 concurrent requests** (standard)
- Use **polling** for scripts/CLI; **webhooks** for production/high-volume
- Configure webhooks via `webhook_url` parameter in the request body

## API Key Setup
```bash
echo 'BFL_API_KEY=bfl_your_key_here' >> ~/.hermes/.env
```
Get a key: https://dashboard.bfl.ai/get-started → Create Key

## Related Skill
See **flux-best-practices** for prompting guidelines and model selection.
