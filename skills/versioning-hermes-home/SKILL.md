---
name: versioning-hermes-home
description: 'Safely version a live HERMES_HOME to git/GitHub: fail-closed gitignore,
  secret gating, runtime-state exclusion, watchdog backup cron.'
version: 1.0.0
author: Hermes Agent
license: MIT
platforms:
- linux
- macos
metadata:
  hermes:
    tags:
    - hermes
    - git
    - github
    - backup
    - config-as-code
    - cron
    - security
    - devops
    category: devops
    related_skills:
    - github-auth
    - github-repo-management
    - script-first-cron-design
    config:
    - key: versioning-hermes-home.enabled
      description: Enable versioning-hermes-home skill behavior
      default: true
      prompt: Enable versioning-hermes-home skill?
---


# Versioning a live HERMES_HOME to git

Put a Hermes instance's customizations under version control and sync them to a
(private) GitHub repo — config, skills, wiki, cron jobs, scripts, memories —
**without ever leaking the secrets and private data that live in the same
directory.** Also covers a quiet daily backup cron.

`HERMES_HOME` (e.g. `~/.hermes` or `/opt/data`) is a minefield: `config.yaml`
sits right next to `.env`, `auth.json`, OAuth tokens, full session transcripts,
live databases, and personal memory. A naive `git add -A && push` leaks all of
it irreversibly. The whole skill is about doing this *safely*.

## When this activates

- "version / back up / sync my Hermes config to GitHub"
- "config-as-code for Hermes", "track my skills/wiki in git"
- "set up a repo for my Hermes setup under <user>"
- Any request to git-init a directory that is (or contains) `HERMES_HOME`

## The non-negotiable safety model: fail-closed gitignore

Never allow-list onto an open default. **Ignore everything, then explicitly
allow-list only safe paths.** A private repo is NOT a license to commit
credentials — private repos get forked, shared, or exposed via a leaked token.

```gitignore
# FAIL-CLOSED: ignore everything, then re-include safe paths.
/*

# --- Allow-listed (safe to version) ---
!/.gitignore
!/.gitattributes
!/README.md
!/config.yaml            # VERIFY no inline secrets first (see below)
!/SOUL.md
!/skills/
!/wiki/
!/scripts/
!/cron/
!/memories/              # MEMORY.md / USER.md — OK in a PRIVATE repo only
!/plans/
!/agent-hooks/

# --- Re-exclude churn / sensitive INSIDE allow-listed dirs ---
skills/.curator_backups/
skills/.archive/
skills/.usage.json
skills/.hub/             # skills hub cache — can be 25MB+, pure runtime
skills/**/__pycache__/
cron/*.bak*
cron/state/              # runtime tick state (next_run_at churns every run!)
cron/output/
memories/*.bak*
memories/*.lock
wiki/**/*.lock
scripts/**/__pycache__/
scripts/whatsapp-bridge/node_modules/

# --- NEVER (also caught by /* but listed for intent) ---
# .env .env.*  auth.json  google_*.json  google/  token.json client_secret
# channel_directory.json  whatsapp/  pairing/  state.db*  kanban.db*
# sessions/  logs/  *cache*  hermes-agent/  personal-context/
```

## Mandatory pre-push secret gate

After `git add -A`, **grep the staged file list** before any commit/push. This
is the last line of defense behind the gitignore:

```bash
git add -A
git diff --cached --name-only | grep -iE \
  '^\.env|auth\.json|google_.*\.json|^google/|state\.db|kanban\.db|channel_directory|^whatsapp/|^pairing/|^sessions/|^logs/|^personal-context/|token\.json|client_secret' \
  && echo "!!! LEAK — abort" || echo "CLEAN"
```

Verify the result on the REMOTE too (what actually landed), not just locally —
e.g. `gh api repos/<owner>/<repo>/git/trees/main?recursive=1 -q '.tree[].path'`
piped through the same grep.

## Workflow

1. **Recon read-only first.** `git --version`, is it already a repo, is `gh`
   present/authed. Inventory the dir; identify which subdirs are real
   customization vs. runtime state vs. secrets. See
   `references/hermes-home-layout.md` for the canonical classification.
2. **Verify config.yaml is clean.** It usually is (dummy `api_key: ollama`,
   empty `''`, Bitwarden refs an env var) — but grep it for real `tvly-`,
   `sk-`, `ghp_`, `gho_`, `AIza`, `xox[bp]-` values before allow-listing it.
