# USAW Event Info — Test Coverage Gap Analysis

Generated 2026-07-08. Exhaustive mapping of all source code paths to existing tests,
identifying every untested branch, edge case, and boundary condition.

## Source Files Analyzed

| File | Lines | Test Files |
|------|-------|-----------|
| `usaw_event_extractor.py` | 813 | `test_extractor.py`, `test_extractor_mock.py`, `test_extractor_units.py` |
| `usaw_results_parser.py` | 908 | `test_results_parser.py`, `test_coverage_expansion.py` |
| `usaw_event_info_sync.py` | ~298 | `test_page_health.py`, `test_coverage_expansion.py` |

## usaw_event_extractor.py — Untested Paths

### rapidfuzz fallback (lines 40–51)
`rapidfuzz` import failure triggers `difflib`-based `_FuzzFallback`. No test disables rapidfuzz.

### `_resolve_url()` edge cases (lines 350–354)
- Protocol-relative URLs (`//cdn.example.com`) pass through unchanged
- Relative URLs with query/hash anchors (`?foo=bar`, `#section`) not tested

### `_clean_link_text()` (lines 357–359)
Only the `", opens in a new tab"` branch tested. Other comma/spacing variants not explicitly tested.

### `_find_section_containers()` (lines 362–397)
No direct tests for: H2 with no parent, nested H2 beyond 5 ancestors, multiple H2s with same text, H2 inside footer/nav.

### `_extract_links_from_element()` (lines 400–484)
- TBA/TBD detection branch used in integration tests but not isolated
- Duplicate URL dedup with same URL different text only partially tested

### `extract_all_links()` fallback loop (lines 514–560)
- The `main`/`body` catch-all loop used by VWS1 tests but no isolated boundary test
- No test for page where `soup.find("main")` is `None` but `body` exists

### `extract_event_title_and_overview()` (lines 597–627)
No test for: multiple pipe-separated overview lines, missing venue, malformed dates, H1 absent branch returning empty dict. `test_coverage_expansion.py` covers basic cases.

### `format_markdown()` (lines 711–789)
No test for: empty title, empty `info_by_type`, unclassified section rendering, `--verbose` flag stripping behavior, status emojis for TBA/missing. `test_coverage_expansion.py` covers basic cases only.

### `main()` CLI (lines 794–810)
The `argparse` path, `--json`, `--markdown`, `--verbose`, and unclassified stripping regex are never executed in tests.

### Network fetch path in `extract_event_page()` (lines 663–670, 32–36)
Live tests exercise it indirectly, but timeout, HTTP error, non-200 status, and missing `requests` import branch are not tested.

### Boundary conditions
- `INFO_TYPES` lookup with empty `header_text` and empty `url` returns `None` (line 330–331) — not directly tested
- Fuzzy score exactly at threshold (60) — no test
- `fuzz.partial_ratio` vs `fuzz.ratio` choice — only partial_ratio is used; no test for ratio fallback
- `classify_info_type` returning first `url_matches[0]` when no header match (line 327) — not isolated

## usaw_results_parser.py — Untested Paths

### `detect_pdf_type()` (lines 50–81)
- `len(doc) == 0` returns `unknown` — no test
- Ambiguous overlaps: PDF containing both "Best Lifters" and "Age Group" would return `best_lifters` (order matters) but no test verifies order

### `parse_full_results()` (lines 94–281)
- Empty or single-page PDF with no Age Group headers falls through — no test
- Multi-line header logic (lines 131–147) exercised by fixtures but no synthetic test
- Column skip list tokens never individually validated
- 1-rank DNF pattern (lines 192–206) not covered by DNF tests
- DNF block with no lot found (lines 237–238) not tested
- DNF-only athlete with 1–2 DNF lines (lines 243–271) not tested

### `parse_athlete_lines()` (lines 284–417)
- `< 5 vals` returns `None` — no test for exactly 4 vals or malformed name
- `AGE_GROUP_HEADER` stop not tested in isolation
- `score` field (line 414–415) not asserted in any test

### `parse_final_schedule()` (lines 426–554)
- Condensed format with `vals[5] in PLATFORM_NAMES` (lines 488–501) not isolated
- WSO age groups only integration test; no synthetic WSO session test
- Sessions rejected by `gender_ok` / `weight_cat_ok` / `entry_ok` silently skipped — no test asserts rejection

