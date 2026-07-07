---
name: skill-marketplace
description: "Use when creating, validating, or publishing a Hermes skill for the marketplace. Enforces config-code separation, generates proper frontmatter, and guides publishing to a GitHub skill registry."
version: 1.0.0
author: Fortified Strength
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [skill-authoring, marketplace, publishing, config-separation, reuse]
    category: software-development
    related_skills: [hermes-agent-skill-authoring, hermes-agent]
    requires_toolsets: [terminal, file]
    config:
      - key: skill-marketplace.repo
        description: "GitHub repo for publishing (org/repo format)"
        default: "whichguy/hermes-skills-marketplace"
        prompt: "GitHub repo for skill publishing (org/repo)?"
      - key: skill-marketplace.default_license
        description: "Default license for new skills"
        default: "MIT"
        prompt: "Default license for published skills?"
      - key: skill-marketplace.default_author
        description: "Default author name for new skills"
        default: ""
        prompt: "Default author name for published skills?"
---

# Skill Marketplace — Author, Validate, Publish

This skill guides you through creating marketplace-ready Hermes skills with
proper **config-code separation** — so every skill works for any agent out of
the box without editing SKILL.md.

## When to Use

- User asks to create a new skill for the marketplace
- User asks to publish a skill to GitHub
- User asks to validate a skill before submitting
- User asks to retrofit an existing skill for marketplace readiness
- User asks to set up or browse the skill marketplace
- User asks to sanitize skills before publishing (privacy audit)
- User asks whether something is redundant with Hermes built-ins

## When NOT to Use

- Creating a quick personal/local skill (use `skill_manage(action='create')` instead)
- Modifying an in-repo Hermes skill (use `hermes-agent-skill-authoring` skill)

## The Config-Code Separation Principle

**Every user-tunable value must be declared in frontmatter — never hardcoded
in scripts or prose.**

A skill downloaded by Agent A in San Ramon, CA must work for Agent B in
London without editing a single line.

| Layer | Frontmatter key | What | Runtime storage |
|-------|----------------|------|-----------------|
| Config | `metadata.hermes.config` | Non-secret defaults | `config.yaml` under `skills.config.*` |
| Secrets | `required_environment_variables` | API keys, tokens | `~/.hermes/.env` |
| Credentials | `required_credential_files` | OAuth token files | `~/.hermes/credentials/` |
| Code | `scripts/*.py` | Pure logic, `os.getenv()` | terminal sandbox |
| Templates | `templates/*` | Output formats | `${HERMES_SKILL_DIR}/templates/` |
| References | `references/*.md` | Bulky docs | `${HERMES_SKILL_DIR}/references/` |
| SKILL.md body | Prose | Triggers + procedure + pitfalls | Loaded on demand |

## Design Principle: Use Hermes Built-ins, Don't Rebuild Them

Hermes already has a full skills marketplace infrastructure. **Don't rebuild
what exists.** Use the built-in commands:

| Need | Hermes built-in (USE THIS) |
|------|---------------------------|
| Add a skill source | `hermes skills tap add <org/repo>` |
| Browse skills | `hermes skills browse` / `hermes skills search <query>` |
| Install a skill | `hermes skills install <identifier>` |
| Check for updates | `hermes skills check` |
| Apply updates | `hermes skills update` |
| Security scan | `hermes skills audit` |
| Publish a skill | `hermes skills publish <path> --to github --repo <org/repo>` |

**Only build what Hermes doesn't have:** config-code separation enforcement.
The 4 validators (`validate_skill.py`, `validate_all_skills.py`,
`check_config_separation.py`, `scan_hardcoded_config.py`) are the only
non-redundant infrastructure. Everything else (sync scripts, cron update
checkers, index generators, secret scanners) is redundant with Hermes
built-ins and should not be rebuilt.

## Procedure: Creating a Marketplace-Ready Skill

### Step 1 — Identify the skill's config surface

Before writing anything, list every value a user might need to tune:

- API keys or tokens → `required_environment_variables`
- OAuth credentials → `required_credential_files`
- Search radius, output format, timezone, defaults → `metadata.hermes.config`
- Required tools (web, terminal, browser) → `requires_toolsets`

