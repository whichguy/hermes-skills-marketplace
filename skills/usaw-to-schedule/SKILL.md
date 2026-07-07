---
name: usaw-to-schedule
description: Read/update USA Weightlifting Technical Official (TO) sign-up & session
  schedule sheets.
version: 1.0.0
author: Hermes (for The User)
license: MIT
platforms:
- linux
- macos
- windows
metadata:
  hermes:
    tags:
    - USAW
    - weightlifting
    - technical-officials
    - schedule
    - sheets
    - referees
    related_skills:
    - google-workspace
    config:
    - key: usaw-to-schedule.enabled
      description: Enable usaw-to-schedule skill behavior
      default: true
      prompt: Enable usaw-to-schedule skill?
    category: productivity
---
---

# USA Weightlifting TO (Technical Official) Schedule

How to read and safely update the USAW Technical Officials sign-up / session
schedule workbook (e.g. **"2026 - Nationals - TO Sign-up Sheet.xlsx"**). These
are the "source of truth" sheets that assign TOs (referees, jury, marshals,
timekeepers, speakers, weigh-in officials) to competition sessions.

## Output format preferences (Jim)

- **All times in MT** (Mountain Time) during NCW and any Colorado Springs event.
- **Short labels only:** `9:30 PM` — NOT `9:30 PM MT` on every line. State the timezone once at the top of the message, not per-line.
- **Platform as colored emoji:** 🔴 RED, ⚪ WHITE, 🔵 BLUE — not `[RED]` or plain text.
- **Session as `S1`, `S2`** — not `Sess 1`, `Session 1`.
- **Jim & Family Member highlighted first** with 🟦/🟪, all others below.

## When to use

- Reading who is assigned to a session/platform/role
- Finding a specific person's assignments across the meet
- Checking session times, weigh-in times, weight classes
- Carefully updating sign-ups (only with explicit approval — these are shared,
  owned by USAW staff, e.g. `pedro.meloni@usaweightlifting.org`)

## Key documents (2026 Nationals)

- **TO Sign-up Sheet** (the schedule, `.xlsx`, owned by USAW/Pedro Meloni):
  `1KbXx2eJ1JxN6933lPkYOUR_SLACK_CHANNEL_ID-Z`
- **NCW 2026 Q Totals** (native Google Sheet, lookup table of event → age group →
  gender → weight class with qualifying totals): `1WNVXSz58KfwgdTcXVX654XfgRYOUR_SLACK_CHANNEL_ID-kl-fHM`

The workbook has one **tab per meet/event**, e.g.:
`2026 WZA`, `VWS1`, `2026 NCW`, `2026 MC & UNI`, plus a `List of TOs` roster tab.

> **Current event tab: `2026 NCW`** — this is the tab for the upcoming 2026
> Nationals event. Default reads/lookups to `2026 NCW` unless Jim names another.

### Header positions are NOT the same across tabs — always re-read row 7/8

Column letters shift between tabs and some headers are **merged** or carry
**multiple sub-values**. Confirmed headers:

- **`2026 NCW`** (header row 7): A=Session, B=Platform, **C:D merged =
  `Weigh - In / Start`** (time in D), E=Gndr, F=Age Group/Weight Category, G=#,
  H=Weigh in, I=Speaker, J=Timekeeper, K=Referees (L,C,R), L=TC,
  M=`Chief Marshal / Assist. Marshal` (2 values), N=`Jury President / Mem 1, Mem 2`.
- **`VWS1`** / **`2026 MC & UNI`** (header row 7): columns are shifted right
  (e.g. Referees at N/L, jury at Q/O) and the jury header is richer:
  `Jury President  Mem 1, Mem 2 (Cat 1 Officials only, please) Special Jury`
  — note the extra **Special Jury** slot.
- **`2026 WZA`** (header row 8): compressed layout — `Referee` is a single
  column F, and the banner says **ONE REFEREE PER PLATFORM** (not L/C/R).

**Multi-value columns to watch** (a single header cell, multiple stacked names):
`Weigh in`, `Referees (L, C, R)`, `Chief Marshal / Assist. Marshal`, and the
jury column (incl. optional `Special Jury` on VWS1/MC&UNI). Always re-read the
header row for the specific tab before mapping columns.

## CRITICAL domain rules (how the schedule is structured)

1. **Timezone:** All times are **LOCAL**, and the sheet banner says
   *"ALL TIMES ARE LOCAL UNLESS POSTED OTHERWISE"*. **If no timezone is posted,
   assume Mountain Time (MT).** Only override when a specific cell/header states
   otherwise. When reporting times to Jim, render in friendly local time and
   label the zone (MT) explicitly.
2. **Platforms run concurrently:** `RED`, `WHITE`, `BLUE` are the three
   platforms. Within one **session**, all three platforms run **at the same
   time** (concurrently).
3. **Sessions are sequential:** Session 1, then 2, then 3 … run one after
   another in time order down the sheet.
