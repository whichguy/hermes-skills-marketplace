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

## Skills (27)

See [CATALOG.md](CATALOG.md) for the full list.

## Releasing updates (two-home skills)

Some skills are distribution snapshots of a canonical source elsewhere; refresh = rsync the source
over `skills/<name>/` (keep the marketplace-only SKILL.md hub-install blocks; **exclude `tests/`**
— the hub bundle fetch caps file count and the guard flags test env-fixtures, so tests stay in the
canonical repos), bump `version` in frontmatter + `.well-known/skills/index.json`, re-run the
validators, commit + push. Run the validators with the container venv python — macOS system 3.9
fails on the `X | None` annotations and homebrew 3.13 lacks pyyaml:
`docker exec -w /opt/data/hermes-skills-marketplace hermes /opt/hermes/.venv/bin/python scripts/validate_skill.py skills/<name>`:

- `next-best-questions` (formerly `information-gain`), `investigator` — source: `hermes-agent` repo (`whichguy/hermes-agent-1`,
  `skills/autonomous-ai-agents/<name>/`).
- `ask` — source: the live `$HERMES_HOME/skills/productivity/ask/` (exclude caches/dev files).

Installers must pin categories (dependency paths resolve through them):
`ask --category productivity`, then `next-best-questions --category autonomous-ai-agents`,
then `investigator --category autonomous-ai-agents`.

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