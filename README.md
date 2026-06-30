# Hermes Skills Marketplace

Custom skills for [Hermes Agent](https://hermes-agent.nousresearch.com) with
**config-code separation** — user-tunable values live in frontmatter config
declarations, not hardcoded in scripts or prose.

## Install

```bash
# Add as a skill source
hermes skills tap add whichguy/hermes-skills-marketplace

# Browse
hermes skills browse

# Install a skill
hermes skills install whichguy/hermes-skills-marketplace/skills/<skill-name>

# Check for updates
hermes skills check
hermes skills update
```

## Skills (25)

See [CATALOG.md](CATALOG.md) for the full list.

## Config-Code Separation

Every skill separates config from code:

| Layer | Where | What |
|-------|-------|------|
| Config | `metadata.hermes.config` frontmatter | Non-secret user-tunable defaults |
| Secrets | `required_environment_variables` frontmatter | API keys, tokens |
| Code | `scripts/*.py` | Pure logic, reads from `os.getenv()` |
| Templates | `templates/*` | Output formats |
| References | `references/*.md` | Bulky docs |

## CI Validators (non-redundant with Hermes built-ins)

These 4 validators enforce config-code separation — Hermes doesn't do this natively:

- `validate_skill.py` — frontmatter schema + config declarations
- `validate_all_skills.py` — runs validator on all skills
- `check_config_separation.py` — scans scripts for hardcoded secrets
- `scan_hardcoded_config.py` — catches "replace this with..." in prose

## License

MIT