3. **Handle embedded git repos.** A skill or vendored dir with its own `.git`
   triggers "adding embedded git repository" and commits as a broken submodule
   pointer. Fix: `git rm --cached -rf <path>; rm -rf <path>/.git; git add <path>`
   so it commits as plain files. Run `advice.addEmbeddedRepo false` to quiet it.
4. **Watch repo size.** Large caches (`skills/.hub/` ~25MB) bloat the repo —
   exclude them. Audit with `git diff --cached --name-only -z | xargs -0 du -h | sort -rh | head`.
   Also check for generated dependencies (`node_modules/`, `vendor/`) — these
   can add 50MB+ and should never be committed. If found tracked, see the
   "Generated dependencies" section below to exclude + purge + provide setup.sh.
5. **Check script portability.** Scripts in `scripts/` often hardcode
   `/opt/data` (the Docker HERMES_HOME default). Run
   `grep -rn '/opt/data' scripts/ --include='*.py' --include='*.sh'` and replace
   with `os.environ.get("HERMES_HOME", "/opt/data")` (Python) or
   `"${HERMES_HOME:-/opt/data}"` (shell). See "Script portability" section below.
6. **Build locally, show the manifest, get approval, THEN push.** A local
   `git init` is fully reversible (`rm -rf .git`). Never push without the user
   confirming the file manifest and which sensitive dirs stay excluded
   (`personal-context/` and `memories/` deserve an explicit yes/no).
7. **Auth** via `github-auth` (the curl device-flow + persist-to-hosts.yml is
   the reliable path in agent shells).
8. **Create + push:** `gh repo create <owner>/<repo> --private --source=. --remote=origin --push`.

## config.yaml is protected from the write/patch tools

