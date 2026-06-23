# Governance hardening: manifest + verify_all

Use this pattern after a personal-context workflow grows beyond a few files or after a lessons-learned review finds verification drift.

## Problem this prevents

Verification summaries can become stale if regression test source files disappear while `__pycache__` remains. A bare `python -m unittest -v` can report `Ran 0 tests` and still be missed if the workflow only checks command exit or old status text.

## Pattern

Create a local fail-closed governance layer:

- `manifest.yaml` — machine-readable list of canonical files, scripts, expected test source files, privacy guards, permission policy, and retention classes.
- `verify_all.py` — one-command verifier that reads the manifest and fails closed when expected files/tests are missing or when safety gates are violated.
- restored/maintained `test_*.py` source files — never rely on `__pycache__` as evidence that tests exist.

## Minimum manifest checks

`verify_all.py` should fail if:

1. `manifest.yaml` is missing or malformed.
2. Any manifest-required canonical file is missing.
3. Any manifest-required script is missing.
4. Any manifest-required test source file is missing.
5. A required test is not a Python source file.
6. The unit-test runner reports zero tests.

## Minimum privacy/side-effect checks

For personal-context work, `verify_all.py` should also fail if:

- candidate third-party edges grant disclosure permission;
- candidate or reviewed third-party edges grant memory-write permission;
- third-party cluster proposals are not review-only;
- sensitive clusters are not marked manual-review-only / do-not-promote-from-metadata;
- important-contact watcher defaults are enabled without separate approval;
- pending contacts can affect alerts or watcher behavior;
- approved important contacts grant memory/disclosure permissions without separate approval;
- forbidden raw/source-text keys appear in JSON-compatible local artifacts.

## YAML compatibility pitfall

Some local files such as `approved-context.yaml` may be human YAML rather than JSON-compatible YAML, while other reviewed files are JSON-compatible YAML. If the environment lacks a YAML parser, do not force JSON parsing of human-YAML files in the verifier. Instead:

- parse JSON-compatible policy-bearing files with `json.loads`;
- scan human-YAML files for forbidden raw markers (`raw_snippet:`, `raw_body:`, `document_text:`, `password:`, `token:`, `account_number:`, `confirmation_number:`);
- keep the canonical schema validator responsible for JSON-compatible reviewed files.

## Permission checks

Keep local posture restrictive:

```bash
chmod 700 /opt/data/personal-context
chmod 600 /opt/data/personal-context/*
chmod 700 /opt/data/personal-context/*.py   # only for scripts meant to execute directly
```

The verifier should fail on group/world-readable or writable files unless explicitly justified.

## Safe-edit pitfall: patch truncation on test files

When editing canonical files in this workspace (`resolve_engagement.py`,
`validate_personal_context.py`, `test_*.py`), a fuzzy-match `patch` whose
`old_string` fails to match cleanly has, in practice, **zeroed/truncated the
target file** — twice in one session it wiped `test_resolve_engagement.py` and
`test_identity_mapping.py` to 0 bytes. Defenses:

1. **Back up canonical/test files first** into `archive/<tag>-<TS>-<name>` before a
   run of edits (you already do this for `people.yaml`-class files — extend it to
   the resolver/validator/tests).
2. For **whole-file or large rewrites of test files, prefer `write_file`** over
   `patch`; reserve `patch` for small, uniquely-anchored hunks.
3. **Immediately re-read / `wc -l` the file after each edit**; if it's gone or
   0 bytes, restore from the latest `archive/` copy and retry with `write_file`.
4. After restoring, **re-run `run_personal_context_tests.py`** before trusting the
   suite — a vanished test module silently drops coverage (`verify_all` catches
   zero-test discovery, but only if you run it).

## Status/audit update

After implementing hardening, update `STATUS.md` and append a non-sensitive `audit-log.jsonl` event with:

- approval source/scope;
- files changed and hashes;
- verification output summary;
- explicit side-effect statement: no memory writes, no cron changes, no watcher enablement, no disclosure-permission changes.

## Good completion signal

A strong final verification includes both:

```text
Ran N tests
OK
```

and:

```text
manifest_checks=passed ...
personal_context_validator=passed
unit_tests=passed unit_tests_ran=N
side_effect_checks=passed
permission_checks=passed
verify_all=passed
```
