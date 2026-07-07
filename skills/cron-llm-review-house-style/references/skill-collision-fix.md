# Skill Collision Fix — Full Recipe

## Symptom

Every LLM-driven cron job delivery starts with:
```
⚠️ Skill(s) not found and skipped: google-workspace, ask
```

The jobs still run, but every message is prefixed with this noisy warning.

## Root Cause (discovered Jul 2026)

`skill_view()` in `tools/skills_tool.py` searches all skill directories: the
local `SKILLS_DIR` (`/opt/data/skills/`) + any `external_dirs` from
`config.yaml`. When the same skill name exists in multiple directories, it
returns "Ambiguous skill name" and the cron scheduler prepends the warning.

**The specific cause in this deployment:** `skills.external_dirs` in
`config.yaml` pointed to `/opt/data/hermes-agent/skills/` — the upstream git
clone used for development. Hermes already syncs bundled skills from the
installed package (`/opt/hermes/skills/`) → the user skills dir
(`/opt/data/skills/`) via the `.bundled_manifest` mechanism. Adding the
hermes-agent git clone as an external_dir created duplicates for all 68
bundled skills that were already synced.

**How it was introduced:** The config change was added between June 28 and
July 3, 2026 (visible in git history of `config.yaml`). The June 28 backup
had only the marketplace path; the July 3 commit added
`/opt/data/hermes-agent/skills`.

**How it was discovered:** During a cron cleanup session, every LLM-driven
job showed the warning. Investigation traced through `get_bundled_skills_dir()`
(which resolves to `/opt/hermes/skills/` in the installed package, NOT the
git clone), the `.bundled_manifest` sync mechanism, and the `external_dirs`
config. The fix was removing the duplicate from `external_dirs`.

## How Hermes Skills Resolution Works

1. **Bundled skills** ship in `/opt/hermes/skills/` (the installed package)
2. On startup, `sync_skills()` copies bundled skills → `~/.hermes/skills/`
   (= `/opt/data/skills/`) using `.bundled_manifest` to track hashes
3. If a user modifies a bundled skill, the hash changes and sync skips it
4. **External dirs** (`skills.external_dirs` in config.yaml) are additional
   search paths scanned alongside SKILLS_DIR
5. `skill_view()` scans all_dirs = [SKILLS_DIR] + external_dirs, collecting
   ALL matches. If >1 match → "Ambiguous" → skill skipped
6. `get_bundled_skills_dir()` resolves to the installed package path
   (`/opt/hermes/skills/`), NOT the git clone (`/opt/data/hermes-agent/skills/`)

## Fixes (in order of preference)

### Fix 1: Remove the duplicate from external_dirs (simplest, root cause)

Remove `/opt/data/hermes-agent/skills` from `skills.external_dirs` in
`config.yaml`. The bundled skills are already synced to `/opt/data/skills/` —
the external_dir is redundant and creates ambiguity.

```yaml
# Before (broken — 68 duplicates)
skills:
  external_dirs:
    - /opt/data/hermes-skills-marketplace/skills
    - /opt/data/hermes-agent/skills       # ← REMOVE THIS

# After (fixed)
skills:
  external_dirs:
    - /opt/data/hermes-skills-marketplace/skills
```

**Belt-and-suspenders:** Rename `hermes-agent/skills/` → `hermes-agent/_skills/`
so it can never be accidentally re-added. The `_` prefix keeps it out of the
skill search path even if someone re-adds the parent directory.

### Fix 2: Category-prefixed names (workaround, no config change)

Use `category/skill-name` instead of bare `skill-name` when attaching skills
to cron jobs. The qualified name resolves unambiguously because `skill_view()`
searches `category/name` subdirectories directly.

```bash
# Before (ambiguous — exists in both /opt/data/skills/ and external_dirs)
hermes cron edit <id> --add-skill google-workspace

# After (unambiguous — resolves to /opt/data/skills/productivity/google-workspace/)
hermes cron edit <id> --add-skill productivity/google-workspace
```

This works for any skill with a collision:
- `google-workspace` → `productivity/google-workspace`
- `hermes-agent` → `autonomous-ai-agents/hermes-agent`
- `llm-wiki` → `research/llm-wiki`
- `personal-context-integration` → `productivity/personal-context-integration`
- `open-threads` → `productivity/open-threads`

### Fix 3: Monkeypatch hook — Prefer local skills on collision

For collisions that remain after Fix 1 and Fix 2, create a `gateway:startup`
hook that wraps `skill_view()`. On ambiguous-name error, retries with
`get_external_skills_dirs` temporarily returning `[]` so only the local
skills dir is searched. Full implementation in the hook directory.

## Verification

Test with skills that collide and skills that don't:

```python
# Should resolve from local (was ambiguous)
skill_view("google-workspace")   # → success, local copy
skill_view("hermes-agent")       # → success, local copy
skill_view("ask")                # → success, local copy

# Should still load from external_dir (only exists there)
skill_view("computer-use")       # → success, external copy
skill_view("dogfood")            # → success, external copy
```

**Cron verification:** force-run a single low-risk job (`hermes cron run <id>`,
wait for scheduler tick), then check `cron/output/<id>/<newest>.md` — confirm
no "Skill(s) not found" warning and all attached skills appear in the
`## Prompt` section.
