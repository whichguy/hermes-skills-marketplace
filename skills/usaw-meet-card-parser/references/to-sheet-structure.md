# TO Sign-up Sheet Structure — NCW 2026

## Column layout (row 7 = header)

| Col | Header | Role key |
|-----|--------|----------|
| 1 | Session | — |
| 2 | Platform (RED/WHITE/BLUE) | — |
| 3-4 | Weigh-In / Start (merged) | — |
| 5 | Gender | — |
| 6 | Age Group / Weight Category | — |
| 7 | # | — |
| 8 | Weigh in | `Weigh-in` |
| 9 | Speaker | `Speaker` |
| 10 | Timekeeper | `Timekeeper` |
| 11 | Referees (L, C, R) | `Referee` |
| 12 | TC | `TC` |
| 13 | Chief Marshal / Assist. Marshal | `Marshal` |
| 15 | Jury President / Mem 1, Mem 2 | `Jury` |

`ROLE_COLS` in `usaw_to_lib.py`: `{8: "Weigh-in", 9: "Speaker", 10: "Timekeeper", 11: "Referee", 12: "TC", 13: "Marshal", 14: "Jury"}`

## Platform blocks

Each platform (RED/WHITE/BLUE) is a block of 3-4 rows. Col 2 has the platform
label on the first row; subsequent rows have col 2 = None. The parser
walks backwards from the assignment row to find the platform anchor.

## Referee position (L/C/R) — row order, NOT the parenthetical tag

The header says `Referees (L, C, R)` but `(L)` in a cell value means
**Local referee certification**, NOT "Left position." Position is determined
by row order within the platform block:

| pos_in_block | Position |
|---|---|
| 0 | Left |
| 1 | Center |
| 2 | Right |

Some platform blocks have **divider rows** containing repeated header text
(`Referees\n(L, C, R)`) that split the block into two referee groups. The
parser filters these out and resets the position counter after each divider.

## Marshal position (Chief/Assistant) — row order

Same pattern. First marshal entry in the block = Chief, subsequent = Assistant.

| pos_in_block | Position |
|---|---|
| 0 | Chief |
| 1+ | Assistant |

Marshal column also has divider rows (`Chief Marshal\nAssist. Marshal`)
that are filtered and reset the counter.

## Certification tags (parenthetical in cell value)

These appear in parentheses after the name: `The User (NAT)`. The `tag`
field in the assignment dict captures the content inside the parens.

| Tag | Meaning |
|---|---|
| `(L)` | Local referee |
| `(NAT)` | National TO |
| `(IWF 1)` | IWF Category 1 |
| `(IWF 2)` | IWF Category 2 |
| `(T CAT 1)` / `(T CAT2)` | Technical official category |
| `(T NAT)` | Technical National |
| `(ROOM N, ...)` | Room assignment + session category |

**`(L)` = Local certification — NOT Left referee position.** This was
confused once. Position comes from `pos_in_block` (row order), not the tag.

## Divider row detection

Divider rows repeat the column header text. Detected by checking for
these markers (lowercase):

```python
DIVIDER_MARKERS = ("referees", "chief marshal", "assist. marshal")
```

When a divider is encountered while counting position:
- Skip it (don't count as a person)
- Reset `pos_in_block = 0` (next entry starts a new group)