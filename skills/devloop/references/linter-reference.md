# Linter Reference — devloop `lint.py`

> **Purpose:** The authoritative catalog of file types devloop's lint gate knows about, the
> linters wired for each, which are runnable in THIS environment, and which linters exist in
> the ecosystem for files we don't cover yet. Update this file when adding a language to
> `lint.py`'s `_LANGUAGES` table or when discovering a new file type the coder produces.

## How the lint gate works

`lint.py` maps file extensions → ordered linter builders. After the coder writes files,
`lint_paths()` runs the mapped linters on EXACTLY the changed files using real subprocess
exit codes. Design principles:

- **Syntax/error-scoped, NOT style** — unconventional-but-valid code is never punished.
- **Skip, never fail-close** on missing tools — an unmapped type or uninstalled linter is
  recorded as "skipped", not a failure.
- **`discover()` reports gaps** — coverage holes are visible, never silent.

The gate runs in `loop.py`'s `_lint_gate()` after IMPLEMENT and before evidence. A CONFIRMED
linter failure feeds errors back to the coder and forces a rebuild.

## Current coverage (as of 2026-07-08)

### Wired linters in `lint.py` `_LANGUAGES`

| Extensions | Linters (ordered) | Available in this env? | Scope |
|---|---|---|---|
| `.py` | `py-syntax` (compile), `pyflakes`, `ruff` (E9,F821,F822,F823), `mypy` (ERROR-only) | ✅ all four | syntax + undefined names + type errors |
| `.json` | `json.tool` (stdlib) | ✅ always | JSON validity |
| `.yaml`, `.yml` | `pyyaml` (safe_load_all) | ✅ PyYAML installed | YAML validity |
| `.js`, `.jsx`, `.mjs`, `.cjs` | `node --check` | ✅ node v22 | JS syntax parse |
| `.toml` | `tomllib` (stdlib) | ✅ Python 3.11+ | TOML validity |
| `.xml` | `xml.etree` (stdlib) | ✅ Python 3.11+ | XML well-formedness |
| `.ini`, `.cfg`, `.conf` | `configparser` (stdlib) | ✅ Python 3.11+ | INI parse validity |
| `.sh`, `.bash` | `bash -n` | ✅ bash available | shell syntax |
| `Makefile`, `.mk` | `make -n` | ✅ make available | Makefile parse |
| `.c`, `.h` | `gcc -fsyntax-only` | ✅ gcc 14.2 | C syntax |
| `.cpp`, `.hpp` | `g++ -fsyntax-only` | ✅ g++ 14.2 | C++ syntax |
| `.sql` | `sqlparse` | ✅ sqlparse installed | SQL syntax |
| `Dockerfile` | `docker --check` | ✅ docker available | Dockerfile syntax |
| `.ts`, `.tsx` | `tsc --noEmit` | ❌ tsc not installed | TS type-check |
| `.css`, `.scss`, `.less` | `stylelint` | ❌ not installed | CSS lint |
| `.html`, `.htm` | `htmlhint` | ❌ not installed | HTML lint |

### ✅ Fixed: ruff discovery (2026-07-08)

`_on_path()` now uses `_resolve_exe()` which checks `sys.prefix/bin` and `/opt/data/.venv/bin`
in addition to `shutil.which()`. Ruff is now correctly discovered and runs on every `.py` file.

### ✅ Fixed: extensionless file handling (2026-07-08)

`_file_key()` now checks the basename (e.g., `Makefile`, `Dockerfile`) in addition to the
extension, so files without extensions are correctly routed to their linters.

### Environment inventory (this container)

| Tool | Installed? | Location / install method |
|---|---|---|
| Python 3.13.5 | ✅ | system |
| py-syntax (compile) | ✅ | stdlib, always |
| ruff 0.15.20 | ✅ | `/opt/data/.venv/bin/ruff` (via `uv`) |
| mypy 2.1.0 | ✅ | via `uv run mypy` |
| pyflakes 3.4.0 | ✅ | `/opt/data/.venv/bin/pyflakes` (via `uv`) |
| node v22.22.3 | ✅ | `/usr/local/bin/node` |
| gcc 14.2.0 | ✅ | system (C/C++ compile) |
| PyYAML | ✅ | installed in venv (2026-07-08) |
| sqlparse | ✅ | installed in venv (2026-07-08) |
| tomllib | ✅ | stdlib (Python 3.11+) |
| configparser | ✅ | stdlib |
| xml.etree.ElementTree | ✅ | stdlib |
| docker | ✅ | `/usr/bin/docker` |
| make | ✅ | `/usr/bin/make` |
| cmake | ✅ | `/usr/bin/cmake` |
| tsc | ❌ | `npm install -g typescript` |
| shellcheck | ❌ | `apt install shellcheck` |
| stylelint | ❌ | `npm install -g stylelint` |
| htmlhint | ❌ | `npm install -g htmlhint` |
| eslint | ❌ | `npm install -g eslint` |
| prettier | ❌ | `npm install -g prettier` |
| go | ❌ | — |
| rustc/cargo | ❌ | — |
| ruby | ❌ | — |
| php | ❌ | — |
| java/javac | ❌ | — |

