---
inclusion: always
---

# Tech Stack

## Language and tooling

The Engine, LSP server, MCP server and CLI are Python. Node.js and npm are used only for the VS Code extension in `vscode-extension/`; nothing else in the repository depends on them.

### Python (`soase_validator` package, `tests/`, `tools/`)

- Python 3.14+ (`requires-python = ">=3.14"`), `src/` layout, package `soase_validator`.
- `uv` manages the environment. Never install Python packages globally.
- Distributed from GitHub and run via `uvx --from git+https://github.com/Donos47/soase-validator <entry-point>`. No PyPI publication.
- Entry points: `soase-validator` (CLI), `soase-validator-lsp`, `soase-validator-mcp`.

### VS Code extension (`vscode-extension/`)

- TypeScript, built with `tsc` and managed with npm. Node.js 24 runs the build, lint and test tooling, and `@types/node` is the 24 line. The extension itself runs in the Node embedded in VS Code, which is also Node 24 for the minimum supported VS Code.
- Tests use mocha (unit, property and extension host tests) and `fast-check` (property tests). `@vscode/test-electron` runs the host tests.
- The extension starts `soase-validator-lsp` through `uvx` and contains no validation logic. It neither imports from nor ships with the Python package.
- Run `npm ci` rather than `npm install` for a clean checkout. Run `npm audit` after changing dependencies and surface high-severity findings.
- Style: 2-space indent, single quotes, semicolons, trailing commas in multiline literals, kebab-case file names, camelCase identifiers, PascalCase types, UPPER_SNAKE_CASE module-level constants, JSDoc on every exported symbol.

## Libraries

Python libraries:

- `pygls` (>=2.1,<3) and `lsprotocol`: LSP server.
- `mcp` (>=2.3,<3): official MCP SDK; use `MCPServer` from `mcp.server`. Keep all SDK code in `mcp_server/app.py`.
- `platformdirs`: user config and cache paths.
- Dev: `pytest`, `hypothesis`, `ruff`, `pip-audit`.
- CLI uses `argparse`. Definitions are bundled JSON (no XML dependency).
- Check current versions on PyPI when adding dependencies. Use ranges that include the latest release. Run `pip-audit` after changes.

Extension libraries (`vscode-extension/` only): `vscode-languageclient` is the only runtime dependency. Dev tooling is `typescript`, `eslint` with `typescript-eslint` and `eslint-plugin-n`, `mocha`, `fast-check`, `@vscode/test-electron` and `@vscode/vsce`. Check current versions on the npm registry and keep the ranges recorded in `.kiro/specs/vscode-extension/design.md`.

## Architecture rules

- All logic lives in the Engine (`engine/`). Front ends (`lsp/`, `mcp_server/`, `cli/`) only translate types and call `engine/facade.py`.
- Core modules (parser, primitives, versions, manifest parsing and `plan_sync`) are pure functions; side effects live in `manifest_apply`, the layer cache and config writers.
- The parser is hand-written and tolerant: always return Diagnostics for the parsed portion of a broken file. Its values are `StringValue`, `NumberValue`, `BoolValue`, `ListValue` and `HexValue`; a keyless row has an empty key.
- Primitive checkers have the signature `check_<type>(raw, prefs, constraint=None)`; `check_orientation` takes the header `Node`. A malformed `constraint` raises `ValueError`; the validator reports it once at load as `SOASE-D001`.
- Unexpected exceptions are caught at the facade, logged to stderr, and returned as partial Diagnostics plus `SOASE-X001`.
- stdout must stay clean in the MCP stdio server and LSP; log to stderr only.
- Positions are zero-based internally; MCP output uses one-based line and column.
- Diagnostic codes are stable: `SOASE-` plus family letter `P` parser, `V` validator, `R` reference, `C` chain/config, `M` manifest, `D` definition load, `X` internal.
- Settings precedence: project `soase.json` (nearest) > environment > editor settings > user file > defaults.
- Never read `EnabledMods.txt`. Chains come from configuration only.

## Code style (Python)

Applies to `src/soase_validator/`, `tests/` and `tools/`.

- 4-space indent, double quotes, type hints (`dict[str, Any]`, `X | None`).
- snake_case functions and modules, PascalCase classes, UPPER_SNAKE_CASE constants, underscore-prefixed private helpers.
- Module and function docstrings with Args, Returns and Raises sections (plus Environment Variables for handlers that read them).
- Prefer frozen dataclasses with `slots=True` for data models.
- Use `get_diagnostics` for quick JSON and Python file checks before writing ad hoc scripts.

## Comments and docstrings (PEP 8, PEP 257)

Applies to the Python code in `src/soase_validator/`, `tests/` and `tools/`; the extension follows its own style above. Strict: fix violations in any file you touch.

- Comments say why, never what. Delete a comment that restates the code.
- Block comments start with `# `, sit at the indentation of the code they describe, and are complete sentences: capital first letter, ending in a period.
- Inline comments are rare, separated from code by at least two spaces, and short.
- No commented-out code, no banner or divider comments (`# ---- name ----`, `# ====`). Split the module or use a descriptive name instead.
- No `TODO` or `FIXME` without a task reference from `tasks.md`.
- Docstrings use triple double quotes. The first line is a one-sentence summary in the imperative mood, ending in a period, on its own line, followed by a blank line before any further text. Use Google sections (`Args`, `Returns`, `Raises`) as in the code style above.
- Comments and docstrings describe current behaviour in present tense. They contain no survey counts, file counts, Reference Root file names, change history ("was", "used to", "no longer", "until"), task numbers or chat history. Evidence lives in `PROVENANCE.json`, `design.md` and `reference/`.
- Do not use the Reference Root's machine path or any absolute path.
- `ruff` enforces what it can (`D`, `E501`, `W505` doc line length, `ERA001`); the content rules above are checked in review.

## Testing

Python (`tests/`):

- pytest plus Hypothesis (`@given`, `settings(max_examples=100)` minimum).
- Property tests: one file each at `tests/properties/test_pNN_<name>.py`, tagged `# Feature: soase-validator, Property N: <text>`.
- Strategies live in `tests/strategies/`. Shared fixtures in `tests/conftest.py`.
- Tests needing game files read the path from config or `SOASE_REFERENCE_ROOT_<VERSION>` (for example `SOASE_REFERENCE_ROOT_REBELLION_198`) and `pytest.skip` when absent. Other tests build small synthetic mod trees under `tmp_path`.
- Performance test is marked `perf` and excluded by default.

Extension (`vscode-extension/test/`):

- mocha runs the unit, property and host tests; `fast-check` supplies the property tests.
- Unit and property tests run in plain Node without importing `vscode`. Host tests run in the extension host against a stub LSP server and synthetic mod files.

## Common commands

Python, from the repository root:

```
uv venv
uv sync
uv run ruff check
uv run ruff format --check
uv run pytest
uv run pytest -m perf
uv run pip-audit
uv run python tools/audit.py --reference-root <path>   # planned, developer-only
uv run python tools/convert_definitions.py <xml-dir> --output <dir>
```

The converter exits 2 and writes nothing when the output directory's `PROVENANCE.json` lists audit corrections; `--overwrite-corrections` overrides that (then re-apply every correction by hand).

Extension, from `vscode-extension/`:

```
npm ci
npm run compile
npm run lint
npm run test
npm run package
```

Run `ruff check`, `ruff format --check` and `pytest` before finishing a Python task. Run `npm run compile`, `npm run lint` and `npm run test` before finishing an extension task.