**Completion criterion:** You have a written list of every config key, env
var, and credential the skill needs. Nothing is left implicit.

### Step 2 — Scaffold from template

The marketplace repo is at `/opt/data/hermes-skills-marketplace/`. The repo
uses a **flat structure**: `skills/<name>/SKILL.md` (no category subdirs).
Categories are declared in `skills.sh.json` groupings, not in the directory
structure. This is required because the Hermes Hub indexer scans only one
level deep under the tap path.

```bash
cp -r /opt/data/hermes-skills-marketplace/skill-template/ \
  /opt/data/hermes-skills-marketplace/skills/<skill-name>/
```

**Completion criterion:** Directory exists with SKILL.md, scripts/, templates/, references/.

### Step 3 — Write frontmatter

Fill in all frontmatter fields. See `references/frontmatter-schema.md` for
the full schema with examples.

```yaml
---
name: my-skill
description: "Use when <trigger>. <behavior>."
version: 1.0.0
author: <author>
license: MIT
platforms: [linux, macos, windows]

metadata:
  hermes:
    tags: [keyword1, keyword2]
    category: <category>
    related_skills: [other-skill]
    requires_toolsets: [web, terminal]
    config:
      - key: my.setting
        description: "What this controls"
        default: "sensible-default"
        prompt: "Setup prompt"

required_environment_variables:
  - name: MY_API_KEY
    prompt: "Enter your API key"
    help: "Get one at https://example.com"
    required_for: "API calls"
---
```

**Completion criterion:** Every config value, env var, and credential is
declared in frontmatter. No user-tunable value is left for prose.

### Step 4 — Write scripts (pure logic)

Scripts in `scripts/*.py` must:
- Read ALL config from `os.getenv()` — never hardcode
- Contain NO API keys, endpoints, or user-tunable defaults as literals
- Use `${HERMES_SKILL_DIR}` for relative paths, not hardcoded paths

```python
import os

# GOOD
radius = os.getenv("MY_SKILL_RADIUS_KM", "10")
api_key = os.getenv("MY_API_KEY", "")

# BAD
radius = 10
API_KEY = "sk-..."
```

**Completion criterion:** `grep -rn "os.getenv" scripts/*.py` shows every
config read. No hardcoded values found by `check_config_separation.py`.

### Step 5 — Write SKILL.md body (procedure only)

SKILL.md body contains:
- `## When to Use` — trigger conditions
- `## Procedure` — numbered steps with completion criteria
- `## Common Pitfalls` — known failure modes
- `## Verification Checklist` — post-action checks

