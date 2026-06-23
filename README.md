# Hermes Skills Marketplace

A curated marketplace of custom skills for [Hermes Agent](https://hermes-agent.nousresearch.com),
enforcing **config-code separation** so every skill works for any agent out of the box.

## Quick Start

### Add this marketplace as a skill source

```bash
hermes skills tap add whichguy/hermes-skills-marketplace
```

### Browse and install

```bash
hermes skills browse          # All sources including this marketplace
hermes skills search usa      # Filter by keyword
hermes skills inspect whichguy/usaw-to-schedule  # Preview
hermes skills install whichguy/usaw-to-schedule  # Install
```

### Auto-sync (for the marketplace owner)

```bash
# Push local skill changes to GitHub
./scripts/sync_skills.sh push

# Pull marketplace updates to local Hermes
./scripts/sync_skills.sh pull

# Check if in sync
./scripts/sync_skills.sh check

# Show status
./scripts/sync_skills.sh status
```

A cron job runs `check_updates.sh` periodically and alerts when updates are available.

## Skills Included

26 custom skills across 5 categories — see [CATALOG.md](CATALOG.md) for the full list.

| Category | Count | Examples |
|----------|-------|---------|
| productivity | 11 | usaw-to-schedule, messaging-platform-formatting, email-utils |
| devops | 5 | script-first-cron-design, self-healing-cron-watchdogs, versioning-hermes-home |
| software-development | 5 | skill-marketplace, skill-testing-harness, simplify-code |
| creative | 3 | html-artifact, bfl-api, flux-best-practices |
| research | 2 | scheduled-research-briefs, live-event-status-updates |

## Config-Code Separation

Every skill enforces the separation principle:

| Layer | Where | What |
|-------|-------|------|
| Config | `metadata.hermes.config` frontmatter | Non-secret user-tunable defaults |
| Secrets | `required_environment_variables` frontmatter | API keys, tokens |
| Code | `scripts/*.py` | Pure logic, reads from `os.getenv()` |
| Templates | `templates/*` | Output formats (swappable) |
| References | `references/*.md` | Bulky docs (API specs, mappings) |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Use the `skill-marketplace` skill for guided authoring:

```
/skill skill-marketplace
```

## License

MIT (individual skills may vary — see each SKILL.md frontmatter)