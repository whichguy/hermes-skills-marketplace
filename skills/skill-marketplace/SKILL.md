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

## Design Principle: Scripted Support First

When building marketplace infrastructure or repeatable operations, prefer
**scripts over agent-driven approaches**. The user explicitly wants scripted
support maximized — cron jobs should be `no_agent=True` with script-only
output, sync operations should be shell scripts, and validation should be
automated Python that runs without an LLM in the loop.

Rationale: scripts are deterministic, fast, cheap, and don't consume tokens.
They run the same way every time. Agent loops are for reasoning, not for
mechanical repetition.

Apply this to:
- Update checks → `check_updates.sh` (cron-safe, silent on no-op)
- Skill syncing → `sync_skills.sh push/pull` (deterministic file copy + git)
- Index generation → `generate_index.py` (scan dirs, write JSON)
- CI validation → 5 Python scripts (exit codes, no LLM needed)
- The only agent-driven part is authoring/editing SKILL.md content itself

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

The marketplace repo is at `/opt/data/hermes-skills-marketplace/`. The template
is at `skill-template/` within it.

```bash
cp -r /opt/data/hermes-skills-marketplace/skill-template/ \
  /opt/data/hermes-skills-marketplace/skills/<category>/<skill-name>/
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

### Step 6 — Update the discovery index

Add your skill to `.well-known/skills/index.json` in the marketplace repo.

**Completion criterion:** `check_index_sync.py` passes.

### Step 7 — Validate

```bash
cd /opt/data/hermes-skills-marketplace
python scripts/validate_all_skills.py
python scripts/check_config_separation.py
python scripts/check_index_sync.py
python scripts/scan_secrets.py
python scripts/scan_hardcoded_config.py
```

**Completion criterion:** All 5 checks pass with zero errors.

### Step 8 — Publish

```bash
# Option A: Hermes CLI (publishes to GitHub directly)
hermes skills publish skills/<category>/<skill-name>/ --to github --repo <repo>

# Option B: Git PR (for curated marketplace)
git add skills/<category>/<skill-name>/
git add .well-known/skills/index.json
git commit -m "feat: add my-skill skill"
```

**Completion criterion:** Skill is pushed to GitHub or a PR is opened.

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

If the marketplace repo is cloned locally (e.g., by the sync script), mount
it directly as a skill source. No security scan, no rate limits.

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

### Option C — Sync Script (for the marketplace owner, bidirectional)

The sync script copies skills between local `~/.hermes/skills/` and the
marketplace GitHub repo. Best for the repo owner who wants to push changes.

```bash
# Push local skill changes to GitHub
/opt/data/hermes-skills-marketplace/scripts/sync_skills.sh push

# Pull marketplace updates to local
/opt/data/hermes-skills-marketplace/scripts/sync_skills.sh pull

# Check if in sync (cron-safe, silent on no-op)
/opt/data/hermes-skills-marketplace/scripts/check_updates.sh

