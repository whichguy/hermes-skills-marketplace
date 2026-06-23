# TO Sign-up Sheet Structure (2026 NCW tab)

## Header row (row 7)

| Col | Letter | Header text | Notes |
|-----|--------|-------------|-------|
| 1 | A | `Session` | Integer (1, 2, 3...) — only on first row of session block |
| 2 | B | `Plat-form` | `RED`, `WHITE`, `BLUE` |
| 3-4 | C:D | `Weigh - In / Start` (merged) | C=label (`W. In`/`Start`), D=time |
| 5 | E | `Gndr` | `F` or `M` |
| 6 | F | `Age Group / Weight Category` | May contain `\n` and `&` (multiple classes) |
| 7 | G | `#` | Number of lifters |
| 8 | H | `Weigh in` | Multiple TOs stacked (2+ names) |
| 9 | I | `Speaker` | Exactly one |
| 10 | J | `Timekeeper` | Often empty |
| 11 | K | `Referees (L, C, R)` | 3 names, top→bottom = Left, Center, Right |
| 12 | L | `TC` | Technical Controller, often empty |
| 13 | M | `Chief Marshal / Assist. Marshal` | 2 names: Chief (top), Assistant (bottom) |
| 14 | N | (empty in NCW) | — |
| 15 | O | `Jury President / Mem 1, Mem 2` | Only on A sessions (JR/U25 & Nationals) |

## Divider rows

Mid-block rows that repeat header text as sub-section dividers:
- `Referees\n(L, C, R)` — separates referee groups within a platform block
- `Chief Marshal\nAssist. Marshal` — separates marshal groups

These must be **skipped** when counting position (`pos_in_block`). The
position counter **resets to 0** after a divider — the first referee after
a divider is position 0 (Left) again.

Detection: check cell text for `referees`, `chief marshal`, `assist. marshal`
(case-insensitive substring match via `DIVIDER_MARKERS` in `usaw_to_lib.py`).

## Certification tags (parenthetical, in cell values)

| Tag | Meaning | Confused with? |
|-----|---------|----------------|
| `(L)` | **Local** referee | NOT "Left" position — position is by row order |
| `(NAT)` | **National** TO | |
| `(IWF 1)` | IWF Category 1 | |
| `(IWF 2)` | IWF Category 2 | |
| `(T CAT 1)` | Technical official, Category 1 | |
| `(T CAT2)` | Technical official, Category 2 | |
| `(T NAT)` | Technical National | |
| `(ROOM 1, ALL)` | Room assignment + session scope | Room assignments, not certification |

**Critical**: The `(L)` tag means Local certification, NOT Left referee
position. Left/Center/Right is determined by row order within the platform
block (position 0=Left, 1=Center, 2=Right), NOT by the parenthetical tag.

## Position computation

`compute_pos_in_block(ws_cells_fn, row, col)` in `usaw_to_lib.py`:
1. Walk backwards from `row` to find the platform anchor (first row where col B = RED/WHITE/BLUE)
2. Count non-empty, non-divider cells in the same column between anchor and `row`
3. Reset counter to 0 at each divider row
4. Return 0-based position

Works with both `openpyxl` worksheets (via `lambda r, c: norm(ws.cell(r, c).value)`)
and raw cell dicts from the diff engine (via `lambda r, c: new_cells.get((r, c), "")`).

## Other tabs in the workbook

| Tab | Header row | Key differences |
|-----|-----------|-----------------|
| `2026 WZA` | Row 8 | Compressed: Referee is single col F, "ONE REFEREE PER PLATFORM" |
| `VWS1` | Row 7 | Columns shifted right; gender+category merged in E:F |
| `2026 MC & UNI` | Row 7 | Columns shifted; has Special Jury slot; "Cat 1 Officials only" |
| `List of TOs` | Row 1 | Roster: name, cert, email, phone (2,558 entries) |

Always re-read the header row for each tab before mapping columns — do not
assume column positions are the same across tabs.