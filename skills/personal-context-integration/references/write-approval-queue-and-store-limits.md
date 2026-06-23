# Write-approval queue triage + memory store-limit consolidation

Use when the user asks to "approve the recommendations / pending memory / pending
skills" OR when `memory(action=...)` / `skill_manage(action=...)` returns
`"staged": true` (the `*.write_approval` gate is on). Covers two linked problems
that bite together: (1) the pending queue is bigger and messier than it looks, and
(2) the memory store has a hard char ceiling that forces consolidation, not just
appending.

## The write-approval queue is cross-session and accumulates

With `memory.write_approval` / `skills.write_approval` on, every staged
`memory(...)`/`skill_manage(...)` call writes a JSON record under:

```
$HERMES_HOME/pending/memory/<id>.json
$HERMES_HOME/pending/skills/<id>.json
```

These persist across sessions. A queue you expect to hold "the 2 things from this
chat" routinely holds **dozens** — most with `origin: background_review`
(auto-staged by the background curator in prior sessions), plus duplicates
(the same fact staged 2–3 times) and chains (`create` + `edit` + `patch` of the
same skill).

**Pitfall — never blind `approve all`.** It commits duplicates, conflicting
versions, and items the user never reviewed — exactly what the approval gate
exists to prevent. Triage first.

### Inspect before approving

Each record is JSON with `id`, `action`, `origin`, `summary`, and a `payload`
(the original tool args). Don't guess field names — dump the real structure:

```python
import json, glob
for f in sorted(glob.glob("memory/*.json")):       # or skills/*.json
    d = json.load(open(f)); p = d.get("payload", {})
    print(d["id"], d["action"], d.get("origin"), "::", d["summary"][:90])
    # payload carries: target/content/old_text (memory) or name/action/old_string/new_string/file_content (skills)
```

Group by theme, spot duplicates (same content staged twice), spot chains
(create→edit→patch on one skill collapse to final state), and separate
*this-session's* items from the prior-session backlog. Approve the tight subset
the user actually meant; reject obvious dups.

## Slash commands ↔ programmatic apply

The user-side `/memory pending|approve|reject <id>` and `/skills pending|approve|diff <id>`
slash commands dispatch through `hermes_cli/write_approval_commands.py`, which
calls the same primitives you can drive directly when you need to apply a precise
subset (the agent cannot type slash commands for the user):

```python
import sys; sys.path.insert(0, "/opt/hermes")
from tools import write_approval as wa
from tools.memory_tool import apply_memory_pending, MemoryStore
from tools.skill_manager_tool import apply_skill_pending
import json

store = MemoryStore()                          # reads HERMES_HOME automatically
rec = wa.get_pending(wa.MEMORY, "9bb82ae7")    # or wa.SKILLS
r = apply_memory_pending(rec["payload"], store)        # memory
# r = json.loads(apply_skill_pending(rec["payload"]))  # skills
if r.get("success"):
    wa.discard_pending(wa.MEMORY, rec["id"])   # remove from queue once applied
wa.discard_pending(wa.SKILLS, "<dup_id>")      # reject a duplicate outright
```

`wa.list_pending(sub)`, `wa.get_pending(sub, id)`, `wa.discard_pending(sub, id)`
are the building blocks; `wa.MEMORY` / `wa.SKILLS` are the subsystem constants.

**Pitfall — run with the gateway venv, not bare python3.** `tools.memory_tool`
imports `yaml` (and other deps) that only exist in the Hermes venv. Bare
`/usr/bin/python3` fails with `ModuleNotFoundError: No module named 'yaml'`.
Use `/opt/hermes/.venv/bin/python` (the interpreter the running gateway uses —
find it via `ps aux | grep gateway`). Always set `HERMES_HOME=/opt/data`.

## Memory store has a hard char ceiling — consolidate, don't just append

