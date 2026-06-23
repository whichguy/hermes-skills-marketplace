---
name: usaw-meet-card-parser
description: 'Parse USAW weightlifting meet cards: athlete name, attempts, totals,
  results. Includes Google Maps links for venue/hotel and USAW meet card deep-links.'
version: 1.0.0
tags:
- usaw
- weightlifting
- meet
- athlete
- attempts
- results
platforms:
- linux
- macos
- windows
author: Fortified Strength
license: MIT
metadata:
  hermes:
    config:
    - key: usaw-meet-card-parser.enabled
      description: Enable usaw-meet-card-parser skill behavior
      default: true
      prompt: Enable usaw-meet-card-parser skill?
    tags:
    - usaw
    category: productivity
---
---

# USAW Meet Card Parser

Parse USAW competition meet cards to extract athlete name, declared attempts, weights, and results. Works with the 2026 NCW National Championships and any USAW event.

## NCW 2026 Logistics (Jim & Kelly)

| | |
|---|---|
| **Venue** | [Ed Robson Arena, 849 N Tejon St, Colorado Springs CO 80903](https://maps.google.com/?q=849+N+Tejon+St,+Colorado+Springs,+CO+80903) |
| **Parking garage** | [110 E Dale St](https://maps.google.com/?q=110+E+Dale+St+Colorado+Springs+CO+80903) (attached) |
| **Hotel** | [Hyatt Regency Colorado Springs, 502 N Nevada Ave](https://maps.google.com/?q=Hyatt+Regency+Colorado+Springs,+502+N+Nevada+Ave,+Colorado+Springs,+CO+80903) |
| **Water/grocery** | [King Soopers, 315 N Nevada Ave](https://maps.google.com/?q=King+Soopers+315+N+Nevada+Ave+Colorado+Springs+CO) (on the route to Hyatt) |
| **Transport** | Kelly's SUV — both Jim and Kelly |
| **Sessions end** | ~10 PM MT most days (Jun 20–27); Jun 28 ends ~4 PM |
| **Water reminder** | Google Calendar popup at 9:30 PM each night (30 min before wrap) |
| **Timezone** | All times Mountain Time (MT) |

| Resource | Link |
|---|---|
| 🏟️ Ed Robson Arena (venue) | https://maps.google.com/?q=849+N+Tejon+St,+Colorado+Springs,+CO+80903 |
| 🏨 Hyatt Regency Colorado Springs | https://maps.google.com/?q=Hyatt+Regency+Colorado+Springs+502+N+Nevada+Ave |
| 🛒 Nearest grocery (water/snacks) | https://maps.google.com/?q=grocery+store+near+849+N+Tejon+St+Colorado+Springs+CO |
| 🏆 USAW 2026 Nationals event page | https://www.usaweightlifting.org/2026-national-championships |
| 📊 USAW lifting results / meet cards | https://www.iwf.sport/results/ |
| 📋 Goodlift results database | https://goodlift.info |
| 🎥 Live stream | https://maestro.tv/usaw |

## References

- `references/to-assignment-lookup.md` — correct pattern for looking up TO assignments from the live xlsx (snapshot JSON has empty person fields — always use xlsx directly). Includes assignment dict field reference.
- `references/to-sheet-structure.md` — TO sign-up sheet column layout, referee position (L/C/R by row order), marshal position (Chief/Assistant by row order), certification tag meanings, divider row detection.

## Meet Card Deep-Link Pattern

USAW uses Goodlift for official results. To link directly to an athlete's meet card:

```
https://goodlift.info/competition-athlete.php?cid=<COMPETITION_ID>&lid=<ATHLETE_ID>
```

For 2026 NCW, the competition ID will be published on Goodlift once results go live.
Search an athlete by name:
```
https://goodlift.info/athletes.php?name=<URL_ENCODED_NAME>
```

Example: `https://goodlift.info/athletes.php?name=James+Wiese`

## Parsing Meet Cards

### From PDF / printed card

A USAW meet card contains:
- Athlete name, bodyweight, lot number, category
- Snatch: attempts 1, 2, 3 (declared → result: ✓ good lift / ✗ no lift)
- Clean & Jerk: attempts 1, 2, 3
- Total, Sinclair/Robi score

### Python parser (from PDF or text)

```python
import re

def parse_meet_card(text: str) -> dict:
    """
    Parse raw text from a USAW meet card (PDF-extracted or OCR'd).
    Returns structured dict with athlete info and attempts.
    """
    result = {
        "name": None, "category": None, "bodyweight": None,
        "lot": None, "club": None,
        "snatch":  {"a1": None, "a2": None, "a3": None, "best": None},
        "cj":      {"a1": None, "a2": None, "a3": None, "best": None},
        "total":   None, "sinclair": None,
    }

    # Name (usually ALL CAPS on meet card)
    m = re.search(r"^([A-Z][A-Z ,'-]+)$", text, re.MULTILINE)
    if m: result["name"] = m.group(1).strip().title()

    # Category e.g. "56kg", "73kg", "81+kg"
    m = re.search(r"\b(\d{2,3}(?:\+)?kg)\b", text, re.IGNORECASE)
    if m: result["category"] = m.group(1).lower()

    # Bodyweight
    m = re.search(r"BW[:\s]+(\d+\.?\d*)", text, re.IGNORECASE)
    if m: result["bodyweight"] = float(m.group(1))

    # Lot number
    m = re.search(r"Lot[:\s#]+(\d+)", text, re.IGNORECASE)
    if m: result["lot"] = int(m.group(1))

    # Attempts: look for 3 consecutive weights in kg (e.g. 100 / 105 / 107)
    # Snatch block
    snatch = re.search(
        r"(?i)snatch.*?(\d{2,3})\s*[/|]\s*(\d{2,3})\s*[/|]\s*(\d{2,3})", text)
    if snatch:
        w = [int(snatch.group(i)) for i in (1,2,3)]
        result["snatch"] = {"a1": w[0], "a2": w[1], "a3": w[2],
                            "best": max(w)}  # replace with actual good lifts if known

    # Clean & Jerk block
    cj = re.search(
        r"(?i)clean.*?(\d{2,3})\s*[/|]\s*(\d{2,3})\s*[/|]\s*(\d{2,3})", text)
    if cj:
        w = [int(cj.group(i)) for i in (1,2,3)]
        result["cj"] = {"a1": w[0], "a2": w[1], "a3": w[2],
                        "best": max(w)}

    # Total
    m = re.search(r"Total[:\s]+(\d{2,3})", text, re.IGNORECASE)
    if m: result["total"] = int(m.group(1))

    return result


def format_meet_card(card: dict) -> str:
    """Format a parsed meet card for display in Telegram/WhatsApp."""
    s = card["snatch"]
    c = card["cj"]
    lines = [
        f"🏋️ **{card['name'] or 'Unknown'}**",
        f"📦 {card['category'] or '?'}  BW: {card['bodyweight'] or '?'} kg  Lot: {card['lot'] or '?'}",
        f"",
        f"**Snatch:**  {s['a1']} / {s['a2']} / {s['a3']}  → best: {s['best']} kg",
        f"**C&J:**     {c['a1']} / {c['a2']} / {c['a3']}  → best: {c['best']} kg",
        f"**Total:**   {card['total'] or '?'} kg",
    ]
    if card.get("sinclair"):
        lines.append(f"**Sinclair:** {card['sinclair']}")
    # Goodlift link
    if card.get("name"):
        name_enc = card["name"].replace(" ", "+")
        lines.append(f"")
        lines.append(f"📋 Meet card: https://goodlift.info/athletes.php?name={name_enc}")
    return "\n".join(lines)
```

### From Goodlift website (live results)

```python
import requests
from bs4 import BeautifulSoup

def fetch_goodlift_athlete(name: str, comp_id: str = None) -> str:
    """Fetch athlete results from Goodlift. Returns formatted card."""
    url = f"https://goodlift.info/athletes.php?name={name.replace(' ', '+')}"
    resp = requests.get(url, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")
    # Parse the results table — structure varies by competition
    rows = soup.select("table.results tr")
    results = []
    for row in rows[1:]:
        cols = [c.get_text(strip=True) for c in row.find_all("td")]
        if cols: results.append(cols)
    return results
```

## Workflow: TO looking up an athlete

1. **During weigh-in** — athlete declares opening attempts on the card
2. **Look up on Goodlift:**
   ```
   https://goodlift.info/athletes.php?name=Firstname+Lastname
   ```
3. **Session/platform sheet** — cross-reference with NCW schedule:
   ```
   https://docs.google.com/spreadsheets/d/1KbXx2eJ1JxN6933lPkD48CHmYTBWS8-Z/edit
   ```
4. **Live results during competition:**
   ```
   https://maestro.tv/usaw
   ```

## Google Maps Links

Always include these for NCW 2026:

```python
MAPS = {
    "venue":   "https://maps.google.com/?q=849+N+Tejon+St,+Colorado+Springs,+CO+80903",
    "hotel":   "https://maps.google.com/?q=Hilton+Garden+Inn+Colorado+Springs+Downtown",
    "grocery": "https://maps.google.com/?q=King+Soopers+315+N+Nevada+Ave+Colorado+Springs",
    "parking": "https://maps.google.com/?q=110+E+Dale+St+Colorado+Springs+CO+80903",
}
```

Parking garage entrance: 110 E Dale St (attached to Ed Robson Arena).

## Pitfalls

- **`assignments_snapshot.json` has empty `person` fields** — the snapshot stores session structure but names are NOT saved in it. The change-watcher diffs names from live xlsx cells directly. To look up all Wiese (or any TO's) assignments, call `parse_assignments(xlsx_path=L.XLSX_PATH, names=None)` directly against the live xlsx at `L.XLSX_PATH` (`/opt/data/cron_state/usaw_to/to_signup.xlsx`), NOT the snapshot JSON.
- **Snapshot vs. live xlsx:** `assignments_snapshot.json` = structure only (zero `person` values). `to_signup.xlsx` = full live data with names. Always use xlsx for name lookups.
- Goodlift athlete IDs change per competition — use name search, not hardcoded IDs
- PDF meet cards often have inconsistent spacing — normalize whitespace before parsing
- "Best" attempt = highest successful lift, not highest declared — check ✓/✗ markers
- Bodyweight is recorded at weigh-in, may differ from category limit
- USAW uses MT (Mountain Time) for all session times at NCW
