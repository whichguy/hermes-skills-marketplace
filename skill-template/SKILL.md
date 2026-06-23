---
name: skill-template
description: "Use when creating a new marketplace-ready skill. Shows the mandatory config-code separation pattern, frontmatter schema, and directory layout."
version: 1.0.0
author: Fortified Strength
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [template, skill-authoring, marketplace, config-separation]
    category: software-development
    related_skills: [hermes-agent-skill-authoring]
    config:
      - key: skill.search_radius_km
        description: "Default search radius in kilometers"
        default: 10
        prompt: "Default search radius (km)?"
      - key: skill.api_endpoint
        description: "API endpoint URL for search calls"
        default: "https://api.example.com/v1/search"
        prompt: "API endpoint URL?"
      - key: skill.timezone
        description: "Timezone for result timestamps (IANA format)"
        default: "UTC"
        prompt: "Your timezone (e.g. America/Los_Angeles)?"
      - key: skill.output_format
        description: "Output format: markdown, json, or text"
        default: "markdown"
        prompt: "Output format (markdown/json/text)?"
required_environment_variables:
  - name: SKILL_API_KEY
    prompt: "Enter your API key"
    help: "Get one at https://example.com/api-keys"
    required_for: "API search calls"
---

# Skill Template — Marketplace-Ready Skill

Copy this directory as the starting point for every new skill. It shows the
mandatory **config-code separation** pattern that makes skills reusable across
any Hermes agent without editing SKILL.md.

## When to Use

- You're creating a new skill for the marketplace
- You're retrofitting an existing skill to be marketplace-ready

## Directory Layout

```
skill-template/
├── SKILL.md               # Triggers, procedure, pitfalls (this file)
├── scripts/
│   └── main.py            # Pure logic — reads config from env, NEVER hardcodes
├── templates/
│   └── output.md          # Output format templates (swappable, not inline)
└── references/
    └── api-reference.md   # Bulky docs (API specs, field mappings, rate limits)
```

## The Config-Code Separation Rule

| Layer | Frontmatter key | What lives here | Where it's stored at runtime |
|-------|----------------|-----------------|------------------------------|
| **Config** | `metadata.hermes.config` | Non-secret user-tunable defaults | `config.yaml` under `skills.config.*` |
| **Secrets** | `required_environment_variables` | API keys, tokens | `~/.hermes/.env` |
| **Credentials** | `required_credential_files` | OAuth token files | `~/.hermes/credentials/` |
| **Code** | `scripts/*.py` | Pure logic, reads from env | Runs in terminal/execute_code sandbox |
| **Templates** | `templates/*` | Output format templates | `${HERMES_SKILL_DIR}/templates/` |
| **References** | `references/*.md` | Bulky docs, API specs | `${HERMES_SKILL_DIR}/references/` |
| **SKILL.md body** | Prose | Procedure + triggers + pitfalls only | Loaded into context on demand |

**Golden rule:** A skill downloaded by Agent A in San Ramon, CA must work for
Agent B in London without editing a single line of SKILL.md or scripts/*.py.

## Scripts Read Config from Environment — Never Hardcode

```python
# scripts/main.py

# BAD — hardcoded values that should be config
DEFAULT_RADIUS = 10
API_ENDPOINT = "https://api.example.com/v1/search"
USER_TIMEZONE = "America/Los_Angeles"

# GOOD — read from environment (Hermes injects config values as env vars)
import os
radius = os.getenv("SKILL_SEARCH_RADIUS_KM", "10")
api_endpoint = os.getenv("SKILL_API_ENDPOINT", "https://api.example.com/v1/search")
timezone = os.getenv("SKILL_TIMEZONE", "UTC")
```

Hermes automatically passes `config.yaml` values and `.env` secrets into
`terminal` and `execute_code` sandboxes. Scripts just read `os.getenv()`.

## Procedure: Creating a New Skill from This Template

1. **Copy the directory:** `cp -r skill-template/ skills/<category>/<your-skill-name>/`
2. **Rename in frontmatter:** Update `name`, `description`, `version`, `author`
3. **Declare config keys:** List every user-tunable value in `metadata.hermes.config`
4. **Declare secrets:** List every API key in `required_environment_variables`
5. **Write scripts:** Pure logic in `scripts/*.py`, reading from `os.getenv()`
6. **Write templates:** Output formats in `templates/`
7. **Move bulky docs:** API specs, field mappings → `references/`
8. **Keep SKILL.md lean:** Triggers + procedure + pitfalls only (≤ 15k chars)
9. **Update index:** Add entry to `.well-known/skills/index.json`
10. **Validate:** Run `python scripts/validate_skill.py skills/<category>/<your-skill-name>/`

## Common Pitfalls

1. **Hardcoding user-tunable values in SKILL.md prose.** A default like "radius 25km for rural areas" is a config value — declare it in `metadata.hermes.config` with a default, not in prose.

2. **Embedding API keys in scripts.** Even as comments. Use `required_environment_variables` and read from `os.getenv()`.

3. **Putting output format templates inline in SKILL.md.** If the format is more than 3 lines, it goes in `templates/`.

4. **Stuffing everything in SKILL.md.** SKILL.md is procedure — API specs go in `references/`, output formats in `templates/`, logic in `scripts/`.

5. **Forgetting platforms declaration.** Always declare `platforms:` explicitly. If your skill only works on Linux (e.g., needs apt-get), say so.

6. **Not updating index.json.** The `.well-known/skills/index.json` file is how `hermes skills tap add` discovers your skill. Forgetting this = invisible skill.

## Verification Checklist

- [ ] Frontmatter has all mandatory fields (name, description, version, author, license, platforms)
- [ ] `metadata.hermes.config` declares ALL user-tunable values
- [ ] `required_environment_variables` declares ALL API keys/secrets
- [ ] `scripts/*.py` contains zero hardcoded user-tunable values
- [ ] `templates/` holds output formats (not inline in SKILL.md)
- [ ] `references/` holds bulky docs (SKILL.md ≤ 15k chars)
- [ ] `platforms:` declared explicitly
- [ ] `requires_toolsets:` / `requires_tools:` declared if skill needs specific tools
- [ ] `.well-known/skills/index.json` updated with new skill entry