SKILL.md body does NOT contain:
- API endpoints (those are in config)
- Output format templates (those are in `templates/`)
- API documentation (that's in `references/`)
- No placeholder substitution instructions (that's what config is for)

**Completion criterion:** SKILL.md ≤ 15k chars. `scan_hardcoded_config.py` passes.

### Step 6 — Publish

The Hermes Hub indexes the repo automatically via the GitHub Contents API.
No manual index.json maintenance needed.

```bash
cd /opt/data/hermes-skills-marketplace
git add skills/<skill-name>/
git add skills.sh.json  # if categories changed
git commit -m "feat: add <skill-name> skill"
git push
```

**Completion criterion:** Skill is pushed to GitHub. `hermes skills tap add
whichguy/hermes-skills-marketplace` + `hermes skills search <name>` finds it.

### Step 7 — Validate (config-code separation only)

Only run the 4 validators that check config-code separation (Hermes built-ins
handle the rest):

```bash
cd /opt/data/hermes-skills-marketplace
python scripts/validate_all_skills.py     # frontmatter + config declarations
python scripts/check_config_separation.py # no hardcoded secrets in scripts
python scripts/scan_hardcoded_config.py   # no "replace this with..." in prose
```

**Completion criterion:** All checks pass with zero errors.

## Procedure: Connecting to the Marketplace (Setup)

There are **three built-in Hermes mechanisms** for connecting an agent to the
marketplace. Use the one that fits the situation.

### Option A — Hermes Skills Hub Tap (for any Hermes agent, public discovery)

This is the native marketplace flow. Other Hermes agents use this to discover
and install your skills from GitHub.

```bash
# 1. Add the marketplace as a tap (one-time per agent)
hermes skills tap add whichguy/hermes-skills-marketplace

# 2. Browse/search for skills
hermes skills browse                    # Shows all sources including this marketplace
hermes skills search usaw               # Filter by keyword

# 3. Install a skill (downloads from GitHub to ~/.hermes/skills/)
hermes skills install whichguy/hermes-skills-marketplace/skills/<skill-name>

# 4. Check for updates
hermes skills check                     # Checks all installed hub skills
hermes skills update                    # Updates outdated skills
```

**How it works:** The Hermes Hub indexer calls the GitHub Contents API on the
tap path (`skills/`), lists directories one level deep, and looks for
`<dir>/SKILL.md` in each. That's why the marketplace uses a **flat structure**
(`skills/<name>/SKILL.md`) — category subdirs would be invisible to the
indexer. Categories are declared in `skills.sh.json` instead.

**Prerequisites:**
- Set `GITHUB_TOKEN` env var (or have `gh` CLI authenticated) to avoid
  GitHub API rate limits (60 req/hr unauthenticated vs 5000/hr authenticated)
- Community-sourced skills go through a security scan on install
- If scan blocks a skill, use `hermes skills install --force <id>` (requires
  the skill to not have a CRITICAL verdict) or use Option B below

### Option B — external_dirs (for local clone, no security scan)

If the marketplace repo is cloned locally, mount it directly as a skill
source. No security scan, no rate limits.

```bash
# 1. Clone the marketplace repo
git clone https://github.com/whichguy/hermes-skills-marketplace.git \
  /opt/data/hermes-skills-marketplace

# 2. Add to Hermes config
hermes config set skills.external_dirs '["/opt/data/hermes-skills-marketplace/skills"]'

# 3. Restart Hermes (or /reset)
```

Skills from the external dir appear alongside bundled skills. No install
step needed — they're available immediately.

### Which option to use?

| Situation | Option |
|-----------|--------|
| Other agents discovering your skills | A (Skills Hub tap) |
| Local development, no security scan | B (external_dirs) |
| Pushing your local changes to GitHub | `git add && git commit && git push` |
| Pulling marketplace updates to local | `git pull` in the cloned repo |
| Checking for updates | `hermes skills check` |

## Procedure: Privacy Sanitization Before Publishing

**This is mandatory before publishing any skill to a public repo.** Skills
built for personal use accumulate personal data in prose, examples, and
scripts. Publishing without sanitizing exposes personal info and is
embarrassing at best, dangerous at worst.

### Step 1 — Audit for personal information

Scan every file in the skill for:

- Email addresses (especially personal/corporate domains)
- Phone numbers (10+ digit sequences, formatted phone numbers)
- WhatsApp/messaging group IDs (e.g., `YOUR_WHATSAPP_GROUP_ID`)
- Home address components (city name, ZIP code, street address)
- Personal names (family members, colleagues, CPA, doctor, etc.)
- Organization domains (your company, church, gym)
- Venue/hotel names tied to personal events
- TV provider, ISP, or other service subscriptions
- IP addresses (except 127.0.0.1 and 0.0.0.0 in config examples)

Use a regex scan across all files in the skill directory. See
`references/privacy-audit-patterns.md` for the pattern list.

### Step 2 — Extract personal values to config.yaml

For each personal value found, extract it to `metadata.hermes.config` in the
skill's frontmatter with a generic default. Write the real personal value to
the user's `config.yaml` under `skills.config.<key>`.

Example: `"San Ramon"` in SKILL.md prose →
- In published SKILL.md: `config: [{key: personal.home_city, default: "Your City"}]`
- In user's config.yaml: `skills.config.personal.home_city: "San Ramon"`

### Step 3 — Replace personal values with generic defaults

In every file (SKILL.md, references/*, scripts/*, templates/*), replace:
- Personal names → "Example Person", "Family Member", "CPA Contact"
- Email addresses → "you@example.com", "coach@your-org.org"
- Phone numbers → "(555) 123-4567"
- Addresses → "123 Venue St", "Venue City", "VENUE_ZIP"
- WhatsApp group IDs → "REDACTED" or `${CONFIG_KEY}`
- Organization domains → "your-org.org", "church-example.org"
- Venue/hotel names → "Venue Name", "Hotel Name"
- TV provider → "TV Provider"

### Step 4 — Decide: publish vs keep private

Some skills are too personal to publish at all. Criteria for keeping private:
- Contains a relationship graph, family approval list, or personal context model
- Contains personal schedule/timeline details (travel dates, hotel reservations)
- Contains cron job IDs, delivery channel identifiers tied to personal accounts
- The skill's core function is managing the user's personal life

If keeping private: do NOT copy to the marketplace repo. Keep it in
`~/.hermes/skills/` only.

### Step 5 — Re-audit after sanitization

Run the audit scan again on the sanitized files. Must find **zero** personal
information before publishing.

**Completion criterion:** Full re-audit finds zero matches. Personal values
## Procedure: Retrofitting a Single Skill

1. **Audit for personal info:** Run privacy audit (see Privacy Sanitization procedure)
2. **Extract personal config:** Move personal values to `metadata.hermes.config` + `config.yaml`
3. **Audit for hardcoded values:** List every hardcoded value in SKILL.md prose and scripts/*.py
4. **Extract config:** Move each to `metadata.hermes.config` with a generic default
5. **Extract secrets:** Move API keys to `required_environment_variables`
6. **Rewrite scripts:** Substitute hardcoded values with `os.getenv()` calls
7. **Move bulky content:** API specs → `references/`, formats → `templates/`
8. **Clean SKILL.md:** Remove placeholder substitution instructions
9. **Flatten directory:** Ensure `skills/<name>/SKILL.md` (no category subdirs)
10. **Validate:** Run 4 config-code separation validators
11. **Re-audit privacy:** Confirm zero personal info remains

## Procedure: Bulk Retrofitting Many Skills

When retrofitting a large library (50+ skills), automate the repetitive parts:

1. **Scan all SKILL.md files** — parse frontmatter, flag which skills are
   missing `metadata.hermes.config`, `platforms:`, or other required fields.
2. **Generate new frontmatter programmatically** — for each skill, inject a
   minimal config block (e.g. `<name>.enabled` with `default: true`), add
   `platforms: [linux, macos, windows]` if missing, fill in `version`,
   `author`, `license`, `tags`, `category` if absent.
3. **Write back via `execute_code`** — use `yaml.dump()` to serialize the new
   frontmatter and `write_text()` to update SKILL.md. The sandbox can write
   to `~/.hermes/skills/` but may hit `PermissionError` on read-only bundled
   skills (see pitfall #8 below).
4. **Copy to marketplace repo** — `shutil.copytree()` each skill directory
   into `marketplace/skills/<category>/<name>/`.
5. **Generate index.json** — collect frontmatter from all skills and write
   `.well-known/skills/index.json` with all entries.
6. **Run all 5 CI validators** — fix any failures, iterate.

**Completion criterion:** All skills pass `validate_all_skills.py`,
zero failures.

## References

- `references/frontmatter-schema.md` — Complete frontmatter field reference with examples
- `references/claude-code-learnings.md` — Research from agentskills.io spec, Anthropic's skills repo, and community marketplaces
- `references/validator-tuning.md` — CI validator architecture, false-positive patterns, advisory vs hard-fail rules, BUILTIN_ENV set
- `references/github-repo-setup.md` — GitHub repo creation, git identity, sync script architecture, cron integration, custom vs bundled skill detection
- `references/privacy-audit-patterns.md` — Regex patterns for scanning skills before publishing; replacement strategy; publish-vs-private decision criteria

## Common Pitfalls

1. **Hardcoding "sensible defaults" in scripts.** A default of `10` for
   radius might be wrong for a rural user. Put it in `metadata.hermes.config`
   with `default: 10` — the user can override it during setup without editing
   the script.

2. **Forgetting `required_environment_variables`.** If your script calls
   `os.getenv("MY_API_KEY")`, that var MUST be declared in frontmatter. The
   CI check `validate_skill.py` catches this.

3. **Embedding output format in SKILL.md.** If your format template is more
   than 3 lines, it belongs in `templates/`. SKILL.md is procedure, not
   formatting.

4. **Not declaring `platforms:`.** Always declare explicitly. If your skill
   uses `apt-get`, it's Linux only.

5. **Forgetting to update `skills.sh.json`.** Categories are declared in
   `skills.sh.json` groupings, not directory structure. When adding a skill
   in a new category (e.g. `sports`), add the grouping and the skill name to
   the array before pushing.

6. **Using `skill_manage(action='create')` for marketplace skills.** That
   writes to `~/.hermes/skills/` (personal). Use `write_file` to the
   marketplace repo's `skills/<name>/SKILL.md` instead.

7. **Referencing user-local skills in `related_skills`.** Only reference
   skills that exist in the marketplace repo or the official Hermes repo.

8. **Read-only bundled skills block `execute_code` writes.** In-repo skills
   may have `-r--r--r--` permissions. The `execute_code` sandbox gets
   `PermissionError` when trying to write. Fix: `chmod u+w <SKILL.md>` via
   `terminal` first, then re-run the write from `execute_code`.

9. **Secret scanners produce false positives on placeholders.** A generic
   regex like `(api_key|token)\s*=\s*["']...["']` matches placeholders in
   docstrings: `API_KEY="COMFY_..."`, `export KEY="***"`, and even
   `api_key=api_key` (variable self-reference in error messages). Fix: only
   scan for real token formats (`sk-...`, `ghp_...`, `AIza...`, `xox...`,
   `AKIA...`, PEM blocks). Exclude values containing `...`, `***`,
   `YOUR_`, `<...>`, `EXAMPLE`, `PLACEHOLDER`, or `XXXX`.

10. **Built-in env vars don't need `required_environment_variables` declaration.**
    `HERMES_HOME`, `HERMES_SESSION_ID`, `HERMES_SKILL_DIR`, `HERMES_GWS_BIN`,
    `PATH`, `HOME`, `USER` are injected by Hermes at runtime — scripts can
    `os.getenv()` them freely. The validator should skip these in the
    undeclared-env-var check. Maintain a `BUILTIN_ENV` set in the validator.

11. **Description format check should NOT require "Use when..." prefix.**
    Many valid Hermes skills start their description differently (e.g.
    "TDD: enforce RED-GREEN-REFACTOR"). Enforcing a "Use when..." prefix
    causes 100+ false failures on existing skills. Keep it as a
    recommendation in the template, not a CI hard-fail.

12. **SKILL.md size limit and config absence should be advisory, not failure.**
    Skills like `hermes-agent` (45k chars) and `personal-context-integration`
    (46k chars) are legitimately large. The 15k-char recommendation and the
    "no config declared" warning should be advisory (printed but not
    exit-code failures). Only the 150k hard limit should fail CI.

13. **external_dirs name collisions cause ambiguous skill_view.** If the
    same skill name exists in both `~/.hermes/skills/` and an external_dirs
    path, `skill_view(name)` fails with "Ambiguous skill name" and lists
    both paths. Fix: either don't duplicate skills in both locations, or
    use the full categorized path (`skill_view('category/skill-name')`).

14. **Privacy sanitization is mandatory before publishing.** Skills built for
    personal use contain email addresses, phone numbers, WhatsApp group IDs,
    home addresses, family names, and organization domains. ALWAYS run the
    privacy audit (see Procedure: Privacy Sanitization Before Publishing)
    before pushing to a public repo. Extract personal values to
    `config.yaml`, replace with generic defaults in the published skill.

15. **Some skills are too personal to publish at all.** Skills that manage
    relationship graphs, personal schedules, or contain cron job IDs /
    delivery channel identifiers should stay in `~/.hermes/skills/` only.
    Don't copy them to the marketplace repo even after sanitizing — the
    skill's structure itself reveals personal patterns.

16. **Redundant infrastructure wastes effort.** Before building sync scripts,
    cron update checkers, index generators, or secret scanners, check if
    Hermes already has the capability. `hermes skills check`, `hermes skills
    update`, `hermes skills audit`, and `hermes skills publish` cover most
    marketplace operations. Only build what Hermes doesn't have (config-code
    separation validators).

17. **GitHub Actions workflow files need `workflow` scope on the token.**
    `gh auth` with only `repo` scope can create repos and push code, but
    `.github/workflows/*.yml` files are rejected. Fix:
    `gh auth refresh -h github.com -s workflow` (requires interactive device
    code flow).

18. **Hub indexer scans only ONE level deep.** The `_list_skills_in_repo`
    function in `tools/skills_hub.py` calls the GitHub Contents API on the
    tap path, lists directories, and looks for `<dir>/SKILL.md` in each —
    one level only. Category subdirs (`skills/<category>/<name>/SKILL.md`)
    are invisible. Fix: use flat structure (`skills/<name>/SKILL.md`) +
    `skills.sh.json` for category groupings.

19. **Verify skill_view works after publishing.** Once a skill exists in both
    the local `~/.hermes/skills/` path and the marketplace `external_dirs`
    path, `skill_view(name)` becomes ambiguous. Either delete the duplicate
    or always use the categorized path (`skill_view('category/skill-name')`)
    in references and SKILL.md cross-links.

20. **Config deference: don't override Hermes config in skill code examples.**
    If Hermes already has a config key for a limit (e.g. `max_turns`,
    `timeout`, `max_children`), skill code examples should NOT hardcode
    `--max-turns 120` or equivalent overrides. The skill's job is to
    document the pattern, not impose its own limits. Let Hermes config be
    the source of truth. Only hardcode when the skill has a domain-specific
    reason (e.g. SDLC phases need 1 turn for text-output phases). Wrong:
    `prompt_model.py --max-turns 120`. Right: omit the flag and let the
    script's default (None) defer to Hermes config. Add a pitfall in the
    skill itself explaining this principle so future maintainers don't
    re-add the override.

21. **Context pollution: dispatch synthesis, don't read large files into
    main context.** When a skill's pattern involves reading multiple
    subagent/model output files (5-15K chars each), the synthesis step
    should be dispatched to another model call — NOT done inline in the
    controller's context. Loading 3-6 review files into main context
    pollutes it with 30-90K chars that are never needed again. Wrong:
    "Read all N output files, synthesize in your head." Right: "Dispatch
    synthesis to GLM via prompt_model.py, read only the final consensus
    file." The controller should only ever read the final deliverable.

## Verification Checklist

- [ ] All user-tunable values in `metadata.hermes.config`
- [ ] All API keys in `required_environment_variables`
- [ ] All OAuth tokens in `required_credential_files`
- [ ] Scripts read from `os.getenv()` — zero hardcoded user-tunable values
- [ ] No secrets in any file (use real token format patterns, not generic regex)
- [ ] No placeholder substitution instructions in prose
- [ ] SKILL.md ≤ 15k chars (advisory; 150k hard limit)
- [ ] Output formats in `templates/`
- [ ] Bulky docs in `references/`
- [ ] `platforms:` declared explicitly
- [ ] `requires_toolsets:` / `requires_tools:` declared if needed
- [ ] **Privacy audit passed** — zero personal info in any published file
- [ ] **Personal values extracted** to `config.yaml` under `skills.config.*`
- [ ] **Skill not too personal to publish** — no relationship graphs, cron IDs, or personal schedules
- [ ] Flat structure: `skills/<name>/SKILL.md` (no category subdirs — Hub indexer is one-level-deep)
- [ ] `skills.sh.json` updated if category groupings changed
- [ ] 4 config-code separation validators pass
- [ ] `hermes skills tap add` + `hermes skills search <name>` finds the skill
- [ ] For GitHub push: `gh auth refresh -s workflow` before pushing workflow files
- [ ] Did NOT rebuild Hermes built-ins (skills check/update/audit/publish)