`MemoryStore` enforces limits (code defaults **MEMORY.md 2200, USER.md 1375**).
When near full, `apply_memory_pending` / `memory(add)` **refuses** with a message
like *"Adding this entry (656 chars) would exceed the limit"* and stages nothing.
Several queued items + a near-full store means most of them physically cannot land
without consolidation first.

**The ceiling is configurable, NOT mandatory.** It's a token-budget guardrail
(memory injects into the system prompt every turn; the code comments rate it at
~2.75 chars/token, so 2200 ≈ 800 tokens). The live values come from `config.yaml`
`memory.memory_char_limit` / `memory.user_char_limit`, read at agent init
(`agent/agent_init.py` → `MemoryStore(...)`), with the code constants as fallback.
So consolidation is one option; **raising the limit is an equally valid option**
when the user keeps fighting the ceiling.

- **Diagnose mandatory-vs-optional**: a config value that already differs from the
  code default (e.g. `user_char_limit: 2000` when the constant is `1375`) is proof
  it's tunable — someone already changed it.
- **Raise it** with the CLI (the patch/file tools REFUSE config edits — a security
  guard returns *"Refusing to write to Hermes config file… use 'hermes config'"*):

  ```bash
  HERMES_HOME=/opt/data /opt/hermes/bin/hermes config set memory.memory_char_limit 3000
  HERMES_HOME=/opt/data /opt/hermes/bin/hermes config set memory.user_char_limit 2400
  ```

  Back up `config.yaml` first; the change takes effect for new `MemoryStore`
  instances (next session) — no restart needed to verify, just re-instantiate.
- **Quantify the cost** before suggesting a bump: extra chars × (1/2.75) tokens,
  billed *every turn*, only for chars actually used (not the ceiling). A 2200→3000
  memory bump is ~+290 tokens/turn — negligible on a large-context model.
- Still **prefer routing operational detail to skills** over an ever-growing
  profile; raise the limit for genuine always-on steering facts, not as a way to
  avoid the route-to-skills discipline below.

### Measure-before-write consolidation loop

Editing the store files is **irreversible** — do it deliberately:

1. **Read current state** — print each file's size vs limit and list every entry
   with its char count (split on the `§` separator). This shows headroom and
   which existing entries are bloated/overlapping.
2. **Draft the consolidated file in a scratch script**, then *measure* total
   length **before** writing anything. Merge duplicates (e.g. two Docker-env
   notes → one), apply queued `replace`s, fold in genuinely-new facts, and trim
   overlap from existing entries the new ones subsume. Iterate the wording until
   `len(doc) <= limit` with a few chars of headroom. Expect several passes — it's
   normal to overshoot by 100–600 chars on the first draft.
3. **Route, don't drop.** The profile can't hold everything. Keep only *always-on
   steering* facts (identity, timezone, tone, formatting, core workflow prefs) in
   USER.md/MEMORY.md; push *operational* detail (a specific cron's house style, an
   event-tracking workflow, a locked-in message format) into the relevant **skill**
   `references/` instead of burning scarce profile chars. Tell the user exactly
   what was kept vs routed — never silently drop an approved fact.