# Show sync status
/opt/data/hermes-skills-marketplace/scripts/sync_skills.sh status
```

A cron job runs `check_updates.sh` every 6h and alerts when updates are
available.

### Which option to use?

| Situation | Option |
|-----------|--------|
| Other agents discovering your skills | A (Skills Hub tap) |
| Local development, no security scan | B (external_dirs) |
| Pushing your local changes to GitHub | C (sync script push) |
| Pulling marketplace updates to local | C (sync script pull) |
| Automated periodic update check | C (cron + check_updates.sh) |

## Procedure: Retrofitting a Single Skill

1. **Audit:** List every hardcoded value in SKILL.md prose and scripts/*.py
2. **Extract config:** Move each to `metadata.hermes.config` with a default
3. **Extract secrets:** Move API keys to `required_environment_variables`
4. **Rewrite scripts:** Substitute hardcoded values with `os.getenv()` calls
5. **Move bulky content:** API specs → `references/`, formats → `templates/`
6. **Clean SKILL.md:** Remove placeholder substitution instructions
7. **Validate:** Run all 5 CI checks
8. **Update index:** Add entry to `.well-known/skills/index.json`

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
`check_index_sync.py` reports in sync, zero failures.

## References

- `references/frontmatter-schema.md` — Complete frontmatter field reference with examples
- `references/claude-code-learnings.md` — Research from agentskills.io spec, Anthropic's skills repo, and community marketplaces
- `references/validator-tuning.md` — CI validator architecture, false-positive patterns, advisory vs hard-fail rules, BUILTIN_ENV set
- `references/github-repo-setup.md` — GitHub repo creation, git identity, sync script architecture, cron integration, custom vs bundled skill detection

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

5. **Forgetting to update index.json.** The `.well-known/skills/index.json`
   is how `hermes skills tap add` discovers skills.

6. **Using `skill_manage(action='create')` for marketplace skills.** That
   writes to `~/.hermes/skills/` (personal). Use `write_file` to the
   marketplace repo's `skills/<category>/<name>/SKILL.md` instead.

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

## Procedure: Syncing Skills with the Marketplace Repo

The marketplace repo is on GitHub at `whichguy/hermes-skills-marketplace`.
Scripts in `scripts/` handle all sync operations.

### Push local changes to GitHub
```bash
/opt/data/hermes-skills-marketplace/scripts/sync_skills.sh push
```

### Pull marketplace updates to local
```bash
/opt/data/hermes-skills-marketplace/scripts/sync_skills.sh pull
```

### Check for updates (cron-safe, silent on no-op)
```bash
/opt/data/hermes-skills-marketplace/scripts/check_updates.sh
```
Exits 0 silently if in sync. Exits 1 with summary if updates available.

### Show sync status
```bash
/opt/data/hermes-skills-marketplace/scripts/sync_skills.sh status
```

13. **GitHub Actions workflow files need `workflow` scope on the token.**
    `gh auth` with only `repo` scope can create repos and push code, but
    `.github/workflows/*.yml` files are rejected: `refusing to allow an OAuth
    App to create or update workflow without workflow scope`. Fix:
    `gh auth refresh -h github.com -s workflow` (requires interactive device
    code flow). Workaround: exclude workflow files from the initial commit,
    add them after refreshing auth.

14. **Hermes skills tap indexer may not immediately discover new repo
    skills.** `hermes skills tap add` registers the repo, but
    `hermes skills search` might not find skills from a freshly added tap
    until the hub indexer crawls it. Use the sync scripts
    (`sync_skills.sh pull`) for immediate skill installation instead of
    waiting for hub indexing.

## Verification Checklist

- [ ] All user-tunable values in `metadata.hermes.config`
- [ ] All API keys in `required_environment_variables`
- [ ] All OAuth tokens in `required_credential_files`
- [ ] Scripts read from `os.getenv()` — zero hardcoded user-tunable values
- [ ] No secrets in any file (scan_secrets.py passes — real tokens only, no placeholder false positives)
- [ ] No placeholder substitution instructions in prose
- [ ] SKILL.md ≤ 15k chars (advisory; 150k hard limit)
- [ ] Output formats in `templates/`
- [ ] Bulky docs in `references/`
- [ ] `platforms:` declared explicitly
- [ ] `requires_toolsets:` / `requires_tools:` declared if needed
- [ ] `.well-known/skills/index.json` updated (check_index_sync.py passes)
- [ ] All 5 CI checks pass
- [ ] For bulk retrofits: `chmod u+w` on read-only bundled skills before writing
- [ ] Validator BUILTIN_ENV set includes HERMES_HOME, HERMES_SESSION_ID, HERMES_SKILL_DIR, HERMES_GWS_BIN
- [ ] Secret scanner excludes placeholder patterns (..., ***, YOUR_, <...>, EXAMPLE)
- [ ] For GitHub push: `gh auth refresh -s workflow` before pushing workflow files
- [ ] For cron setup: copy scripts to `~/.hermes/scripts/` and use `no_agent=True`