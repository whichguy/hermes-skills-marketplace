# Contributing to the Hermes Skills Marketplace

## Quick Start

1. **Copy the template:**
   ```bash
   cp -r skill-template/ skills/<category>/<your-skill-name>/
   ```

2. **Edit SKILL.md** — update frontmatter, write procedure, declare config.

3. **Write scripts** — pure logic in `scripts/*.py`, reading from `os.getenv()`.

4. **Update the index** — add your skill to `.well-known/skills/index.json`.

5. **Validate locally:**
   ```bash
   python scripts/validate_skill.py skills/<category>/<your-skill-name>/
   python scripts/check_config_separation.py
   python scripts/check_index_sync.py
   python scripts/scan_secrets.py
   ```

6. **Open a PR** — CI runs all checks automatically.

## The Config-Code Separation Rule

This is the single most important rule in this marketplace. **Every
user-tunable value must be declared in frontmatter, not hardcoded in code or
prose.**

### What counts as "config"?

| Type | Frontmatter key | Example |
|------|----------------|---------|
| User-tunable default | `metadata.hermes.config` | search radius, output format, timezone |
| API key / secret | `required_environment_variables` | `MAPS_API_KEY`, `STRAVA_TOKEN` |
| OAuth credential file | `required_credential_files` | `google_token.json` |

### What counts as "code"?

| Location | What goes here |
|----------|---------------|
| `scripts/*.py` | Pure logic — API calls, data processing, formatting |
| `templates/*` | Output format templates (HTML, markdown, text) |
| `references/*.md` | Bulky documentation (API specs, field mappings) |

### The golden rule

> A skill downloaded by Agent A in San Ramon, CA must work for Agent B in
> London without editing a single line of SKILL.md or scripts/*.py.

If a user needs to change a value to use the skill, that value belongs in
`metadata.hermes.config` with a sensible default — not in prose saying
"change this to..."

## Skill Directory Structure

```
skills/<category>/<skill-name>/
├── SKILL.md               # Required: triggers, procedure, pitfalls
├── scripts/               # Optional: helper scripts (pure logic)
│   └── main.py
├── templates/             # Optional: output format templates
│   └── output.md
├── references/            # Optional: bulky docs
│   └── api-reference.md
└── assets/                # Optional: static assets (images, etc.)
```

## Categories

| Category | Description |
|----------|-------------|
| `productivity` | Documents, spreadsheets, scheduling, email |
| `devops` | Infrastructure, deployment, monitoring |
| `research` | Academic search, data collection, analysis |
| `creative` | Content generation, design, media |
| `software-development` | Code, testing, review, CI/CD |
| `health` | Fitness, wellness, medical info |
| `finance` | Financial data, payments, accounting |

Don't see a fit? Open an issue proposing a new category.

## Frontmatter Reference

```yaml
---
name: my-skill                    # lowercase + hyphens, ≤64 chars
description: "Use when <trigger>. <behavior>."  # ≤1024 chars
version: 1.0.0                    # semver
author: Your Name
license: MIT
platforms: [linux, macos, windows]  # explicit, don't default to all

metadata:
  hermes:
    tags: [keyword1, keyword2]
    category: productivity
    related_skills: [other-skill]
    requires_toolsets: [web, terminal]      # optional
    requires_tools: [web_search]            # optional
    fallback_for_toolsets: [browser]        # optional
    config:                                  # ALL user-tunable values
      - key: my.setting
        description: "What this controls"
        default: "sensible-default"
        prompt: "Setup prompt for this value"

required_environment_variables:              # ALL API keys/secrets
  - name: MY_API_KEY
    prompt: "Enter your API key"
    help: "Get one at https://example.com"
    required_for: "API calls"

required_credential_files:                   # OAuth tokens, etc.
  - path: token.json
    description: "OAuth token (created by setup script)"
---
```

## CI Checks

Every PR must pass:

1. **validate_skill.py** — frontmatter schema, required fields, size limits
2. **check_config_separation.py** — no hardcoded config in scripts
3. **check_index_sync.py** — index.json matches actual skills
4. **scan_secrets.py** — no hardcoded secrets in any file
5. **scan_hardcoded_config.py** — no "replace this with..." instructions in prose

## Review Process

See [REVIEW.md](REVIEW.md) for the curator review checklist.