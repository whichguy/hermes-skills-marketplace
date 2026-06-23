# TO Assignment Lookup — NCW 2026

## Key paths

| File | What it contains |
|------|-----------------|
| `/opt/data/cron_state/usaw_to/to_signup.xlsx` | Live sheet download — names ARE here |
| `/opt/data/cron_state/usaw_to/assignments_snapshot.json` | Structure only — `person` fields are always empty |
| `/opt/data/scripts/usaw_to_lib.py` | Library: `parse_assignments()`, `XLSX_PATH`, `TAB` |

## Tab scoped to current event

```python
TAB = "2026 NCW"  # hardcoded in usaw_to_lib.py
```

Only the "2026 NCW" tab is parsed. "Sheet8" and "List of TOs" tabs are ignored.

## Correct pattern: look up all assignments for a person

```python
import sys
sys.path.insert(0, '/opt/data/scripts')
import usaw_to_lib as L
L.ensure_deps()

# Parse ALL assignments (no name filter) directly from live xlsx
assignments = L.parse_assignments(xlsx_path=L.XLSX_PATH, names=None)

# Filter by name
wiese = [a for a in assignments if 'wiese' in a.get('person','').lower()]
wiese.sort(key=lambda a: (a['day'], a['sess'], a['win'] or '', a['person']))
```

## WRONG: using the snapshot JSON for person lookups

```python
# DON'T DO THIS — person fields are always empty
data = json.loads(Path("/opt/data/cron_state/usaw_to/assignments_snapshot.json").read_text())
wiese = [a for a in data if 'wiese' in a.get('person','').lower()]  # returns []
```

## Assignment dict fields

| Field | Example | Notes |
|-------|---------|-------|
| `person` | `"Kelly Wiese"` | Full name as it appears in sheet |
| `day` | `"2026-06-21"` | ISO date string |
| `sess` | `11` | Session number (int) |
| `plat` | `"BLUE"` | Platform: RED/WHITE/BLUE |
| `role` | `"Referee"` | Weigh-in/Speaker/Referee/Marshal |
| `cat` | `"14-15yo 63kg & 69kg A"` | Weight category + group |
| `gndr` | `"F"` | Gender |
| `win` | `"11:30"` | Weigh-in time (HH:MM, 24h) |
| `start` | `"13:30"` | Session start time (may be None) |
| `tag` | `"NAT"` | Certification tag (NAT, L, IWF 1, IWF 2, etc.) — NOT referee position |
| `pos_in_block` | `1` | 0-based position within platform block. Ref: 0=Left, 1=Center, 2=Right. Marshal: 0=Chief, 1+=Assistant. |

## Platform emoji map

```python
PLAT = {'RED': '🔴', 'WHITE': '⚪', 'BLUE': '🔵'}
```

## Session confirmed at NCW 2026: Wiese assignments

As of Jun 21, 2026 sheet snapshot: **37 assignments** across 4 days (Jun 20–23).
No assignments visible after Tue Jun 23 — later sessions may not yet be populated.

- **Jim (James Wiese)** 🟦: 19 assignments
- **Kelly Wiese** 🟪: 18 assignments
- Both primarily on 🔴 RED platform, NAT tag
- Roles: Referee (most common), Weigh-in, Speaker, Marshal

## See also

- `references/to-sheet-structure.md` — full column layout, certification tag meanings, divider row detection, position calculation details