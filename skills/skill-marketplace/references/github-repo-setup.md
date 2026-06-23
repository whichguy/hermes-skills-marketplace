# GitHub Repo Setup & Sync Infrastructure

Pattern for creating a dedicated GitHub marketplace repo with bidirectional
sync between local Hermes skills and the remote repo.

## Repo Creation

```bash
gh repo create <org>/<repo-name> --public --description "..."
```

Requires `gh` CLI with `repo` scope. For GitHub Actions workflow files,
the token also needs `workflow` scope:

```bash
gh auth refresh -h github.com -s workflow
```

Without `workflow` scope, `.github/workflows/*.yml` files are rejected on
push with: `refusing to allow an OAuth App to create or update workflow
without workflow scope`. Workaround: exclude the workflow file from the
initial commit, add it after refreshing auth.

## Git Identity

Fresh clones on Docker/container hosts may lack git identity:

```bash
GH_USER=$(gh api user --jq '.login')
GH_EMAIL=$(gh api user --jq '.email // "noreply@github.com"')
git config user.name "$GH_USER"
git config user.email "$GH_EMAIL"
```

## Sync Script Architecture

`sync_skills.sh` has four commands:

| Command | Direction | What it does |
|---------|-----------|-------------|
| `push` | local → GitHub | Copy tracked skills to repo, regen index, commit, push |
| `pull` | GitHub → local | Fetch + copy changed skills to `~/.hermes/skills/` |
| `check` | compare | Fetch + compare SHAs (exit 0=in sync, 1=drift) |
| `status` | display | Show SHA comparison + commit log + skill count |

Key design decisions:
- **Explicit skill list** in the script (SYNC_SKILLS array) — not a glob.
  Only custom skills are synced, not bundled Hermes skills.
- **Category map** (associative array) maps skill names to marketplace dirs.
- `find_local_skill()` searches by both directory name and frontmatter `name:`
  field, since they sometimes differ.
- `push` does `git pull --rebase` before committing to avoid conflicts.
- `pull` does `git fetch` + `git reset --hard` as fallback if rebase fails.

## Cron Integration

`check_updates.sh` is designed for `cronjob` with `no_agent=True`:
- Exits 0 silently when in sync (cron delivers nothing)
- Exits 1 with a summary when updates exist (cron delivers the text)
- Script must be in `~/.hermes/scripts/` for cron to find it

```bash
# Cron setup (done via Hermes cronjob tool)
cp /opt/data/hermes-skills-marketplace/scripts/check_updates.sh \
   ~/.hermes/scripts/marketplace-check-updates.sh
```

Schedule: every 6h is sufficient — the marketplace isn't a high-frequency
update target.

## Distinguishing Custom vs Bundled Skills

Before building the marketplace, determine which skills are custom (yours)
vs bundled (ship with Hermes):

1. Walk `/opt/data/hermes-agent/skills/` + `optional-skills/` — collect all
   bundled skill names from frontmatter.
2. Walk `~/.hermes/skills/` — collect local skill names.
3. Custom = local minus bundled.
4. Only custom skills go in the marketplace repo. Bundled skills are already
   available via `hermes skills install official/<name>`.

## Hermes Skills Tap

```bash
hermes skills tap add whichguy/hermes-skills-marketplace
hermes skills tap list
```

The tap registers the repo as a skill source. However, the Hermes hub
indexer may not immediately crawl the repo — `hermes skills search` might
not find skills from a freshly added tap until the indexer runs. Use the
sync scripts for immediate operations.

## File Layout

```
hermes-skills-marketplace/
├── .well-known/skills/index.json    # Discovery (hermes skills tap add)
├── .github/workflows/validate-skills.yml  # CI (needs workflow scope)
├── .github/PULL_REQUEST_TEMPLATE/skill-submission.md
├── scripts/
│   ├── sync_skills.sh               # Bidirectional sync (push/pull/check/status)
│   ├── check_updates.sh             # Cron-safe update checker
│   ├── generate_index.py            # Auto-generate index.json + CATALOG.md
│   ├── validate_skill.py            # Single-skill frontmatter validator
│   ├── validate_all_skills.py       # Batch validator
│   ├── check_config_separation.py   # No hardcoded secrets in scripts
│   ├── check_index_sync.py          # Index matches actual skills
│   ├── scan_secrets.py              # Real token format detection
│   └── scan_hardcoded_config.py     # No "replace this with..." in prose
├── skill-template/                  # Copy-and-go template
├── skills/<category>/<name>/        # The actual skills
├── community/                       # Community submissions (pre-review)
├── CONTRIBUTING.md
├── REVIEW.md
├── CATALOG.md                       # Auto-generated from index.json
└── README.md
```