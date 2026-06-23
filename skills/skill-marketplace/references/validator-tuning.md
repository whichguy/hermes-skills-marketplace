# CI Validator Tuning — Lessons from Bulk Retrofit

Session-derived knowledge for maintaining the marketplace CI validators.
These patterns were discovered while retrofitting 81 skills in one pass.

## Validator Architecture

Five scripts in `scripts/`:
1. `validate_skill.py` — single-skill frontmatter + structure check
2. `validate_all_skills.py` — runs #1 on every skill in the repo
3. `check_config_separation.py` — scans scripts for hardcoded secrets
4. `check_index_sync.py` — verifies index.json matches actual skills
5. `scan_secrets.py` — scans all .py files for real token patterns
6. `scan_hardcoded_config.py` — scans SKILL.md prose for "replace X with..." instructions

## False-Positive Secret Detection

### Problem
Generic regex `(api_key|token|secret|password)\s*=\s*["'][^"']{12,}["']` matches:
- `ENV_API_KEY="COMFY_..._KEY"` — placeholder in docstring
- `export COMFY_CLOUD_API_KEY="***"` — placeholder in usage example
- `client = OpenAI(api_key=api_key, ...)` — variable self-reference in error message

### Fix
Only scan for real token formats:
```python
SECRET_PATTERNS = [
    (r'sk-[a-zA-Z0-9]{20,}', "OpenAI API key"),
    (r'ghp_[a-zA-Z0-9]{36,}', "GitHub personal access token"),
    (r'AIza[a-zA-Z0-9_-]{35}', "Google API key"),
    (r'xox[baprs]-[a-zA-Z0-9-]+', "Slack token"),
    (r'AKIA[0-9A-Z]{16}', "AWS access key"),
    (r'-----BEGIN (RSA |EC )?PRIVATE KEY-----', "Private key block"),
]
```

## BUILTIN_ENV — Env Vars That Don't Need Declaration

Scripts commonly reference Hermes built-in env vars that are injected at
runtime. These should NOT trigger the "undeclared env var" check:

```python
BUILTIN_ENV = {
    "HERMES_HOME",        # Hermes home directory
    "HERMES_SESSION_ID",  # Current session ID
    "HERMES_SKILL_DIR",   # Current skill's directory
    "HERMES_GWS_BIN",     # Google Workspace CLI binary path
    "PATH", "HOME", "USER",
}
```

## Advisory vs Hard-Fail Checks

| Check | Type | Rationale |
|-------|------|-----------|
| SKILL.md > 150k chars | Hard fail | Truly broken — context overflow |
| SKILL.md > 15k chars | Advisory | Many valid skills are 20-45k |
| No `metadata.hermes.config` | Advisory | Some skills have no user-tunable values |
| Description doesn't start "Use when..." | Advisory | Many valid Hermes skills use other prefixes |
| Missing `platforms:` | Hard fail | Critical for cross-platform compat |
| Missing `version`/`author`/`license` | Hard fail | Required for marketplace metadata |

## Allowed Subdirectories

Skills may contain these subdirectories:
```python
ALLOWED_SUBDIRS = {
    "scripts",     # executable code
    "templates",   # output format templates
    "references",  # documentation loaded on demand
    "assets",      # static resources (images, data files)
    "prompts",     # prompt templates (some skills use these)
    "tests",       # test files
    "examples",    # example files
    "evals",       # evaluation files (skill-creator pattern)
    "workflows",   # workflow definitions (comfyui)
    "shared",      # shared resources across sub-skills
    "agents",      # agent definitions (skill-creator pattern)
}
```

Hidden directories (`.pytest_cache`, `.git`) are skipped in the check.

## Prose Code-Block Exclusion

When scanning SKILL.md for "replace X with your..." instructions, exclude
content inside code blocks (` ``` ... ``` `) since those are examples
showing what NOT to do, not actual instructions:

```python
prose_content = re.sub(r'```[\s\S]*?```', '', content)
```

## Read-Only Bundled Skills

In-repo skills shipped with Hermes may have `-r--r--r--` permissions.
The `execute_code` sandbox cannot write to these. Fix:

```bash
chmod u+w /opt/data/skills/<category>/<skill>/SKILL.md
```

Then re-run the write from `execute_code`.

## Index Sync

The `.well-known/skills/index.json` must contain an entry for every skill
directory that contains a `SKILL.md`. The `check_index_sync.py` script:
1. Reads all skill names from `index.json`
2. Walks `skills/`, `community/`, and `skill-template/` for `SKILL.md` files
3. Reports skills missing from index and stale index entries

When adding a skill, always update index.json in the same commit.