The `patch`/`write_file` tools REFUSE to edit `config.yaml` and `.env`
("Write denied: protected system/credential file" / "Refusing to write to
Hermes config file"). This is deliberate. To change config use the CLI
(`hermes config set web.extract_backend tavily`) or edit via terminal/script;
to change `.env` use a terminal heredoc or a small python script. When `hermes`
isn't on PATH, find it (`/opt/hermes/bin/hermes`) and pass `HERMES_HOME`.

## Quiet daily backup cron (watchdog pattern)

Pair this with `script-first-cron-design`. Two scripts:
`scripts/git-sync/hermes-sync.sh` (the real sync, takes `--quiet`) and a thin
`hermes-sync-cron.sh` wrapper. Ship them via `scripts/git-sync/` and templates
in this skill: `templates/hermes-sync.sh` and `templates/hermes-sync-cron.sh`.

**Critical design point:** `cron/jobs.json` rewrites its `next_run_at` /
`last_run_at` timestamps on *every* scheduler tick. If the backup pings you on
success, it will fire **every single day** on meaningless timestamp churn. Use
the watchdog pattern instead — **silent on success, alert only on failure**:

```bash
out=$(/path/scripts/git-sync/hermes-sync.sh --quiet 2>&1); rc=$?
[ "$rc" -ne 0 ] && { echo "⚠️ Hermes GitHub backup FAILED (exit $rc):"; echo "$out"; exit "$rc"; }
exit 0   # success => empty stdout => no_agent cron stays silent
```

Register as `no_agent: true` (zero LLM cost). The cron `script` field needs a
path **relative to `$HERMES_HOME/scripts/`** and **cannot take inline args** —
hence the wrapper hardcodes `--quiet`.

## Generated dependencies (node_modules, vendor dirs)

Never commit generated dependencies (`node_modules/`, `vendor/`, `.venv/`).
They bloat the repo by 50MB+ and are regeneratable from a lockfile.

### Excluding from tracking

```gitignore
# In the fail-closed .gitignore, add INSIDE the allow-listed scripts/ dir:
scripts/whatsapp-bridge/node_modules/
```

Then remove from tracking (keeps files on disk):
```bash
git rm --cached -rq scripts/whatsapp-bridge/node_modules/
```

### Purging from git history

If node_modules was previously committed, `git rm --cached` stops tracking
but the blobs persist in history (49MB of loose objects in one real deployment).
Purge them:

```bash
# 1. Safety: backup branch
git branch backup-pre-rewrite

# 2. Stash any unstaged changes (filter-branch requires clean tree)
git stash

# 3. Rewrite all commits, removing the path from every tree
FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch --force --prune-empty \
  --index-filter 'git rm --cached -rq --ignore-unmatch "scripts/whatsapp-bridge/node_modules/" 2>/dev/null || true' \
  -- --all

# 4. Clear stashes (filter-branch corrupts them), expire reflog, gc
git stash clear
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# 5. Force-push rewritten history
git fetch origin
git push --force-with-lease origin main

# 6. Verify: repo size dropped, no node_modules in remote tree
git count-objects -vH   # 49MB → 19MB in real deployment
gh api repos/<owner>/<repo>/git/trees/main?recursive=1 -q '.tree[].path' | grep node_modules || echo CLEAN

# 7. Cleanup backup branch
git branch -D backup-pre-rewrite
```

### Fresh-clone setup script

When you exclude generated deps, you MUST provide a setup path. Add an
idempotent `setup.sh` at repo root (gitignore-allow-list it):

1. **Prerequisites check** — Docker, npm/node, etc. (clear error if missing)
2. **Create `.env` from template** — only if `.env` doesn't already exist; chmod 600
3. **Install generated deps** — `npm install --production` if `node_modules/` absent
4. **Secure sensitive files** — chmod 600 on `.env`, `auth.json`, `google_*.json`
5. **Print next steps** — edit .env → docker compose up → gateway setup → doctor

See `templates/setup.sh` for a ready-to-adapt template.

## Script portability (HERMES_HOME env var)

Scripts in `scripts/` often hardcode `/opt/data` (the Docker default for
HERMES_HOME). This breaks on any machine where HERMES_HOME differs. Make all
scripts portable:

```python
# BEFORE (hardcoded — breaks on non-Docker or different mount):
GOOGLE = Path('/opt/data/skills/productivity/google-workspace/scripts/google_api.py')
STATE_PATH = Path('/opt/data/cron/state/inbox_triage_seen.json')

# AFTER (portable — works with any HERMES_HOME):
HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
GOOGLE = HERMES_HOME / "skills/productivity/google-workspace/scripts/google_api.py"
STATE_PATH = HERMES_HOME / "cron/state/inbox_triage_seen.json"
```

For the hermes binary path itself:
```python
# BEFORE:
HERMES = "/opt/hermes/.venv/bin/hermes"
# AFTER:
HERMES = os.environ.get("HERMES_BIN", "/opt/hermes/.venv/bin/hermes")
```

For timezone in cron output scripts:
```python
# BEFORE:
LOCAL_TZ = ZoneInfo("America/Los_Angeles")
# AFTER:
LOCAL_TZ = ZoneInfo(os.environ.get("HERMES_TZ", "America/Los_Angeles"))
```

See `references/script-portability-pattern.md` for the complete env-var
convention table and the deep-audit methodology.
## Common gotchas when bulk-patching paths:

- String replacements on `Path('/opt/data/cron/state/X.json')` can produce
  `HERMES_HOME / "cron/state/"X.json')` — the closing `')` from the old literal
  stays attached. Always syntax-check with `py_compile` after patching.
- Scripts using `os.environ.get(...)` need `import os` — easy to forget when
  the script previously had no `os` dependency.
- Shell scripts: use `HERMES_HOME="${HERMES_HOME:-/opt/data}"` at the top.
- **Hardcoded binary paths:** `GIT = '/usr/bin/git'` breaks if git lives
  elsewhere. Use `shutil.which('git') or 'git'` (needs `import shutil`).
- **`/opt/hermes` for imports:** `sys.path.insert(0, "/opt/hermes")` (used
  by smoke tests to find Hermes source modules) should be
  `sys.path.insert(0, os.environ.get("HERMES_SOURCE", "/opt/hermes"))`.
  Same for shell: `BRIDGE_DIR="${HERMES_SOURCE:-/opt/hermes}/scripts/..."`.
- **Missing shebang in library modules:** Files imported by other scripts
  (e.g. `usaw_to_lib.py`) may lack `#!/usr/bin/env python3` — not a runtime
  issue when imported, but breaks if someone tries to run them directly.
  Add shebangs during the audit pass.
- **Timezone hardcoded in cron_style.py:** `LOCAL_TZ = ZoneInfo("America/Los_Angeles")`
  should be `ZoneInfo(os.environ.get("HERMES_TZ", "America/Los_Angeles"))` so
  deployments in other timezones get correct cron output.
- **config.yaml `host.docker.internal`:** Provider URLs use Docker's host bridge.
  Document in README that non-Docker deployments need `localhost` instead.
- **`cron_review_prompt.md` is frozen at creation:** Editing the shared style
  guide does NOT update existing cron jobs. Add a comment noting this, and use
  `cronjob action=update` to change live job prompts.
- **Undefined variables from prior patches:** Always read script logic flow
  after bulk path replacements — a variable renamed in one place (e.g.
  `wiki_path` to `root`) may still be referenced elsewhere. `py_compile` catches
  syntax errors but not `NameError` on undefined variables.

## Deep audit methodology

After the initial bulk patch, run a second-pass scan on **tracked files
only** (not `.bak*` files on disk — those are gitignored and don't travel
with the repo):

```bash
# Get tracked scripts only
git ls-files 'scripts/*.py' 'scripts/*.sh'

# Scan each for remaining hardcoded paths (exclude docstrings/comments)
grep -rn '/opt/data' scripts/ --include='*.py' --include='*.sh' \
  | grep -v '__pycache__\|node_modules\|\.pyc'

# For Python: syntax-check every modified file
for f in $(git ls-files 'scripts/*.py'); do
  python3 -c "import py_compile; py_compile.compile('$f', doraise=True)"
done

# For shell: syntax-check
for f in $(git ls-files 'scripts/*.sh'); do bash -n "$f"; done
```

A two-pass approach catches: (1) the obvious hardcoded paths in the first
grep, (2) missing `import os`, hardcoded binary paths (`/usr/bin/git`),
`/opt/hermes` for source imports, and missing shebangs in the deep scan.

## Pitfalls

- **Fail-open gitignore = leak.** Always `/*` then allow-list. Never the reverse.
- **`cron/state/` churns constantly.** Forgetting to exclude it makes the backup
  noisy and the tree never-clean. Untrack with `git rm -r --cached cron/state/`.
- **`cron_state/` (alternate state dir).** Some scripts write to `cron_state/`
  (no slash, different from `cron/state/`). Exclude both.
- **Generated deps committed historically.** `git rm --cached` stops tracking
  but doesn't shrink the repo — blobs persist in history. Use `filter-branch`
  + aggressive gc to actually reclaim space. See the "Purging from git history"
  section above.
- **No setup path after excluding deps.** Excluding `node_modules/` without
  providing a `setup.sh` means fresh clones are broken. Always pair exclusion
  with a setup script that regenerates the deps.
- **Cron prompts hardcode `/opt/data/wiki` and similar paths.** The precheck
  scripts use env vars (`$WIKI_PATH`, `$HERMES_HOME`), but the cron *prompts*
  (frozen at job creation) often contain hardcoded paths. After portability
  overhaul, update each wiki-related cron prompt via `cronjob action=update`
  to say "use $WIKI_PATH or $HERMES_HOME/wiki" instead of `/opt/data/wiki`.
  This is easy to miss because the scripts are already portable.
- **`memories/` and `personal-context/`.** memories/ is OK only in a *private*
  repo and only with the user's yes. personal-context/ mixes custom scripts with
  sensitive relationship data + `audit-log.jsonl` — default to EXCLUDE.
- **Nested `.gitignore` files override parent rules.** If a subdirectory has its
  own `.gitignore` (e.g. `ui-tui/.gitignore` with `dist/`), the root's
  `!/path/to/dist/` un-ignore is silently ignored — git uses the innermost
  applicable rule. Fix the nested file too. Also, the nested `.gitignore` itself
  may be ignored by the root `/*` pattern — add `!/path/to/.gitignore` to the
  root allow-list so it can be tracked and committed.
- **`gh` not on PATH / no sudo.** Install userspace: download the release tarball
  for the right arch and drop the binary in `~/bin` or `$HERMES_HOME/bin`. No root.
- **Don't trust "pushed" — verify the remote tree.** Re-run the secret grep
  against the actual pushed tree, confirm local HEAD == `origin/main`.
- **Token persistence:** see `github-auth` — persist to `hosts.yml`, not a bare
  env var, or the next session is logged out.

See `references/hermes-home-layout.md` for the full path-by-path keep/exclude map.
See `templates/setup.sh` for a fresh-clone onboarding script template.