## File types devloop produces

### Always produced (every run)

| File | Type | Linted? | Notes |
|---|---|---|---|
| `test_devloop_dod_<slug>.py` | Python | ✅ py-syntax + ruff | Rendered oracle (render.py) |
| Coder implementation files | Python (primary) | ✅ py-syntax + ruff | Whatever the coder writes |
| `charter.json` | JSON | ✅ json.tool | Persisted by loop.py |
| `design_spec.json` | JSON | ✅ json.tool | Persisted by loop.py |
| `judge_verdicts.json` | JSON | ✅ json.tool | Persisted by loop.py |
| `grounding.json` | JSON | ✅ json.tool | Persisted by loop.py |
| `rendered_tests.json` | JSON | ✅ json.tool | Persisted by loop.py |
| `trace.jsonl` | JSONL | ✅ json.tool (per line) | Append-only trace |
| `progress.jsonl` | JSONL | ✅ json.tool (per line) | Append-only progress |
| `attempts.jsonl` | JSONL | ✅ json.tool (per line) | Per-attempt record |
| `commit_scope.json` | JSON | ✅ json.tool | Persisted by loop.py |
| `overfit_audit.json` | JSON | ✅ json.tool | Persisted by loop.py |
| `checkpoint.json` | JSON | ✅ json.tool | State checkpoint |

### Potentially produced (coder output depends on request)

The coder can write ANY file type the request asks for. Current lint coverage:

