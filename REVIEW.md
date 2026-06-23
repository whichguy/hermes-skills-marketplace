# Review Process for Skill Curators

## Tiers

| Tier | Location | Trust | Requirements |
|------|----------|-------|-------------|
| **Curated** | `skills/<category>/` | ★★ | CI passes + human review |
| **Community** | `community/<author>/` | ★ | CI passes only |
| **External Tap** | Any GitHub repo | ☆ | User's responsibility |

## Review Checklist

For a PR promoting a skill from `community/` to `skills/` (curated tier):

### Config-Code Separation (must pass)
- [ ] All user-tunable values declared in `metadata.hermes.config`
- [ ] All API keys/secrets declared in `required_environment_variables`
- [ ] All OAuth tokens declared in `required_credential_files`
- [ ] Scripts contain zero hardcoded user-tunable values
- [ ] No "replace this with..." or "change X to Y" instructions in SKILL.md prose

### Structure (must pass)
- [ ] SKILL.md ≤ 15k chars (bulky content moved to references/)
- [ ] Output formats in templates/ (not inline in SKILL.md)
- [ ] Logic in scripts/ (not inline in SKILL.md prose)
- [ ] Only allowed subdirs: scripts/, templates/, references/, assets/
- [ ] `platforms:` declared explicitly
- [ ] `requires_toolsets:` / `requires_tools:` declared if applicable

### Reusability (must pass)
- [ ] Skill works on a fresh Hermes install with no assumptions about user's environment
- [ ] No hardcoded paths (uses `${HERMES_HOME}` or `os.getenv()`)
- [ ] No hardcoded timezone, location, or personal preferences
- [ ] Defaults are sensible for a generic user, not the original author

### Security (must pass)
- [ ] No secrets in any file (CI scan passes)
- [ ] No credentials in SKILL.md or scripts
- [ ] Setup prompts exist for all required env vars
- [ ] Scripts don't log or print secrets

### Quality (reviewer judgment)
- [ ] Description starts with "Use when..." and describes the trigger class
- [ ] Procedure steps have checkable completion criteria
- [ ] Pitfalls section covers known failure modes
- [ ] Verification checklist present
- [ ] Skill doesn't duplicate an existing curated skill

## Promotion Flow

```
community/<author>/<skill>/  →  PR  →  CI passes  →  human review  →  skills/<category>/<skill>/
```

1. Author submits skill to `community/<author>/<skill-name>/`
2. CI validates automatically
3. Curator reviews using the checklist above
4. If approved: curator moves to `skills/<category>/` and updates index.json
5. If changes needed: curator leaves review comments on the PR

## Removal

A curated skill can be removed if:
- It's broken and the author is unresponsive for 30+ days
- It duplicates another skill (merge into the better one)
- Security issues are found and can't be patched

Removal is always a PR with a description explaining why. The skill is moved
to `community/archive/` — never deleted outright.