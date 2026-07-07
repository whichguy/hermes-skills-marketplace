# Wiki Lint Script

Automated wiki health check. The standalone script lives at
`${HERMES_HOME}/scripts/wiki_lint.py` and can be run manually or as a cron precheck.

## Usage

```bash
# Human-readable report (default)
python3 ${HERMES_HOME}/scripts/wiki_lint.py

# Exit non-zero on broken links or missing frontmatter (CI mode)
python3 ${HERMES_HOME}/scripts/wiki_lint.py --strict

# JSON output for machine consumption
python3 ${HERMES_HOME}/scripts/wiki_lint.py --json
```

## What it checks

1. **Broken wikilinks** — `[[links]]` pointing to pages that don't exist.
   - Handles pipe-alias syntax: `[[page|alias]]` → strips alias before checking.
   - Filters example/illustrative terms (`wikilink`, `wikilinks`, `wiki-links`, `page`, `page-name`)
     so prose examples don't false-positive.
   - Skips `index.md`, `SCHEMA.md`, `log.md`, `queue.md` for link checking (they contain
     syntax examples and historical entries, not real links).
2. **Orphan pages** — pages with zero inbound links (informational, not an error).
3. **Missing frontmatter** — pages without YAML frontmatter starting with `---`.
4. **Stale pages** — `updated:` date > 90 days ago.
5. **Oversized pages** — pages exceeding 200 lines (SCHEMA.md threshold).
6. **Index completeness** — pages not listed in `index.md`.
7. **Index page count** — compares curated page count vs total .md files.

## Design decisions

- **Silent on clean, speaks up on issues** — same watchdog pattern as all Hermes crons.
- **Raw sources excluded from broken-link checking** — `raw/articles/*.md` files are
  immutable sources, not wiki pages. They can be orphans without it being a problem.
- **Stale threshold configurable** — `STALE_THRESHOLD_DAYS = 90` at top of script.
- **Size threshold configurable** — `SIZE_THRESHOLD_LINES = 200` at top of script.

## After lint

- Fix broken links by creating stub pages or downgrading to plain text
- Fix orphans by adding `[[wikilinks]]` from related pages (only for curated pages,
  not raw sources)
- Fix missing frontmatter by adding the required fields
- Add missing pages to `index.md`
- Append a log entry: `## [YYYY-MM-DD] lint | N issues found`