| File type | Extensions | Wired? | Available? | Recommended linters |
|---|---|---|---|---|
| Python | `.py` | ✅ | ✅ | `py-syntax`, `ruff` (current); **add** `mypy` for type-checking, `pyflakes` for additional checks |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` | ✅ | ✅ | `node --check` (current); **add** `eslint` for semantic checks |
| TypeScript | `.ts`, `.tsx` | ✅ | ❌ | `tsc --noEmit` (current); **add** `eslint` with `@typescript-eslint` |
| JSON | `.json` | ✅ | ✅ | `json.tool` (current, sufficient) |
| YAML | `.yaml`, `.yml` | ✅ | ❌ | `pyyaml` (current); **add** `yamllint` for style |
| CSS | `.css`, `.scss`, `.less` | ✅ | ❌ | `stylelint` (current) |
| HTML | `.html`, `.htm` | ✅ | ❌ | `htmlhint` (current) |
| TOML | `.toml` | ✅ | ✅ (stdlib `tomllib`) | `tomllib` — Python 3.11+ stdlib |
| XML | `.xml` | ✅ | ✅ (stdlib `xml.etree`) | `xml.etree.ElementTree.parse()` |
| INI/CFG | `.ini`, `.cfg`, `.conf` | ✅ | ✅ (stdlib `configparser`) | `configparser.read()` |
| Shell | `.sh`, `.bash` | ✅ | ✅ (`bash -n`) | `bash -n` (syntax); **add** `shellcheck` when installed for semantic checks |
| SQL | `.sql` | ✅ | ✅ (sqlparse via uv) | `sqlparse.parse()` for syntax validation |
| Dockerfile | `Dockerfile` | ✅ | ✅ (`docker build --check`) | `docker build --check` (dry-run syntax); **add** `hadolint` when installed for best-practice checks |
| Makefile | `Makefile`, `.mk` | ✅ | ✅ (`make -n`) | `make -n` (dry-run parse) |
| Markdown | `.md`, `.markdown` | ❌ | ❌ | **Add** `markdown-it` or `mdformat` (syntax/structure); `markdownlint` for style |
| Go | `.go` | ❌ | ❌ | **Add** `gofmt -l` (syntax); `golangci-lint` when installed |
| Rust | `.rs` | ❌ | ❌ | **Add** `rustc --edition 2021 --crate-type lib` (syntax); `cargo check` when installed |
| C/C++ | `.c`, `.h`, `.cpp`, `.hpp` | ✅ | ✅ (gcc/g++) | `gcc -fsyntax-only` (C), `g++ -fsyntax-only` (C++) |
| Ruby | `.rb` | ❌ | ❌ | **Add** `ruby -c` (syntax) when installed |
| PHP | `.php` | ❌ | ❌ | **Add** `php -l` (syntax) when installed |
| Java | `.java` | ❌ | ❌ | **Add** `javac -Xlint` when installed |
| Env/Properties | `.env`, `.properties` | ❌ | ✅ (configparser) | **Add** `configparser` for `.properties`; basic line-format check for `.env` |

## Recommended additions to `lint.py`

Priority-ordered. Each is a `(extensions, [builders])` row in `_LANGUAGES`.

### ✅ P0: Fix ruff discovery (bug) — DONE 2026-07-08

`_on_path()` now uses `_resolve_exe()` which checks `sys.prefix/bin` and `/opt/data/.venv/bin`
in addition to `shutil.which()`. Ruff is now correctly discovered.

### ✅ P1: Add stdlib-only linters — DONE 2026-07-08

All five stdlib-only linters are now wired: `tomllib`, `xml.etree`, `configparser`, `bash -n`, `make -n`.

### ✅ P2: Add uv-installable linters — DONE 2026-07-08

PyYAML and sqlparse are now installed in the venv. YAML and SQL linters are functional.

### ✅ P1 (additional): Add mypy as second Python linter — DONE 2026-07-08

`mypy` is now wired after ruff in the `.py` linter chain, scoped to ERROR-only (not style).

### ✅ P2 (additional): Add Dockerfile linter — DONE 2026-07-08

`docker build --check` is now wired for `Dockerfile` (extensionless file handling fixed via `_file_key()`).

### P3: Add npm-installable linters (when node is present)

| Extension(s) | Builder | Linter name | Install |
|---|---|---|---|
| `.js`, `.jsx`, `.mjs`, `.cjs` | `_eslint` | `eslint` | `npm install -g eslint` |
| `.css`, `.scss`, `.less` | `_stylelint` (already wired) | `stylelint` | `npm install -g stylelint` |
| `.html`, `.htm` | `_htmlhint` (already wired) | `htmlhint` | `npm install -g htmlhint` |

### P4: Add compile-check linters (when compiler is present)

| Extension(s) | Builder | Linter name | Method |
|---|---|---|---|
| `.cpp`, `.hpp` | `_gpp_syntax` | `g++ -fsyntax-only` | `g++ -fsyntax-only -Wall <path>` |
| `.go` | `_go_fmt` | `gofmt` | `gofmt -l <path>` (exit 1 if needs formatting) |
| `.rs` | `_rustc_syntax` | `rustc --check` | `rustc --edition 2021 --crate-type lib <path>` |
| `.rb` | `_ruby_syntax` | `ruby -c` | `ruby -c <path>` |
| `.php` | `_php_syntax` | `php -l` | `php -l <path>` |

### P5: Special files

| File pattern | Builder | Linter name | Method |
|---|---|---|---|
| `.md`, `.markdown` | `_markdown_syntax` | `mdformat` | `mdformat --check <path>` (via uv) |

## Adding a new linter to `lint.py`

1. Write a builder function `_<name>()` returning `{"name", "available", "argv"}`.
   - `available()` → `True` iff the tool/module is usable HERE.
   - `argv(path)` → the command list to run (exit 0 = clean, nonzero = failure).
2. Add a `(extensions, [builders])` row to `_LANGUAGES`, ordered syntax-first.
3. Run `python3 -c "import lint; print(json.dumps(lint.discover(), indent=2))"` to verify.
4. Add a test to `tests/test_lint.py` and `tests/test_lint_more.py`.
5. Update this reference file's coverage table.

## Design principles (from `lint.py` docstring)

- Linters are **SYNTAX/ERROR-scoped, NOT style** — no false rebuilds from unconventional code.
- Anything not runnable HERE is **skipped** (recorded, not failed).
- `discover()` reports gaps so coverage holes are **never silent**.
- Adding a language = one `(extensions, [builders])` row. A builder returns
  `{name, available()->bool, argv(path)->list}`. Return `available()=False` when the tool is
  absent so the gate skips instead of failing.