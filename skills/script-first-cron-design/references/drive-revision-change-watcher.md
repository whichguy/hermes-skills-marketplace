# Drive-Backed Change Watcher + Snapshot-Driven Reminder Crons

Pattern for "remind me before each X, and re-check for changes every N during
the event, only notify on changes" against a Google Drive file (Sheet/`.xlsx`).
Two cooperating `no_agent` scripts plus a shared lib. Proven on the USAW TO
schedule (`.xlsx` in Drive) but generalizes to any Drive-hosted source of truth.

## Architecture: split reminder from change-detection

- **Reminder job** (frequent, e.g. every 15 min): reads a cached **snapshot**
  (local JSON), fires when `now` (in the user's TZ) reaches `anchor_time - lead`,
  dedupes so each item reminds exactly once. Never touches the network on a
  normal tick — pure local read. Silent unless something is due.
- **Change-watcher job** (e.g. hourly): cheap-first Drive poll, downloads + diffs
  only when the file actually changed, notifies on diffs **and rewrites the
  snapshot** so the reminder job auto-stays-correct. Silent otherwise.

The snapshot file is the contract between the two jobs.

## Cheap-first change detection (the optimization)

Do NOT re-download every tick. Use **one `revisions().list()` call** — it gives
you the change signal AND the full edit trail AND the editor name, all for the
cost of one API call:

```python
def drive_revisions(retries=10):
    """Returns list of {id, modifiedTime, modifiedBy} dicts, oldest-first."""
    resp = svc.revisions().list(
        fileId=FILE_ID,
        fields="revisions(id,modifiedTime,lastModifyingUser/displayName)",
        pageSize=1000,
    ).execute()
    revs = resp.get("revisions", [])
    return [
        {
            "id": r["id"],
            "modifiedTime": r["modifiedTime"],
            "modifiedBy": (r.get("lastModifyingUser") or {}).get("displayName") or "unknown",
        }
        for r in revs
    ]

def drive_head(retries=10):
    """Thin wrapper: (modifiedTime, revisionId, modifiedBy) for the latest revision."""
    revs = drive_revisions(retries=retries)
    latest = revs[-1]
    return latest["modifiedTime"], latest["id"], latest["modifiedBy"]

def revisions_since(all_revs, last_rev_id):
    """Slice of all_revs that came *after* last_rev_id (exclusive, oldest-first).
    Falls back to returning all_revs if last_rev_id is missing (pruned history)."""
    if not last_rev_id:
        return all_revs
    ids = [r["id"] for r in all_revs]
    if last_rev_id in ids:
        return all_revs[ids.index(last_rev_id) + 1:]
    return all_revs
```

> **Note (corrected):** `revisions().list()` works reliably for **binary `.xlsx`**
> files hosted in Drive — confirmed in production (Jun 2026). The full revision
> list, including `lastModifyingUser`, is returned. Empty `displayName` is possible
> for programmatic/system edits — guard with `or "unknown"`. The old advice to use
> `headRevisionId` from `files().get()` still works as a single-field cheap poll,
> but `revisions().list()` is strictly richer and costs the same one network round-trip.

**Always compare by `revisionId`, not `modifiedTime` alone** — store both but key
the change decision on `revisionId`. Time alone can be non-monotonic under some
Drive conditions.

## Always stamp `last_checked_at`, even on silent runs

State should record **when you last looked**, independent of whether the sheet
changed. This gives you a checkable audit trail and lets you tell the user "last
polled at 8:44 AM MT" even when nothing happened:

```python
state["last_checked_at"] = datetime.datetime.now(tz).isoformat()
save_state(state)
if no_change:
    return  # empty stdout AFTER saving state
```

Without this, "when did we last check?" is unanswerable from state alone.

## 3-Tier precheck-LLM architecture (recommended over pure no_agent)

For change-watchers that need human-readable output (Telegram alert), use three
tiers where the script does ALL deterministic work and the LLM is a **pure
formatter only**. LLM only fires when there is something real to format.

| Tier | Runs when | Cost |
|---|---|---|
| Script — rev check | Every tick | 1 API call, 0 tokens |
| Script — download + diff | Rev ID changed | Download + parse only |
| LLM — format | Watched rows changed | Tokens only when needed |

**Script contract:** emit a structured JSON payload when LLM input is needed;
emit nothing (empty stdout) otherwise. The scheduler skips the LLM entirely on
empty stdout — this is what makes the pattern cheap even at hourly cadence.

```python
# Script always stamps last_checked_at, then:
if no_change:
    return                          # empty stdout → LLM never fires

# Sheet changed — download, diff, check if watched rows affected
if not (added or removed or retimed):
    return                          # empty stdout → LLM still silent

# Only here: emit structured JSON for LLM to format
payload = {
    "last_checked_at":  "Jun 19 7:00 AM MT",
    "checked_at":       "Jun 19 8:44 AM MT",
    "revision_count":   3,
    "revision_trail":   [{"when": "Jun 13 10:20 AM MT", "by": "jodi.stumbo"}, ...],
    "diff": {"added": [...], "removed": [...], "retimed": [...]},
    "sheet_url":        "https://...",
}
print(json.dumps(payload, indent=2))
```

**LLM prompt:** tell it explicitly it is a **formatter only** — data is already
correct, it just renders to Telegram Markdown with the house style. Include the
`[SILENT]` rule. This prevents editorializing and keeps token use minimal.

### Flipping an existing no_agent job to precheck-LLM mode

The `cronjob` tool `action=update` does NOT expose a `no_agent` toggle. Flip it
directly in `/opt/data/cron/jobs.json` (key is `"id"`, not `"job_id"`):

```python
import json
path = '/opt/data/cron/jobs.json'
data = json.loads(open(path).read())
job = next(j for j in data['jobs'] if j['id'] == '<job_id>')
job['no_agent'] = False
open(path,'w').write(json.dumps(data, indent=2))
```

Then update the prompt via `cronjob action=update`. The `cronjob list` API
returns `job_id` but the JSON file uses `id` — they are the same value,
different key names. Verify after writing that `no_agent` is absent/False in
the list output.

## Diff shape: added / removed / retimed

Build a stable key per watched item (e.g.
`person|date|session|platform|role`), map old vs new snapshot, then report:
`added` (key in new not old), `removed` (old not new), and `retimed` (same key,
changed time/category fields). Only emit when a watched entity is affected —
an edit elsewhere in the file stays silent.

## Reminder anchor: confirm with the user explicitly

"2 hours before" is ambiguous when an item has multiple times (e.g. weigh-in
vs session start). Ask which it anchors to and hardcode the choice with a dated
comment. (USAW: anchor = **2h before session START**, per user 2026-06-18 —
note this superseded an earlier "2h before weigh-in" answer, so expect the user
to refine the anchor; keep it a single well-commented constant, easy to flip.)

## Self-silencing event window

Gate both `main()`s on an `in_event_window()` date check (a few days padding
around the event). Lets you leave the jobs scheduled without firing or polling
before/after the event — no manual pause/disable needed.

```python
EVENT_START = date(2026, 6, 19); EVENT_END = date(2026, 6, 29)
def in_event_window(): return EVENT_START <= now_tz().date() <= EVENT_END
```

## Dependency guard: uv re-exec (no pip in this env)

When a `no_agent` script imports libs the bare interpreter lacks
(`googleapiclient`, `openpyxl`, …), re-exec the script under `uv run --with ...`
once, guarded by an env flag to avoid a loop:

```python
def ensure_deps():
    import importlib.util, os, sys
    need = {"googleapiclient":"google-api-python-client",
            "google_auth_oauthlib":"google-auth-oauthlib", "openpyxl":"openpyxl"}
    missing = [p for m,p in need.items() if importlib.util.find_spec(m) is None]
    if missing and os.environ.get("UV_REEXEC") != "1":
        os.environ["UV_REEXEC"] = "1"
        os.execvp("uv", ["uv","run","--quiet",
                         *sum((["--with",p] for p in [
                            "google-api-python-client","google-auth-oauthlib",
                            "google-auth-httplib2","openpyxl"]), []),
                         "python", os.path.abspath(sys.argv[0]), *sys.argv[1:]])
```

This is the same "subprocess must use the target's dep env" rule as the main
SKILL pitfall, applied to the script's *own* imports rather than a child call.

## Reusing the google-workspace credentials directly

The `google_api.py` wrapper exposes `set_current_account(None)` +
`build_service(api, version)`. Import it for raw Drive calls the CLI doesn't
cover (revisions, `get_media` download, `headRevisionId`):

```python
sys.path.insert(0, str(HERMES_HOME/"skills/productivity/google-workspace/scripts"))
import google_api as G; G.set_current_account(None)
svc = G.build_service("drive","v3")
```

Wrap every Drive call in retry-with-backoff (user asked for up to 10 attempts,
exponential) so a transient 429/500 self-heals instead of false-alarming.

## Testing the firing path before scheduling

A reminder/watcher that's silent today proves nothing. Validate the *fire* path
by monkeypatching "now":

```python
class FakeDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None): return fake_now   # = anchor - lead + 1 min
ReminderModule.datetime.datetime = FakeDateTime
ReminderModule.main()   # expect the message
ReminderModule.main()   # expect SILENT (dedupe)
```

Run it from a real file (not heredoc stdin) so the uv-reexec guard can resolve
`argv[0]` — under `python - <<EOF`, `argv[0]` is `-` and the re-exec fails with
`can't open file '-'`. Reset the dedupe/state file afterward so production
starts clean.

## Cell-level diff engine (richer than high-level object diff)

When the parsed high-level diff (e.g. added/removed/retimed assignments) is not
enough — e.g. you want to know *which specific cell changed* and *who made it*
— go one level deeper: download the two xlsx revisions and compare their raw
cell grids. This is how you distinguish a row-shift (structural, noise) from a
genuine name swap (signal).

### Core helpers (add to your shared lib)

```python
def _norm_cell(v):
    """Normalise any cell value to a plain string."""
    if v is None: return ""
    if isinstance(v, datetime.datetime): return v.isoformat()
    if isinstance(v, datetime.time): return v.strftime("%H:%M")
    if isinstance(v, datetime.date): return v.isoformat()
    return re.sub(r"\s+", " ", str(v)).strip()

def _sheet_cells(xlsx_path, tab):
    """Return {(row, col): value_str} for every non-empty cell in the tab.
    Returns {} if the tab doesn't exist in this revision (e.g. tab was added
    mid-project — early revisions won't have it)."""
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    if tab not in wb.sheetnames:
        return {}
    ws = wb[tab]
    return {(r, c): _norm_cell(ws.cell(r, c).value)
            for r in range(1, ws.max_row + 1)
            for c in range(1, ws.max_column + 1)
            if _norm_cell(ws.cell(r, c).value)}

def _build_row_context(cells, max_row):
    """Map each row → nearest session anchor above it (session/platform/day/times).
    Works on raw cell dict so context is computable for ANY row, not just
    rows that matched a watched name."""
    cur_day = cur_sess = None
    anchors = {}
    for r in range(1, max_row + 1):
        a = cells.get((r, 1), "")
        if isinstance(a, str) and re.search(r"DAY,", a):
            cur_day = _parse_day(a); continue
        try: cur_sess = int(float(a))
        except (ValueError, TypeError): pass
        if cells.get((r, 2), "") in ("RED", "WHITE", "BLUE"):
            anchors[r] = dict(sess=cur_sess, plat=cells.get((r,2),""),
                              day=cur_day, gndr=cells.get((r,5),""),
                              cat=cells.get((r,6),""), win=cells.get((r,4),""),
                              start=cells.get((r+1,4),""))
    row_ctx = {}
    for r in range(1, max_row + 1):
        for rr in range(r, max(r - 10, 0), -1):
            if rr in anchors: row_ctx[r] = anchors[rr]; break
    return row_ctx

def diff_xlsx_for_watched(old_path, new_path, names, role_cols, tab):
    """Cell-level diff filtered to watched names in role columns.
    Returns list of {action: added|removed|replaced, role, old_name, new_name,
    row, context}.
    Structural row-shifts where neither old nor new contains a watched name
    are automatically ignored."""
    old_cells = _sheet_cells(old_path, tab)
    new_cells = _sheet_cells(new_path, tab)
    if not new_cells: return []
    max_row = max((max(r for r,_ in old_cells) if old_cells else 0),
                  (max(r for r,_ in new_cells) if new_cells else 0))
    new_ctx = _build_row_context(new_cells, max_row)
    old_ctx = _build_row_context(old_cells, max_row) if old_cells else {}
    name_match = lambda v: any(n.lower() in v.lower() for n in names)
    changes = []
    for r in sorted(set(r for r,_ in old_cells.keys()|new_cells.keys())):
        for col, role in role_cols.items():
            old_v = old_cells.get((r,col),""); new_v = new_cells.get((r,col),"")
            if old_v == new_v or not (name_match(old_v) or name_match(new_v)):
                continue
            ctx = new_ctx.get(r) or old_ctx.get(r) or {}
            action = "replaced" if old_v and new_v else ("removed" if old_v else "added")
            changes.append(dict(action=action, role=role,
                                old_name=old_v or None, new_name=new_v or None,
                                row=r, context=ctx))
    return changes
```

### Classifying raw cell changes into logical events

After `diff_xlsx_for_watched`, collapse into human-readable events.
**Attach `changed_by` and `changed_at` per event** — not just per revision group —
so the LLM can reference the editor on any individual line without needing to
look up a parent:

```python
def classify_cell_changes(raw_changes, names, changed_by="unknown", changed_at=""):
    """Returns list of {person, event, role, context, old_name, new_name,
    changed_by, changed_at}. event ∈ assigned|removed|swapped_in|swapped_out|tag_updated."""
    events = []
    for ch in raw_changes:
        old_n = ch.get("old_name") or ""; new_n = ch.get("new_name") or ""
        base = dict(role=ch["role"], context=ch["context"],
                    changed_by=changed_by, changed_at=changed_at)
        for watched in names:
            in_old = watched.lower() in old_n.lower()
            in_new = watched.lower() in new_n.lower()
            if not (in_old or in_new): continue
            if ch["action"] == "added":
                events.append(dict(person=watched, event="assigned",
                                   old_name=None, new_name=new_n, **base))
            elif ch["action"] == "removed":
                events.append(dict(person=watched, event="removed",
                                   old_name=old_n, new_name=None, **base))
            elif ch["action"] == "replaced":
                if in_old and not in_new:
                    events.append(dict(person=watched, event="swapped_out",
                                       old_name=old_n, new_name=new_n, **base))
                elif in_new and not in_old:
                    events.append(dict(person=watched, event="swapped_in",
                                       old_name=old_n, new_name=new_n, **base))
                else:
                    events.append(dict(person=watched, event="tag_updated",
                                       old_name=old_n, new_name=new_n, **base))
    return events
```

### Per-revision download walk (multi-revision gap handling)

When multiple revisions happened between cron ticks, walk them in pairs so you
catch every intermediate edit, not just the net result:

```python
with tempfile.TemporaryDirectory() as tmp:
    old_path = None
    # If only 1 new revision and current xlsx already on disk, use it as baseline.
    if len(new_revs) == 1 and prev_rev_idx is not None and XLSX_PATH.exists():
        old_path = XLSX_PATH
    elif prev_rev_idx is not None:
        old_path = Path(tmp) / "rev_base.xlsx"
        drive_download_revision(all_revs[prev_rev_idx]["id"], old_path)

    for i, rev in enumerate(new_revs):
        new_path = Path(tmp) / f"rev_{i}.xlsx"
        drive_download_revision(rev["id"], new_path)
        if old_path and old_path.exists():
            raw = diff_xlsx_for_watched(old_path, new_path, ...)
            events = classify_cell_changes(raw,
                         changed_by=rev["modifiedBy"],
                         changed_at=mt_fmt(rev["modifiedTime"]))
            if events:
                all_events.append({"revision": {...}, "events": events})
        old_path = new_path  # chain: this rev becomes the next "before"

    # Always end by downloading latest as the on-disk current file
    drive_download_revision(latest["id"], XLSX_PATH)
```

**`drive_download_revision` helper:**

```python
def drive_download_revision(rev_id, dest_path, retries=10):
    import time, io
    from googleapiclient.http import MediaIoBaseDownload
    svc = _gapi().build_service("drive", "v3")
    last = None
    for n in range(retries):
        try:
            req = svc.revisions().get_media(fileId=FILE_ID, revisionId=rev_id)
            buf = io.BytesIO(); dl = MediaIoBaseDownload(buf, req)
            done = False
            while not done: _, done = dl.next_chunk()
            Path(dest_path).write_bytes(buf.getvalue()); return Path(dest_path)
        except Exception as e: last = e; time.sleep(min(2**n, 60))
    raise RuntimeError(f"drive_download_revision failed: {last}")
```

### Pitfalls specific to cell-level diff

- **Tab may not exist in early revisions.** A tab added mid-project (e.g. `2026 NCW`
  was absent in the Feb 9 revision of the USAW xlsx, added later) means
  `_sheet_cells` returns `{}` for the old path — handle this by treating it as
  "no baseline" (all new cells are additions). Check `if tab not in wb.sheetnames`.
- **1730 changed cells ≠ 1730 real changes.** A bulk row-insert shifts every
  subsequent row's position, generating hundreds of `replaced` events where
  *neither* old nor new contains a watched name. The `name_match` filter in
  `diff_xlsx_for_watched` eliminates all of these automatically.
- **`modifiedBy` is empty string (not None) for programmatic/system edits.**
  Guard with `or "unknown"` at extraction time AND display as "system edit" to
  the user — do not display an empty string.
- **Row context lookup: use a search window of ~10 rows.** Session anchors
  (platform header rows) are typically within 3–4 rows above the name cell,
  but merged rows and blank separators can push this out. A window of 10 is safe.

## Scope signal — "targeted edit" vs "broad reshuffle"

After downloading a revision pair, compute how many total role-column cells
changed vs how many contained a watched name. This context is critical:
a `swapped_out` in a 743-cell reshuffle means the whole schedule was rebuilt;
a `swapped_out` in a 3-cell patch means someone specifically targeted that row.

```python
def scope_signal(old_path, new_path, tab, role_cols, watched_names):
    """Returns {total_role_changes, watched_changes, size_delta_bytes,
    label: 'targeted'|'broad reshuffle', ratio_pct}."""
    old_cells = _sheet_cells(old_path, tab)
    new_cells  = _sheet_cells(new_path, tab)
    all_rows   = set(r for r,_ in (old_cells.keys() | new_cells.keys()))
    total = watched = 0
    lc_names = [n.lower() for n in watched_names]

    def has_watched(v): return any(n in v.lower() for n in lc_names)

    for r in sorted(all_rows):
        for col in role_cols:
            ov = old_cells.get((r,col),""); nv = new_cells.get((r,col),"")
            if ov == nv: continue
            total += 1
            if has_watched(ov) or has_watched(nv): watched += 1

    size_delta = Path(new_path).stat().st_size - Path(old_path).stat().st_size
    ratio_pct  = round(watched / total * 100) if total else 0
    return {
        "total_role_changes": total,
        "watched_changes":    watched,
        "size_delta_bytes":   size_delta,
        "label":              "targeted" if (total==0 or ratio_pct>=25) else "broad reshuffle",
        "ratio_pct":          ratio_pct,
    }
```

**Threshold:** ≥25% of role-column changes touch a watched name → `"targeted"`.
Below that → `"broad reshuffle"`. Tune the threshold to taste, but 25% works
well empirically — a full schedule rebuild produces <5% watched-name hits.

**Size delta hint for the LLM:** `+41,817 bytes` = full tab addition (rebuild);
`+204 bytes` = surgical patch. Include in the alert: `_(broad reshuffle — 743 role cells, +41 KB)_`.

Attach `scope` at the **revision group level** (one scope per revision pair),
not per event. Add it to the JSON payload alongside `events`.

## Session urgency — how soon is the affected session?

Compute urgency from `context.date` + `context.start` vs `now_mt`. Attach
**per event** (different sessions have different urgency). The LLM uses the
icon to visually triage: a `swapped_out` with 🔴 is an emergency; with ⚪ it's
informational.

```python
def session_urgency(date_str, start_str, now_mt):
    """Returns {label, icon, hours_until}.
    date_str: ISO '2026-06-21' or formatted 'Sat Jun 21'.
    start_str: 'HH:MM' string from context.
    """
    if not date_str or not start_str:
        return {"label": "unknown", "icon": "⚪", "hours_until": None}
    try:
        tz = now_mt.tzinfo
        try:
            d = datetime.date.fromisoformat(date_str)
        except ValueError:
            import time as _t
            d = datetime.date(*_t.strptime(date_str, "%a %b %d")[:3])
            d = d.replace(year=now_mt.year)
        hh, mm    = map(int, start_str.split(":"))
        session_dt = datetime.datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
        delta_h    = (session_dt - now_mt).total_seconds() / 3600
        today, s_date = now_mt.date(), session_dt.date()

        if   delta_h < 0.5:                             return {"label":"NOW",       "icon":"🔴","hours_until":round(delta_h,1)}
        elif delta_h < 2:                               return {"label":"<2h",       "icon":"🔴","hours_until":round(delta_h,1)}
        elif delta_h < 6:                               return {"label":"<6h",       "icon":"🟡","hours_until":round(delta_h,1)}
        elif s_date == today:                           return {"label":"today",     "icon":"🟡","hours_until":round(delta_h,1)}
        elif s_date == today+datetime.timedelta(days=1):return {"label":"tomorrow",  "icon":"🟢","hours_until":round(delta_h,1)}
        else:
            return {"label":f"in {(s_date-today).days}d","icon":"⚪","hours_until":round(delta_h,1)}
    except Exception:
        return {"label": "unknown", "icon": "⚪", "hours_until": None}
```

**LLM urgency rule:** `NOW` or `<2h` → **bold the entire bullet**. `<6h` or `today` → prefix with `⚠️`. This ensures truly urgent changes are unmissable even in a long alert.

## Drive Revisions API — available fields and which to surface

Full field list from `revisions().list(fileId=..., fields="revisions")`:

| Field | Example | Surface to user? |
|---|---|---|
| `id` | `0B_UOfg…` | Use as change key — yes (internally) |
| `modifiedTime` | `2026-06-13T16:20:50.740Z` | ✅ yes — formatted as MT |
| `lastModifyingUser.displayName` | `jodi.stumbo` | ✅ yes — the "who" |
| `size` | `326490` | ✅ yes — compute delta for scope hint |
| `keepForever` | `true` | ✅ yes — show 📌 if set (signals "official baseline" |
| `originalFilename` | `2026 - VWS1 - TO Sign-up Sheet.xlsx` | ❌ no — always same |
| `md5Checksum` | `eaf74b93…` | ❌ no — rev ID is the change signal |
| `published` | `false` | ❌ no — always false for xlsx |
| `mimeType` | `application/vnd…` | ❌ no |

**`modifiedBy` is empty string (not None) for programmatic/system edits** — always
guard with `or "unknown"` and display to user as "system edit".

**`keepForever=True`** on a revision means someone pinned it in Drive as a named
version. For a meet schedule, this signals "this is the official baseline" or
a deliberate milestone checkpoint. Worth a 📌 in the alert but rare.

## Attach `changed_by`/`changed_at` per event, not just per revision group

When building events from a revision, embed `changed_by` and `changed_at`
directly in each event dict — don't only store it at the revision-group level:

```python
base = dict(role=role, context=ctx,
            changed_by=changed_by, changed_at=changed_at,
            urgency=session_urgency(ctx.get("date"), ctx.get("start"), now_mt))
events.append(dict(person=watched, event="assigned", old_name=None, new_name=new_n, **base))
```

This matters when the LLM formats individual bullets: it can write
_"swapped out by jodi.stumbo"_ per line without needing to look up which
revision group the event belongs to. Keeps the JSON self-contained at the
event level.

## Pitfall: blank row between W.In and Start rows (session 24 RED pattern)

Most session anchor rows have Start time at `anchor_row + 1` (col 4). But
occasionally a **blank separator row** sits between the W.In row and the Start
row (confirmed in 2026 NCW session 24 RED: W.In at R244, blank at R245,
Start at R246). Using `cells.get((r+1, 4))` returns empty string.

**Fix:** scan forward up to 3 rows, preferring the row where col 3 label starts
with "Start":

```python
start_val = ""
for offset in range(1, 4):
    candidate = cells.get((r + offset, 4), "")
    label     = cells.get((r + offset, 3), "")
    if candidate and str(label).strip().lower().startswith("start"):
        start_val = candidate
        break
    if candidate and not start_val:
        start_val = candidate  # fallback: first non-empty C4 below
```

Without this fix, urgency computation for affected sessions returns `"unknown"`
with `None` hours_until, making the 🔴/🟡/🟢 icons useless.

## Actor-centric alert phrasing (user preference)

When alerts describe schedule changes made by a named editor, phrase every line as:

> **`<actor> did <action> to <affected person>`**

Never reverse this to person-centric ("James Wiese was removed by…"). The actor-first
structure makes it immediately clear who is responsible, then what they did, then who
is affected — which is the most actionable reading order.

Pattern map:

| `event` | Sentence |
|---|---|
| `assigned` | `<changed_by> added 🟦/🟪 <person> as <Role> · <context>` |
| `removed` | `<changed_by> removed 🟦/🟪 <person> from <Role> · <context>` |
| `swapped_out` | `<changed_by> replaced 🟦/🟪 <person> with <new_name> in <Role> · <context>` |
| `swapped_in` | `<changed_by> moved 🟦/🟪 <person> into <Role>, replacing <old_name> · <context>` |
| `tag_updated` | `<changed_by> updated 🟦/🟪 <person>'s tag in <Role>: <old_name> → <new_name>` |

Strip credential tags from replacement names ("Les Simonton (IWF 1)" → "Les Simonton").
Use "system" when `changed_by` is "unknown". Append urgency icon + label at end of each line.
**Bold** the entire line when urgency is NOW or <2h. Prefix `⚠️` when <6h or today.

## CRITICAL: `revisions_since()` pruning bug — Drive drops old revision IDs

Drive retains only a limited number of revisions per file and **prunes the oldest
ones over time**. If the anchor `revisionId` stored in state is pruned, it will
no longer appear in `revisions().list()`.

**Wrong behavior (original fallback):** `revisions_since()` returning the full
list when the anchor is not found — this replays the entire history from the
oldest surviving revision as "new", flooding the user with stale alerts.

**Confirmed incident (Jun 19 2026):** After a Hermes container restart the state
file was re-seeded to an intermediate revision ID. By the next cron tick, Drive
had pruned that revision and `revisions_since` fell back to all 3 revisions,
causing 36 stale assignment events to fire.

**Correct fallback:** When the anchor is not found, return only the **latest**
revision (not all), and use the **on-disk snapshot xlsx** as the baseline for
the diff (not the pruned revision). The snapshot is always the correct prior
state regardless of Drive's revision history:

```python
def revisions_since(all_revs, last_rev_id):
    """Returns (revs, pruned: bool).
    If anchor pruned: returns only the latest revision + pruned=True.
    Caller should use on-disk snapshot xlsx as baseline when pruned=True.
    """
    if not last_rev_id:
        return all_revs, False
    ids = [r["id"] for r in all_revs]
    if last_rev_id in ids:
        return all_revs[ids.index(last_rev_id) + 1:], False
    return all_revs[-1:], True   # anchor pruned → only latest, signal the caller
```

In the watcher's `main()`, handle the `pruned` flag:

```python
new_revs, anchor_pruned = L.revisions_since(all_revs, state.get("revisionId"))

if anchor_pruned and L.XLSX_PATH.exists():
    old_path = L.XLSX_PATH   # snapshot on disk IS the correct prior state
elif prev_rev_idx is not None and L.XLSX_PATH.exists() and len(new_revs) == 1:
    old_path = L.XLSX_PATH   # optimise: single new rev, already have old on disk
elif prev_rev_idx is not None:
    old_path = Path(tmp) / "rev_base.xlsx"
    drive_download_revision(all_revs[prev_rev_idx]["id"], old_path)
else:
    old_path = None
```

## CRITICAL: always test against isolated /tmp state dirs, never the live dir

When manually running a precheck script to test behavior, **always** override the state
dir with a temporary path:

```bash
USAW_STATE_DIR=/tmp/usaw_test python usaw_to_change_watch.py
```

Running the script against the live state dir — even once — advances `revisionId`/
`last_seen` and can corrupt the baseline. The next real cron tick then treats all
historical data since that anchor as "new" and floods the user with stale alerts.

**Incident (Jun 19 2026):** `rm -f /opt/data/cron_state/usaw_to/last_revision.json`
to test baseline establishment caused the next real cron run to replay all 36 Jun 13
assignments as new alerts delivered to Telegram.

**Re-seeding after corruption:** run the script once against the live dir with the
current latest revision pre-loaded in state, or directly write the latest rev ID:

```python
import json, datetime, sys
sys.path.insert(0, "/opt/data/scripts")
import usaw_to_lib as L
revs = L.drive_revisions()
latest = revs[-1]
state = {
    "revisionId":      latest["id"],
    "modifiedTime":    latest["modifiedTime"],
    "modifiedBy":      latest["modifiedBy"],
    "last_checked_at": datetime.datetime.now(L.mt_tz()).isoformat(),
}
(L.STATE_DIR / "last_revision.json").write_text(json.dumps(state, indent=2))
```

Then verify the next run produces empty stdout (no spurious alert).

## All-names diff + direct no_agent formatter (no LLM needed)

When the output is fully deterministic — one line per cell change, no synthesis — skip the LLM entirely and have the script print the final message directly as a `no_agent` job.

**When to use:** change alerts where every change line has the same structure (emoji · time · session · platform · role: old → new). No judgment, ranking, or prose needed.

**Pattern:**

```python
# All names, not just watched ones — pass names=[""] to diff_xlsx_for_watched
# "" matches every non-empty cell (any('' in val.lower() for val in ...) is always True)
raw = diff_xlsx_for_watched(old_path, new_path, names=[""])

# Noise filter: strip header/template literal strings that appear when
# the sheet's template structure is rebuilt
LABEL_NOISE = {
    "weigh in", "speaker", "timekeeper", "referees (l, c, r)", "tc",
    "chief marshal assist. marshal", "jury president mem 1",
    "jury president mem 1, mem 2", "jr nationals", "youth nationals",
    "snr nationals",
}
clean = [ch for ch in raw
         if (ch.get("old_name") or "").lower().strip() not in LABEL_NOISE
         and (ch.get("new_name") or "").lower().strip() not in LABEL_NOISE]
```

**Message format per line:**
```
emoji · HH:MM AM/PM TZ · SN DayDate 🔴/⚪/🔵 Role: name (added/removed/old→new)
```

- `✅` = added (show new name only — no "— →" prefix)
- `❌` = removed (show old name only — no "→ —" suffix)
- `🔄` = replaced (show old → new)
- Platform as colored circle: 🔴 RED, ⚪ WHITE, 🔵 BLUE (not `[RED]` brackets)
- Session as `S1` not `Sess 1`
- Time in short form: `9:47 PM MT` not full ISO

**Cap bulk reshuffles:** on a full schedule rebuild 600+ lines hit at once. Always cap other-changes at ~30 lines with `… +N more (view sheet for full list)`. Show Jim/Kelly (or any VIP) in full regardless of cap.

**VIP pinning:** check `any(w in (old_n+new_n).lower() for w in WATCHED)` to separate VIP changes and pin them above the general list with a distinct header.

```python
PLAT_EMOJI = {"RED": "🔴", "WHITE": "⚪", "BLUE": "🔵"}

def fmt_line(c):
    emoji = {"added":"✅","removed":"❌"}.get(c["action"],"🔄")
    old_n, new_n = c["old"] or "—", c["new"] or "—"
    chg = new_n if c["action"]=="added" else (old_n if c["action"]=="removed" else f"{old_n} → {new_n}")
    plat = PLAT_EMOJI.get((c["plat"] or "").upper(), "⬜")
    return f"{emoji} {c['when_short']} · S{c['sess']} {c['day_fmt']} {plat} {c['role']}: {chg}"
```

**Structure:**
```
📋 NCW 2026 — Schedule Changes
🕐 Checked: Jun 20 10:15 AM MT
✏️  Editor: jodi.stumbo  |  1 save(s), 12 changes

👇 [VIP names]:
  🟦 Jim · ✅ 9:47 PM MT · S24 Tue Jun 23 🔴 Speaker: James Wiese (NAT)

📋 All changes:
  ✅ 9:47 PM MT · S1 Sat Jun 20 🔵 Marshal: Dori Turnier (ROOM N, Y)
  🔄 9:47 PM MT · S1 Sat Jun 20 🔵 Referee: Michelle Picking (NAT) → Les Simonton (IWF 1)
  … +N more (view sheet for full list)

📄 https://docs.google.com/spreadsheets/d/<id>/edit
```

**Finding an unknown group's WhatsApp chat ID:** send a ping (`{"chatId": "<candidate>@g.us", "message": "test"}`), then ask the user which group received it. The bridge log at `/opt/data/whatsapp/bridge.log` lists outbound `chatId` values — cross-reference there too.

## Complementary-vs-duplicate check

Before scheduling, list existing crons. A meet may already have a *different*
alert engine (e.g. athlete lift-time pings) that looks similar but tracks a
different entity (officials vs lifters). Confirm purpose differs; leave the
existing job untouched and note the distinction to the user rather than
assuming a duplicate.