4. **Show the exact final text of both files and get explicit approval**
   (the user's "exact diffs before saving" rule), then write **atomically with a
   timestamped `.bak`**:

   ```python
   import shutil, time, pathlib
   ts = time.strftime("%Y%m%d-%H%M%S")
   shutil.copy2(target, target.with_suffix(target.suffix + f".bak-{ts}"))
   tmp = target.with_suffix(".tmp"); tmp.write_text(new); tmp.replace(target)
   ```
5. **Verify reload** — re-instantiate `MemoryStore()` / re-read the files, confirm
   sizes are under limit and entry counts are sane (no parse errors), then drain
   the now-applied items from the queue with `wa.discard_pending`.

### Heredoc / shell pitfall

Scratch consolidation scripts contain text with `&&`, `→`, and trailing-`&`-looking
fragments. A `python - <<'PY'` heredoc can trip the terminal's "uses `&`
backgrounding" guard and abort. Write the scratch script with `write_file` and run
it as a file instead of piping a heredoc.

## Skill patches conflict across sessions — reconstruct, don't sequentially apply

The skills queue is worse than the memory queue: many staged `patch` records were
created in **different prior sessions, each diffed against the SAME original
SKILL.md**. So multiple patches carry the *same* `old_string` anchor (e.g. six
patches all anchored on the "Reference patterns:" list line, two on the same
pitfall line). They **cannot be applied sequentially** — the first apply changes
the anchor text, and every later patch against that anchor then fails to match.

Worse, `background_review` independently re-discovers the same lesson in separate
sessions, so 4–5 patches may each append a near-identical "subprocess dependency
false alarm" / "no boilerplate footers" / "bare-URL" block. Blind-applying stacks
**duplicate** sections and pitfalls.

**Technique — collapse to one reconstructed file:**

1. **Classify each queued item by `(name, action, file_path)`.** `write_file`
   records for *new* `references/`/`scripts/` files are additive and almost always
   safe to apply directly (no shared anchor). The `SKILL.md` `patch` records are
   the conflict-prone set.
2. **Dump every patch's full `old_string` + `new_string`** and group by anchor.
   Same anchor = conflict cluster; read all `new_string`s together and notice the
   redundancy (often the same lesson worded 3 ways).
3. **Hand-build the final SKILL.md once** in your editor/`write_file`: start from
   the current on-disk file, fold in each *distinct* addition, de-duplicate the
   repeated lessons into a single coherent section, renumber pitfall lists so
   there are no dup numbers. Then `discard_pending` all the superseded patch IDs
   (they're now represented in the rewrite) — don't `apply_skill_pending` them.
4. **For create→edit→patch chains on one skill**, only the final state matters.
   If the skill doesn't exist on disk yet, take the last `edit`/`create`'s full
   `content` as authoritative, write it, and discard the whole chain.
5. **Dedup near-identical new reference files.** Sessions sometimes stage
   `calendar-invites-as-reminders.md`, `calendar-event-creation-reminders.md`, and
   `calendar-events-as-reminders.md` — all the same lesson. Keep the most complete
   one; reject the others AND reject the SKILL.md ref-list patches that point at the
   rejected files (apply only the patch that references the kept file).

**Apply/reject by target file, in order:** apply the kept `write_file` first, then
the SKILL.md patch that references it; reject the dup files and the patches that
reference them. After a kept-file rename/choice, grep the SKILL.md to confirm zero
dangling references to a rejected file.

**`apply`/`create` "errors" that are actually already-done states:** a `create`
that returns *"already exists"* and a `delete` that returns *"not found in active
profile"* (skill already archived/absorbed) are both no-ops — verify the on-disk
reality, then just `discard_pending` the stale record. Don't treat them as failures.

**Verify with the skill harness, not by eye.** After reconstruction, run the
contract checker so dangling script/file refs and frontmatter-name/dir mismatches
surface:

```bash
HERMES_HOME=/opt/data /opt/hermes/.venv/bin/python skills/_testkit/skill_contract_check.py [skill-name...]
# and the test harness for skills that ship tests/:
HERMES_HOME=/opt/data /opt/hermes/.venv/bin/python skills/_testkit/run_skill_tests.py
```

A `name != dir` advisory is fixed by renaming the directory to match frontmatter
(`mv` the dir) once you've grepped that nothing references the old path. Doc-drift
(SKILL.md references a script that was never shipped, even upstream) is fixed by
rewriting the doc to the real working command — **verify the replacement command
actually exists before writing it** (e.g. confirm `pack.py` has no `--unpack` mode
before documenting it; a .pptx unpack is just `unzip`). Never paper over drift with
a second invented reference.

## Reporting

State: before/after sizes for each store, which queued items were applied vs
rejected-as-duplicate vs routed-to-a-skill vs collapsed-into-a-reconstruction,
that backups were written, that the stores reload cleanly, the contract check is
green, and the queue counts remaining. Offer the skill backlog (pending skill
writes) as a clearly separate next phase.