4. **A session = a block:** All lifters in a single session lift together.
   Usually one weight class per platform, but **occasionally a session/platform
   has multiple weight classes** (rare — the `Weight Category` cell will list
   more than one, e.g. `30kg & 33kg A`, `48kg & 52kg B`).
5. **Gender:** `F` = female, `M` = male (column `Gndr`).
6. **Referee block order = L, C, R:** The `Referees (L, C, R)` column lists three
   referees **in this order: Left, Center, Right** (top cell = Left, middle =
   Center, bottom = Right). Some have an explicit `(L)` tag but the **position is
   determined by row order within the block**, not the tag.
7. **Day separators:** A **full-width row** (text only in column A, spanning the
   sheet) denotes the **day and event group for all sessions below it**, until
   the next separator. Example: `SATURDAY, JUNE 20, 2026 - YOUTH NC - U11 & U13`.
   Everything beneath belongs to that day until the next day-separator row.
8. **Weigh-in:** Each platform block has a **2-hour weigh-in window before start**.
   Column `Weigh - In / Start` pairs rows: the `W. In` row time and the `Start`
   row time (start is typically weigh-in + 2:00). Weigh-in officials are listed
   in the `Weigh in` column.
9. **Report times by role (fixed USAW policy):**
   - **Weigh-in** → report at **W.In time**; duty lasts **max 1 hour** (closes 1 hour before Start)
   - **Marshal / Chief Marshal / Assist. Marshal** → report **30 min before Start** time
   - **All other roles** (Referee, Speaker, Timekeeper, TC, Jury) → report at **Start** time

10. **Role counts per platform block (expected fill):**
   - **Weigh in (col H):** **multiple Tech Officials** are assigned — expect
     **2+ names** stacked down the block (not a single official).
   - **Speaker (col I):** **exactly one** speaker/announcer per platform.
   - **Referees (col K):** **three** — L, C, R (see rule 6).
   - **Chief Marshal / Assist. Marshal (col M):** **two spots** — the Chief
     Marshal and the Assistant Marshal (two stacked names).
   - **Jury (col N):** **only the top-level "A" sessions have a jury of 3**
     (Jury President + Member 1 + Member 2). Validated against 2026 NCW: jury
     panels appear **only on JR/U25 and NATIONALS "A" sessions** — never on
     Youth (U11/U13/14-15/16-17). An empty jury column on Youth/non-A sessions
     is normal, not missing data.

## Column layout (NCW-style tabs)

Header is on the tab's header row (≈ row 7). Columns:

| Col | Header | Meaning |
|-----|--------|---------|
| A | `Session` | Session number (1, 2, 3 …) — only on the first row of the session block |
| B | `Platform` | `RED` / `WHITE` / `BLUE` |
| C | `Weigh - In / Start` | Row label: `W. In` or `Start` |
| D | (time) | The actual time for that W.In / Start row |
| E | `Gndr` | `F` or `M` |
| F | `Age Group / Weight Category` | e.g. `U11 & U13\n40kg B` (may list multiple classes) |
| G | `#` | Number of lifters in the session |
| H | `Weigh in` | Weigh-in official(s) — **multiple TOs** stacked |
| I | `Speaker` | Speaker/announcer — **exactly one** |
| J | `Timekeeper` | Timekeeper |
| K | `Referees (L, C, R)` | **3** referees, top→bottom = Left, Center, Right |
| L | `TC` | Technical Controller |
| M | `Chief Marshal / Assist. Marshal` | **2 spots**: Chief Marshal + Assistant Marshal |
| N | `Jury President / Mem 1, Mem 2` | Jury of **3** — **only top-level "A" sessions (JR/U25 & Nationals)** |

Names often carry a credential tag in parens, e.g. `(NAT)`, `(IWF 1)`, `(IWF 2)`,
`(L)` (Local), or a room assignment like `(ROOM 1, ALL)`. Tabs other than NCW
(`WZA`, `VWS1`, `MC & UNI`) follow the same shape with minor column shifts —
always re-read the header row to confirm column positions for that tab.

## Column positions SHIFT per tab — always re-read the header row

Do **not** hardcode column letters. Each tab has its own header row (find the row
where col A = `Session`) and its own column offsets. Confirmed examples:

| Field | 2026 NCW | VWS1 | 2026 MC & UNI | 2026 WZA |
|-------|----------|------|---------------|----------|
| Referees (L,C,R) | K | N | L | F |
| Speaker | I | L | J | — |
| Chief/Assist Marshal | M | P | N | — |
| Jury | N | Q | O | — |

### Merged / multi-value header fields (Jim's note — watch these)

Several headers are **merged across columns** and/or pack **multiple values into
one field**. Re-read each header and expand it:

- **`Weigh-In / Start`** — header is **merged across two columns (C:D)**: the
  label (`W. In` / `Start`) sits in the left column, the **time** in the right.
