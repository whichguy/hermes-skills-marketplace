# Drive briefing precheck pattern

Use this when a recurring briefing includes Google Drive or document changes.

## Goal

Avoid noisy or speculative Drive sections. The briefing should tell the user only about Drive changes the run is actually aware of, and should summarize inspected file contents/changes rather than titles alone.

## Precheck shape

Emit compact structured records for candidates only:

- account alias/provenance (`personal`, `nonprofit`, etc.)
- file id
- file name
- MIME type
- modified time
- web link
- cutoff timestamps used for the query

Recommended candidate classes:

- Recently changed: `modifiedTime > <short cutoff> and trashed = false`
- Recently shared/recently modified shared: `sharedWithMe = true and modifiedTime > <longer cutoff> and trashed = false`

Use explicit account routing. For multi-account setups, query each account or use connector-supported aggregate reads that preserve provenance.

## Prompt requirements

Add briefing instructions like:

- Only consider Drive files surfaced by the precheck as recently changed or recently shared/recently modified shared.
- Tell the user only about Drive changes you are actually aware of from this run.
- Look at candidate files when practical and summarize observed content/changes in your own words.
- If a candidate cannot be inspected safely, omit it or clearly label it as metadata-only.
- Never imply knowledge of file contents from title/metadata alone.
- Do not quote raw Drive text, large excerpts, sensitive identifiers, credentials, or raw document contents.

## Pitfalls

- Metadata such as a modified timestamp proves only that something changed, not what changed.
- Drive search may return automation/state files; the LLM should omit low-value files unless they are relevant to the user's briefing goals.
- Binary files may not be safely readable; do not fake summaries for them.
