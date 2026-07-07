# Skill Curation Watchdog Pattern

**Established:** 2026-06-25

## Pattern

A `no_agent` weekly cron script that reads skill usage stats (`.usage.json`),
identifies low-use agent-created skills and marketplace sync issues, and reports
actionable findings. Silent when all healthy — costs zero tokens on most runs.

## Schedule

```text
script: skill_curation_watch.py
no_agent: true
schedule: 0 9 * * 0  (weekly, Sundays 9am UTC)
deliver: origin
enabled_toolsets: [terminal, file]
```

## What it checks

1. **Agent-created skills with 0-2 uses** — review candidates for archival.
   Uses `created_by` in SKILL.md frontmatter to distinguish agent-created from
   bundled skills (bundled skills are never flagged — the curator won't touch
   them either).
2. **Broken references** — skills with missing SKILL.md files.
3. **Marketplace git sync** — checks if `hermes-skills-marketplace` repo has
   unpushed commits or uncommitted files. Reports if not synced to GitHub.
4. **Usage stats** — total tracked, used, never used counts.

## Relationship to built-in curator

Hermes has a built-in curator (`hermes curator`) that runs on a configurable
interval (default 168h = weekly). It handles:
- Marking skills stale after `stale_after_days` (default 30)
- Archiving skills after `archive_after_days` (default 90)
- Creating tar.gz backups before each run
- LLM-based consolidation (optional, off by default)

The built-in curator only touches **agent-created** skills (those with
`created_by: agent` in frontmatter). Bundled and hub-installed skills are off-limits.

This watchdog script is **complementary** — it reports findings the curator
doesn't surface (marketplace sync, broken refs, usage stats). It does NOT
mutate skills.

## Skill discovery function

```python
def find_skill_dir(name: str) -> Path | None:
    """Find skill directory by name, checking direct + category subdirs."""
    direct = SKILLS_DIR / name
    if direct.is_dir():
        return direct
    for cat_dir in SKILLS_DIR.iterdir():
        if cat_dir.is_dir() and not cat_dir.name.startswith(".") and not cat_dir.name.startswith("_"):
            candidate = cat_dir / name
            if candidate.is_dir():
                return candidate
    return None
```

This handles the naming convention where usage.json uses the frontmatter `name:`
field (e.g. `cron-llm-review-house-style`) but the directory is nested under a
category (e.g. `skills/devops/cron-llm-review-house-style/`).

## Files

- Script: `${HERMES_HOME}/scripts/skill_curation_watch.py`
- Usage stats: `/opt/data/skills/.usage.json` (maintained by Hermes curator)
- Curator state: `/opt/data/skills/.curator_state` (JSON, maintained by built-in curator)
- Marketplace repo: `/opt/data/hermes-skills-marketplace/` (git repo)

## Sample output (when findings exist)

```
🔧 **Weekly Skill Curation Report**

📦 **Agent-created skills for review** (2):
  • `email-utils (1 uses, agent-created)`
  • `research/scheduled-research-briefs (2 uses, agent-created)`

📊 **Stats**: 109 tracked, 65 used, 44 never used
```

## Verification

Ad-hoc verification covers:
1. Script exists and runs (exit 0)
2. Output contains expected sections (header, review section, stats)
3. No stdout contamination from sitecustomize
4. Built-in curator active (not paused, run_count > 0)
5. Marketplace repo clean (no uncommitted/unpushed files)
6. sitecustomize stdout fix holding