- **`Gender, b/w, group`** — on **VWS1** and **MC & UNI** the header is **merged
  (E:F)** and combines **gender + bodyweight category + group** in one field
  (NCW splits these into `Gndr` (E) + `Age Group / Weight Category` (F)).
- **`Referees (L, C, R)`** — one header, **three stacked values** (L, C, R order).
- **`Chief Marshal / Assist. Marshal`** — one header, **two stacked values**.
- **`Jury President / Mem 1, Mem 2`** — one header, up to **three values**; on
  VWS1 & MC & UNI it also carries **`Special Jury`** and the note
  **"Cat 1 Officials only, please"**. Only Senior "A" sessions field a jury (see
  domain rule 9).

When parsing, programmatically read merged-cell ranges (`ws.merged_cells.ranges`)
so you don't mistake a merged label column for an empty one.

## Block geometry (how to parse sessions)

- Each **platform block is ~3 rows tall**: row 1 = `W. In` + most assignments,
  row 2 = `Start` + second referee + second marshal, row 3 = third referee.
- A **session** = three stacked platform blocks (RED, WHITE, BLUE), ~10 rows,
  followed by a blank separator row before the next session.
- The **referee** column (K) for a block spans its 3 rows = L, C, R in order.

## Reading the sheet

Read the native Google Sheet (Q Totals) directly; download the `.xlsx` and parse
with openpyxl (no pip in this env → use `uv run --with openpyxl`).

### ⚠️ Pitfall: assignments_snapshot.json person field is always empty

The change-watcher at `/opt/data/cron_state/usaw_to/assignments_snapshot.json`
stores session structure (categories, times, platforms) but **`person` is always `""`**
in the snapshot — names are populated only during live diffing, not persisted.

**To look up who is assigned to what, always parse directly from the xlsx:**

```python
import sys
sys.path.insert(0, '/opt/data/scripts')
import usaw_to_lib as L
L.ensure_deps()

# Parse all assignments (no name filter)
assignments = L.parse_assignments(xlsx_path=L.XLSX_PATH, names=None)
# Filter by name
wiese = [a for a in assignments if 'wiese' in a.get('person', '').lower()]
wiese.sort(key=lambda a: (a['day'], a['sess'], a.get('win') or ''))
```

`L.XLSX_PATH` = `/opt/data/cron_state/usaw_to/to_signup.xlsx` (live downloaded copy).
Do NOT query the snapshot JSON for name-based lookups — it will always return zero results.

**Auto-retry all Google API / Drive calls: up to 10 attempts with exponential
backoff** (Google reads intermittently 429/500/503). Wrap network calls in a
retry loop — e.g. delays of 1, 2, 4, 8 … seconds (cap ~60s), 10 tries max,
before surfacing a failure.

```bash
# Retry wrapper for any Google API call (10 tries, exponential backoff)
gapi_retry() {
  local n=0 max=10 delay=1
  until "$@"; do
    n=$((n+1))
    if [ "$n" -ge "$max" ]; then echo "FAILED after $max attempts: $*" >&2; return 1; fi
    echo "retry $n/$max in ${delay}s..." >&2; sleep "$delay"
    delay=$(( delay*2 )); [ "$delay" -gt 60 ] && delay=60
  done
}

```bash
# Shorthand for the Google API wrapper (uv handles missing deps)
GAPI() {
  uv run --quiet \
    --with google-api-python-client --with google-auth-oauthlib --with google-auth-httplib2 \
    python ${HERMES_HOME:-$HOME/.hermes}/skills/productivity/google-workspace/scripts/google_api.py "$@"
}

# Q Totals (native Google Sheet) — read lookup table
gapi_retry GAPI sheets get 1WNVXSz58KfwgdTcXVX654XfgRYOUR_SLACK_CHANNEL_ID-kl-fHM "A1:E200"

# Download the TO Sign-up workbook (.xlsx) to parse locally
gapi_retry GAPI drive download 1KbXx2eJ1JxN6933lPkYOUR_SLACK_CHANNEL_ID-Z --output /tmp/to_signup.xlsx
```

Parse with `scripts/parse_to_schedule.py` (lists tabs, day separators, sessions,
platforms, and per-person assignment lookups):

```bash
uv run --quiet --with openpyxl python \
  ${HERMES_HOME:-$HOME/.hermes}/skills/productivity/usaw-to-schedule/scripts/parse_to_schedule.py \
  /tmp/to_signup.xlsx --tab "2026 NCW"

# Find one person's assignments across all tabs
uv run --quiet --with openpyxl python \
  ${HERMES_HOME:-$HOME/.hermes}/skills/productivity/usaw-to-schedule/scripts/parse_to_schedule.py \
  /tmp/to_signup.xlsx --person "Family Member Wiese"
