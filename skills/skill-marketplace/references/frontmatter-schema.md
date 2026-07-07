# Frontmatter Schema Reference

Complete reference for SKILL.md frontmatter fields in the marketplace.

## Mandatory Fields

| Field | Type | Constraint | Example |
|-------|------|-----------|---------|
| `name` | string | lowercase + hyphens, ≤64 chars | `wellness-finder` |
| `description` | string | ≤1024 chars, starts with "Use when" | `"Use when finding wellness facilities."` |
| `version` | string | semver (x.y.z) | `1.0.0` |
| `author` | string | author name | `The User` |
| `license` | string | SPDX identifier | `MIT` |
| `platforms` | list | one or more of: linux, macos, windows | `[linux, macos, windows]` |

## Config Declaration (`metadata.hermes.config`)

```yaml
metadata:
  hermes:
    config:
      - key: wellness.search_radius_km
        description: "Default search radius in kilometers"
        default: 10
        prompt: "Default search radius (km)?"
```

### Config key naming convention

Use dot notation: `<skill-name>.<setting>`

### What belongs in config vs env vs credentials

| Type | Example | Frontmatter key |
|------|---------|----------------|
| Non-secret default | search radius, format, timezone | `metadata.hermes.config` |
| API key / token | `MAPS_API_KEY` | `required_environment_variables` |
| OAuth token file | `google_token.json` | `required_credential_files` |

## Secret Declaration (`required_environment_variables`)

```yaml
required_environment_variables:
  - name: MAPS_API_KEY
    prompt: "Enter your Google Maps API key"
    help: "Get one at https://console.cloud.google.com"
    required_for: "Place search API calls"
```

## Credential File Declaration (`required_credential_files`)

```yaml
required_credential_files:
  - path: google_token.json
    description: "Google OAuth2 token (created by setup script)"
```

## Conditional Activation

```yaml
metadata:
  hermes:
    requires_toolsets: [web, terminal]    # hidden if these toolsets are off
    fallback_for_toolsets: [browser]      # hidden when browser toolset is active
```

## Platform Gating

```yaml
platforms: [linux, macos]                 # hidden on Windows
platforms: [linux, macos, windows]        # cross-platform (most common)
```