### `parse_best_lifters()` (lines 561–609)
- `len(doc) == 0` path not tested
- Names with apostrophes/hyphens, missing total/score not tested

### `parse_start_list()` (lines 618–685)
- Name detection requires comma; athlete without comma is skipped — not tested
- Numeric break logic (lines 646–647) not isolated

### Google Drive functions (lines 692–742)
`download_drive_file()` and `list_drive_folder()` entirely untested (no network mocks).

### `classify_file_name()` (lines 749–778)
Only `full_results`, `start_list`, `best_lifters`, `medal_schedule`, `unknown` tested. `teams`, `registered_teams`, `glen_middleton` untested.

### `main()` CLI (lines 846–905)
All argparse branches untested.

### Missing `fitz` import branch (lines 39–43)
`except ImportError` exit path not tested.

### Boundary conditions
- Athlete lot = 0 or lot > 2000 handling
- Bodyweight/age values that are non-numeric or missing
- Total exactly 0 vs DNF semantics
- Empty PDF (0 pages) in `parse_pdf()`
- PDF with only headers and no athletes

## usaw_event_info_sync.py — Untested Paths

### `run_extractor()` (lines 38–51)
- `subprocess.run` non-zero returncode raises `RuntimeError` — no test
- `json.loads(result.stdout)` on empty/invalid stdout not tested
- `_health_warnings` added when `check_page_health` returns unhealthy — no direct test

### `check_page_health()` (lines 62–67)
- Exactly 4 links (threshold is `< 5`) — no boundary test
- `{"sections": None}` not tested

### `simplify_event()` (lines 84–111)
- `simplify_event(None)` would crash on `.get()` — not tested

### `diff_events()` (lines 119–149)
- Only added URLs/types tested; removal branches not covered
- Fees/milestones/status changes in `simplify_event` but not compared in `diff_events`
- Old dict missing individual keys not tested

### `run_test_suite()` (lines 152–167)
- `--with-live-tests` branch not tested

### `update_meet_ids_reference()` (lines 186–221)
- Reference file missing returns `[]` — not tested
- 3-digit or 7-digit meet IDs not tested (regex `\d{4,6}`)
- Non-registration Sport80 URLs only partially tested

### `main()` (lines 224–298)
- Entire daily-sync orchestration loop untested
- `--dry-run` path not tested
- Error carry-forward branch (lines 249–251) not tested
- Test failure summary printing (lines 287–291) not tested
- Meet ID drift summary printing (lines 274–277) not tested

### Boundary conditions
- `EVENTS_2026` list empty
- `SNAPSHOT_FILE` exists but contains invalid JSON
- `REPORT_FILE` write fails due to permissions
- `subprocess.run` timeout (120s / 300s)

## Integration Gaps

- End-to-end sync script (`usaw_event_info_sync.main()`) tested only at function level, never as full pipeline
- Extractor + sync interaction: no test verifies extractor JSON output is consumable by `simplify_event` and `diff_events` together
- Google Drive download + results parser: no integration test downloads a file and parses it
- `--refresh` fixture path in `test_extractor_mock.py` not tested
- Live network tests depend on external USAW pages; no contract test isolates expected HTML structure

## Already Covered (for reference)

- `classify_sport80_url()`: 4 Sport80 patterns + 2 negative cases
- `_is_nav_link()`: 6 cases
- `extract_inline_metadata()`: fees, flat fees, dates, milestones, empty text
- `classify_info_type()`: many info types + header_priority disambiguation
- `extract_event_page()`: 11 events across live + mock tests
- `detect_pdf_type()`: 4 PDF types
- `parse_full_results()` / `parse_best_lifters()` / `parse_start_list()` / `parse_final_schedule()`: structure tests against real fixtures
- `parse_athlete_lines()`: 3 DNF layout cases
- `check_page_health()`: 5 tests
- `simplify_event()` / `diff_events()` / `load_snapshot()` / `save_snapshot()` / `update_meet_ids_reference()` / `run_test_suite()`: covered in `test_coverage_expansion.py`
- `classify_file_name()` / `format_summary()`: covered in `test_coverage_expansion.py`