```

## Updating the sheet (DANGER — shared, owned by USAW)

> ⛔ **READ-ONLY BY DEFAULT. Jim's standing instruction: DO NOT MODIFY THE SHEET.**
> Treat these documents as strictly read-only. Use only non-mutating operations
> (`drive get`, `drive download`, `sheets get`). Do **not** run `sheets update`,
> `sheets append`, re-upload an edited `.xlsx`, or edit via the UI on Jim's
> behalf. Only consider a write if Jim **explicitly** asks for that specific edit
> in that moment — and even then, confirm the exact cell + new value first and
> back up the original.

1. **Always confirm with Jim before any write.** These are shared "source of
   truth" sheets owned by USAW staff. An accidental edit affects the whole meet.
2. The schedule is an **`.xlsx` in Drive**, not a native Google Sheet — the
   `sheets update` API targets native Sheets. To edit safely:
   - Prefer making the change **in the Google Sheets UI** (open the webViewLink),
     OR
   - Download → edit with openpyxl → re-upload as a new version only with explicit
     approval and after backing up the original.
3. **Never blank a cell to "move" an assignment** — copy first, verify, then
   clear. Keep the L/C/R row order intact when changing referees.
4. After any change, re-parse and show Jim a diff of the affected session block.

## Reminder cron (duty reminders for Jim & Family Member)

A `no_agent` cron job (`006d130492a7`, every 15 min) runs `usaw_to_reminder.py`,
which fires TWO reminders per **person per session**, timed to their **earliest duty**:

| Offset (before earliest duty) | Label | Purpose |
|-------------------------------|-------|---------|
| 2h | `2h prep` | Travel / get-ready window |
| 15m | `15m final` | Final heads-up |

**Earliest duty rule:** if the person has Weigh-in duty, their earliest duty is the
weigh-in time (typically 2hr before session start). Otherwise, earliest duty = session
start time. This ensures the 2h prep reminder arrives with enough time to get to
weigh-in — previously it fired 2h before *session start*, which is exactly when
weigh-in begins (useless for prep).

| Session | Roles | Earliest duty | 2h fires at | 15m fires at |
|---------|-------|--------------|-------------|-------------|
| S15 | Referee only | 9:00 AM (start) | 7:00 AM | 8:45 AM |
| S18 | Weigh-in + Referee | 1:00 PM (weigh-in) | 11:00 AM | 12:45 PM |
| S20 | Weigh-in + Marshal | 5:00 PM (weigh-in) | 3:00 PM | 4:45 PM |

Each fires exactly once (deduped by `person|day|sess|offset` key in
`reminders_sent.json`). Silent outside the event window and when no reminders are due.

**Header format:** `🏋️ *NCW — Duty Reminder · {label}* ({Xh Ym to go})`
- The `{label}` distinguishes which reminder fired (`2h prep` vs `15m final`), so
  Jim knows instantly whether to start getting ready or wrap up and go.
- If both offsets fire in the same tick (edge case): header shows `2h prep + 15m final`.

**Body format (per session):**
```
📅 {Day} · S{N} · Start {time} MT  (Weigh-in {time} MT)
  🟦 Jim · 🔴 · ⚖️ Weigh-in @ 1:00 PM MT — {category}
  🟦 Jim · 🔵 · 🦓 Referee (Center) @ 3:00 PM MT — {category}
  🟪 Family Member · ⚪ · ⚖️ Weigh-in @ 1:00 PM MT — {category}
  🟪 Family Member · 🔵 · 🦓 Referee (Right) @ 3:00 PM MT — {category}
```

- **Wall-clock `@ {time} MT`** on every assignment line — weigh-in time for
  weigh-in roles, session start time for all other roles. This makes it explicit
  when each duty starts, not just the session start.
- **Weigh-in listed first** within each person's assignments (chronological order).
- All times include **MT** suffix — cron notifications are standalone (no surrounding
  context), so the per-line MT is necessary. The "short labels / state timezone once
  at top" preference in the Output Format section above applies to **agent chat
  responses**, not to standalone cron script output.
- Role emoji: 🦓 Referee, ⚖️ Weigh-in, 📋 Marshal, 🎙️ Speaker, ⏱️ Timekeeper, 🛠️ TC, 👨‍⚖️ Jury
- Platform emoji: 🔴 RED, ⚪ WHITE, 🔵 BLUE
- Schedule sheet link at bottom as **Markdown hyperlink** — never bare URLs

**Pitfall — fmt_t() must include MT:** The original `fmt_t()` returned `3:40 PM`
without the timezone suffix. Since these are standalone Telegram notifications
with no header context stating the timezone, every time must carry `MT` — Jim
reads these on his phone in California where PT is the local zone.

**Pitfall — header must distinguish reminder type:** The original header was
`🏋️ *NCW — Duty Reminder*` with no indication of which offset fired. Both the 2h
and 15m reminders produced identical headers. The fix adds the offset label
(`2h prep` / `15m final`) to the header so Jim knows which ping he's receiving.

**Position info in reminder output (Referee L/C/R + Marshal Chief/Assist):**
Both `usaw_to_reminder.py` and `usaw_to_change_watch.py` now display the position
within the platform block:
- **Referee:** `Referee (Left)`, `Referee (Center)`, `Referee (Right)` — position
  0=Left, 1=Center, 2=Right
- **Marshal:** `Chief Marshal`, `Assist Marshal` — position 0=Chief, 1+=Assist

The `pos_in_block` field is computed in `usaw_to_lib.py` by counting same-role
entries above the current row within the platform block. Divider rows (repeated
header text like `Referees\n(L, C, R)` or `Chief Marshal\nAssist. Marshal`) are
skipped and **reset** the position counter — so the first referee after a divider
is position 0 (Left) again.

**Critical: `(L)` in a cell value means Local referee certification, NOT Left position.**
The position is determined by row order within the platform block. Other certification
tags include `(NAT)` (National), `(IWF 1)`, `(IWF 2)`, `(T CAT 1)`, `(T CAT2)`, and
room assignments like `(ROOM 1, ALL)`. Do NOT parse these parenthetical tags as
position indicators — use `pos_in_block` from the row order.

**Example reminder output (with position info + wall-clock times):**
```
🏋️ *NCW — Duty Reminder · 2h prep* (1h 55m to go)

