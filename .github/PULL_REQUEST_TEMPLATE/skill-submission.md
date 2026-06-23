## Skill Submission

### Skill Name
<!-- e.g., wellness-finder -->

### Category
<!-- productivity, devops, research, creative, software-development, health, finance -->

### One-line description
<!-- "Use when <trigger>. <behavior>." -->

### Config-Code Separation Checklist

- [ ] All user-tunable values declared in `metadata.hermes.config`
- [ ] All API keys/secrets declared in `required_environment_variables`
- [ ] All OAuth tokens declared in `required_credential_files`
- [ ] Scripts contain zero hardcoded user-tunable values (read from `os.getenv()`)
- [ ] No "replace this with..." or "change X to Y" instructions in SKILL.md prose
- [ ] Output formats in `templates/` (not inline in SKILL.md)
- [ ] Bulky docs in `references/` (SKILL.md ≤ 15k chars)
- [ ] `platforms:` declared explicitly
- [ ] `.well-known/skills/index.json` updated with new skill entry

### Validation

- [ ] `python scripts/validate_skill.py skills/<category>/<name>/` passes
- [ ] `python scripts/check_config_separation.py` passes
- [ ] `python scripts/check_index_sync.py` passes
- [ ] `python scripts/scan_secrets.py` passes
- [ ] `python scripts/scan_hardcoded_config.py` passes

### Reusability

- [ ] Skill works on a fresh Hermes install with no environment assumptions
- [ ] No hardcoded paths (uses `${HERMES_HOME}` or `os.getenv()`)
- [ ] No hardcoded timezone, location, or personal preferences
- [ ] Defaults are sensible for a generic user