📅 Mon Jun 22 · S15 · Start 9:00 AM MT  (Weigh-in 7:00 AM MT)
  🟦 Jim · 🔵 · 🦓 Referee (Center) @ 9:00 AM MT — 16-17yo 71kg B
  🟪 Family Member · 🔵 · 📋 Assist Marshal @ 9:00 AM MT — 16-17yo 71kg B

[📋 Schedule](https://docs.google.com/spreadsheets/d/...)
```

For sessions with weigh-in + another role, the wall-clock times differ per line:
```
📅 Mon Jun 22 · S18 · Start 3:00 PM MT  (Weigh-in 1:00 PM MT)
  🟦 Jim · 🔴 · ⚖️ Weigh-in @ 1:00 PM MT — 16-17yo 94+kg B
  🟦 Jim · 🔵 · 🦓 Referee (Center) @ 3:00 PM MT — 16-17yo 79 kg A
  🟪 Family Member · ⚪ · ⚖️ Weigh-in @ 1:00 PM MT — 16-17yo 69kg - 77kg B
  🟪 Family Member · 🔵 · 🦓 Referee (Right) @ 3:00 PM MT — 16-17yo 79 kg A
```

**Example change-watch output (with position info):**
```
👇 Jim & Family Member:
  🟦 Jim · ✅ 8:45 AM MT · S15 Mon Jun 22 🔵 Referee (Center): New Person
  🟪 Family Member · 🔄 8:45 AM MT · S15 Mon Jun 22 🔵 Assist Marshal: Old → New
```

### Change consolidation (role moves within a session)

The change-watcher consolidates remove+add pairs for the same person in the same
session+platform into a single 🔄 "moved" line, instead of showing separate ❌
and ✅ entries. This reduces noise when someone swaps roles (e.g. moved from
Marshal to Referee within the same platform block).

**Consolidation rules:**
- **Same person, same session, same platform** → merge removal + addition into one
  `🔄 Old Role → New Role (Person)` line
- **Weigh-in is exempt** — a person can do weigh-in + another role in the same
  session, so weigh-in changes are never merged with non-weigh-in changes
- **Cross-platform moves** → stay as separate lines (different platforms = different
  assignments, even if same session)
- **Pure add or pure removal** with no matching pair → stays as-is

The `consolidate_changes()` function in `usaw_to_change_watch.py` implements this
by grouping changes by `(person, day, sess, plat, role_bucket)` where
`role_bucket` is `"Weigh-in"` for weigh-in entries and `"_ROLE"` for everything
else (so non-weigh-in roles share a group and can be merged).

**Before consolidation (3 lines):**
```
✅ S17 🔵 Referee (Center): Scott Gonzalez (NAT)
❌ S17 ⚪ Chief Marshal: Jim Healis (NAT)
✅ S17 ⚪ Referee (Right): Jim Healis (NAT)
```

**After consolidation (2 lines):**
```
✅ S17 🔵 Referee (Center): Scott Gonzalez (NAT)
🔄 S17 ⚪ Chief Marshal → Referee (Right) (Jim Healis)
```

**Pitfall — `fmt_line()` for moved entries:** When `action == "moved"`, the `chg`
string already contains the full role transition (`Chief Marshal → Referee (Right)
(Jim Healis)`) — the standard `role_lbl: {chg}` suffix is NOT appended for moved
entries, only the time/session/platform prefix + the transition text. This avoids
duplicate role labels.

State file: `/opt/data/cron_state/usaw_to/reminders_sent.json` (JSON array of sent keys)

**Dry-run testing the reminder script:** `datetime.datetime.now` is an immutable C type — you cannot monkeypatch it (`TypeError: cannot set 'now' attribute of immutable type 'datetime.datetime'`). To test the formatted output without waiting for a real trigger time, extract the formatting logic (header construction, `fmt_t()`, `time_label()`, groupby loop) and call it directly with mock `due` entries and a fixed `now` value. Build mock `due` tuples as `(start_dt, assignment_dict, sent_key, human_label)` matching the real structure. This verifies the output format (MT suffix, header label, emoji rendering) without touching live state files or the real clock.

## Change-watching cron (live schedule monitor)

A companion cron job (`usaw_to_change_watch.py` + `usaw_to_lib.py`) watches
the TO Sign-up xlsx for edits during the event window and alerts Jim and Family Member
via Telegram. It uses the Drive Revisions API (`revisions().list()`) — one cheap
API call per tick — and only downloads + diffs the xlsx when the revision ID
changes. See `script-first-cron-design → references/drive-revision-change-watcher.md`
for the full 3-tier precheck-LLM pattern and the cell-level diff engine.

**Delivery:** The cron job (`3a8b59f34fdd`) delivers to `telegram,whatsapp:YOUR_WHATSAPP_GROUP_ID` (the "TO Changes" WhatsApp group). Both channels receive the formatted alert when any row changes. The WhatsApp group ID `YOUR_WHATSAPP_GROUP_ID` is the "TO Changes" meet coordination group.

**Cadence:** Every 15 minutes (`*/15 * * * *`), `no_agent=True` — the script outputs the final formatted message directly, zero LLM tokens.

**Coverage:** The watcher tracks ALL role-column changes (not just Jim/Family Member). Jim and Family Member changes are pinned at the top with 🟦/🟪 icons. Everything else is listed below, capped at 30 lines on bulk reshuffles with `… +N more (view sheet for full list)`.

**Message format (per change line):**
```
emoji · time · SN Date 🔴/⚪/🔵 Role (Position): old → new
```
- ✅ for added (shows new name only), ❌ for removed (shows old name only), 🔄 for replaced (shows old → new)
- Platform shown as colored circle emoji: 🔴 RED, ⚪ WHITE, 🔵 BLUE
- Session shown as `S1`, `S2` etc (not `Sess 1`)
- **Role includes position:** `Referee (Left)`, `Referee (Center)`, `Referee (Right)`, `Chief Marshal`, `Assist Marshal` — computed from `pos_in_block` in the diff engine
- Bulk reshuffles: Jim/Family Member shown in full, all others capped at 30 lines

**Noise filter:** Template/header cells (literal strings like "Weigh in", "Speaker", "Timekeeper", "Referees (L, C, R)", "TC", "Chief Marshal Assist. Marshal", "Jury President Mem 1, Mem 2", "JR Nationals", "Youth Nationals", "SNR Nationals") are stripped from diffs — they appear when the sheet's template structure is rebuilt and are not real assignment changes.

Key state file: `/opt/data/cron_state/usaw_to/last_revision.json`
Keys: `revisionId`, `modifiedTime`, `modifiedBy`, `last_checked_at`

`last_checked_at` is stamped on **every** tick (including silent/no-change runs)
so you can always answer "when did we last poll?". `revisionId` is the change
key — `modifiedTime` alone is not reliable. `modifiedBy` may be empty string
for system edits; display as "system edit".

## Creating Google Calendar events from sessions

Each lifting session = **2 hours** from start time. Use personal Google Calendar account. MT = UTC offset `-06:00`.

```python
import subprocess, json
from collections import defaultdict

GAPI = "uv run --with google-api-python-client --with google-auth-oauthlib --with google-auth-httplib2 python /opt/data/skills/productivity/google-workspace/scripts/google_api.py"

# Group assignments by (day, sess) — one event per session
sessions = defaultdict(list)
for a in assignments:
    sessions[(a['day'], a['sess'])].append(a)

PLAT_EMOJI = {'RED': '🔴', 'WHITE': '⚪', 'BLUE': '🔵'}

for (day, sess), roles in sorted(sessions.items()):
    starts = [r['start'] for r in roles if r['start']]
    if not starts: continue
    earliest = min(starts)
    h, m = map(int, earliest.split(':'))
    start_iso = f"{day}T{h:02d}:{m:02d}:00-06:00"   # MT = -06:00
    end_iso   = f"{day}T{h+2:02d}:{m:02d}:00-06:00"  # always +2h

    role_parts = [f"{PLAT_EMOJI.get(r['plat'].upper(), '⬜')} {r['role']}"
                  for r in sorted(roles, key=lambda x: x['start'] or '')]
    title = f"🏋️ NCW TO — S{sess:02d} · {' · '.join(role_parts)}"
    location = "Ed Robson Arena, 849 N Tejon St, Colorado Springs, CO 80903"

    cmd = (f'{GAPI} --account personal calendar create '
           f'--summary "{title}" --start {start_iso} --end {end_iso} '
           f'--location "{location}"')
    result = json.loads(subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout)
```

**Pitfall:** `start` field on some rows can be `None` (session 24 RED in 2026 NCW). Always guard with `if r['start']` before splitting. Skip the event if no start times found for the session.

**Idempotency:** Before creating, search for existing events with the same summary on the same day to avoid duplicates. The Calendar API `list` with a date range + summary filter is sufficient.

## Shared helpers architecture (usaw_to_lib.py)

Three scripts consume the sheet: `usaw_to_reminder.py` (duty reminders),
`usaw_to_change_watch.py` (schedule change alerts), and `ncw_alerts.py`
(athlete lift alerts). Shared logic lives in `usaw_to_lib.py` — the single
source of truth for:

| Helper | Purpose |
|--------|---------|
| `PLAT_EMOJI` + `plat_emoji(p)` | Platform → emoji (🔴⚪🔵), default ⬜ |
| `REF_POS` / `MARSHAL_POS` | Position label dicts (0=L/Chief, 1=C/Assist, 2=R) |
| `role_label(role, pos_in_block)` | Full role label: `Referee (Center)`, `Chief Marshal` |
| `compute_pos_in_block(ws_cells_fn, row, col)` | Count same-role entries above row in platform block, skipping divider rows |
| `DIVIDER_MARKERS` | Tuple of header-repeat strings to skip in position counting |
| `parse_assignments(names=...)` | Extract assignments from xlsx, includes `pos_in_block` field |
| `diff_xlsx_for_watched(old, new, names)` | Cell-level diff between revisions, includes `pos_in_block` |

**When adding a new feature that needs role formatting or position info,
import from `usaw_to_lib` — do NOT re-implement `PLAT_EMOJI`, `REF_POS`,
`MARSHAL_POS`, or position-counting logic in the consumer script.** The
consolidation was done because all three scripts had drifted copies that
broke independently.

## Sheet data analysis & feature ideas

See `references/sheet-data-analysis.md` for:
- Workbook tab inventory (NCW, WZA, VWS1, MC & UNI, List of TOs)
- Multi-platform conflict analysis (42 conflicts, Jim has 4 — all time-feasible)
- Empty role slot breakdown (364 total, 19 critical)
- Jim & Family Member workload per day
- Feature ideas ranked by impact: conflict detector, daily workload summary,
  empty slot tracker, TO roster lookup, athlete-TO cross-reference, multi-meet support

## Pitfalls

- **No pip in this env.** Always use `uv run --with openpyxl` (and the `uv`
  wrapper for the Google API). Plain `python google_api.py` throws
  `ModuleNotFoundError: googleapiclient`.
- `data_only=True` in openpyxl returns computed values; times come back as
  `datetime.time` objects.
- Cell text uses `\\n` newlines inside `Age Group / Weight Category` and headers —
  normalize whitespace when matching.
- A person can appear in **multiple roles and sessions**; always search the whole
  column set, not just referees.
- Don't assume one weight class per platform — check for `&` in the category cell.
- The first row of a session is the only one with the `Session` number; rows
  below inherit it until the next numbered row / blank separator.
- **Early revisions may lack the NCW tab entirely.** The `2026 NCW` tab did not
  exist in the Feb 9, 2026 revision — it was added later. `openpyxl` raises
  `KeyError: 'Worksheet 2026 NCW does not exist.'` when you try to access it.
  Always guard with `if tab not in wb.sheetnames: return {}` before accessing.
- **Blank row between W.In and Start (session 24 RED pattern).** Most session
  blocks have Start time at `anchor_row + 1` (col D). But occasionally a blank
  separator sits between them (confirmed: 2026 NCW session 24 RED — W.In at R244,
  blank at R245, Start at R246). Do NOT use `cells.get((r+1, 4))` alone; scan
  forward up to 3 rows, preferring the row where col C label starts with "Start".
  Failure to handle this causes `start=None` → urgency returns "unknown" → 🔴/🟡/🟢
  icons all render as ⚪ for those sessions.
- **`scope_signal()` and `session_urgency()` are now part of `usaw_to_lib.py`.**
  `scope_signal(old_path, new_path)` → `{label, total_role_changes, watched_changes,
  ratio_pct, size_delta_bytes}`. `session_urgency(date_str, start_str, now_mt)` →
  `{label, icon, hours_until}`. Both are deterministic Python — no LLM needed.
  See `script-first-cron-design → references/drive-revision-change-watcher.md`
  for full code.
- **`cronjob action=update` cannot toggle `no_agent`.** To flip a job from
  `no_agent: true` to LLM mode, edit `/opt/data/cron/jobs.json` directly:
  the array key is `"id"` (not `"job_id"` as the API returns). Set
  `job["no_agent"] = False` then write back. Verify with `cronjob action=list`.
- **Shared-helpers consolidation pattern.** When multiple `no_agent` cron
  scripts consume the same data source (e.g. `usaw_to_reminder.py`,
  `usaw_to_change_watch.py`, and `ncw_alerts.py` all read the USAW TO sheet),
  extract shared constants (emoji dicts, position mappings, divider markers)
  and shared functions (`plat_emoji()`, `role_label()`, `compute_pos_in_block()`)
  into the lib module (`usaw_to_lib.py`). Consumer scripts import them rather
  than maintaining drift-prone inline copies. The `compute_pos_in_block()`
  helper takes a cell-accessor function so it works with both `openpyxl`
  worksheet objects AND raw cell dicts from the diff engine — one function,
  two call sites, zero duplication.
- **Safe N-day lookback test pattern (manual replay without corrupting live state):** To force-replay recent sheet changes without touching `/opt/data/cron_state/usaw_to/`, use a standalone script that (1) fetches all revisions, (2) filters to those within a CUTOFF = `now_mt - timedelta(days=N)`, (3) downloads the last revision *before* the window as the baseline, (4) walks the window revisions as diffs, and (5) posts results directly — never reading or writing the live state file. Template: `${HERMES_HOME}/scripts/usaw_test_run.py`. Post to TO Changes WhatsApp directly via `requests.post("http://localhost:3000/send", json={"chatId": "YOUR_WHATSAPP_GROUP_ID", "message": msg})`. To force a live-script test without corrupting state: save the state file, blank the `revisionId` key, run the script, then restore from backup.
- **Group ID lookup:** The correct chatId for "TO Changes" is `YOUR_WHATSAPP_GROUP_ID`. The old ID `YOUR_WHATSAPP_GROUP_ID` goes to Jim's home/personal channel — NOT the TO Changes group. Always verify by sending a test ping before wiring up a cron. The bridge log at `/opt/data/whatsapp/bridge.log` shows outbound `chatId` values for recently sent messages — cross-reference to identify unknown groups.

- **`parse_assignments(names=[""])` or `names=['']` returns ZERO results — not empty person:** When called with an empty-string names list, `all_mode` is False (since `[""] != ["*"]`). The function enters named mode, matches `""` against every cell (empty string is `in` every string, so `person_name = ""`), but then `if not person_name: continue` skips every entry because empty string is falsy. Result: 0 assignments returned, not assignments with empty person fields. **Correct usage:** call `parse_assignments()` with no args (defaults to `WATCHED = ["The User", "Family Member Wiese"]`), or `names=["*"]` for all-mode (returns every assignment with `person` set to the cell value, cert tags stripped). Never pass `names=[""]` or `names=['']` — it silently returns nothing.

- **No bare URLs in cron output — always Markdown hyperlinks.** Jim's preference: all URLs in notification messages must be `[label](url)` Markdown links, never bare `https://...` strings. This applies to all three TO scripts (`usaw_to_reminder.py`, `usaw_to_change_watch.py`, `ncw_alerts.py`). The reminder and athlete alert scripts already used Markdown links; the change-watch script had a bare URL at the bottom — now fixed to `📄 [Schedule](url)`.

- **Token-efficient breadcrumb docstrings for cron scripts.** Each `no_agent` cron script should have a docstring that lets a future agent understand the script without reading the full source. Keep it to ~10-15 lines covering: cron schedule + silence conditions, output format, key design decisions (grouping, dedup, position logic), shared helper references, and a wiki cross-reference (`[[ncw-2026-to-logistics]]`). This costs minimal tokens when loaded but saves a full file read when the agent needs to recall how the script works.

- **Divider rows in the sheet repeat header text and must be skipped when computing position.** Cells containing `Referees\n(L, C, R)` or `Chief Marshal\nAssist. Marshal` appear mid-block as sub-section dividers (separating groups of referees within the same platform block). When computing `pos_in_block`, these rows must be detected (by checking for `referees`, `chief marshal`, `assist. marshal` markers in the cell text) and skipped — and the position counter must **reset to 0** after a divider, so the first referee after the divider is position 0 (Left) again. Both `parse_assignments()` and `diff_xlsx_for_watched()` in `usaw_to_lib.py` implement this logic.

- **Always test the change-watcher against an isolated /tmp dir, never the live state dir.** Running `usaw_to_change_watch.py` against the live `/opt/data/cron_state/usaw_to/` without `USAW_STATE_DIR` override advances the `revisionId` anchor. If the state file is also deleted during testing, the next real cron tick replays all historical assignments as new alerts. Re-seed after corruption by writing the current latest revision directly to `last_revision.json` (see `script-first-cron-design → references/drive-revision-change-watcher.md` for the snippet), then verify empty stdout on the next run.
- **`modifiedBy` is empty string for system/programmatic edits** (not `None`).
  Guard at extraction: `(user or {}).get("displayName") or "unknown"`. Display
  to the user as "system edit", never as a blank.
