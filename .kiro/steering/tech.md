---
inclusion: always
---

# Tech Stack

## Language and tooling

- Python 3.14+ (`requires-python = ">=3.14"`), `src/` layout, package `soase_validator`.
- `uv` manages the environment. Never install packages globally.
- Distributed from GitHub and run via `uvx --from git+https://github.com/<owner>/soase-validator <entry-point>`. No PyPI publication.
- Entry points: `soase-validator` (CLI), `soase-validator-lsp`, `soase-validator-mcp`.

## Libraries

- `pygls` (>=2.1,<3) and `lsprotocol`: LSP server.
- `mcp` (>=2.3,<3): official MCP SDK; use `MCPServer` from `mcp.server`. Keep all SDK code in `mcp_server/app.py`.
- `platformdirs`: user config and cache paths.
- Dev: `pytest`, `hypothesis`, `ruff`, `pip-audit`.
- CLI uses `argparse`. Definitions are bundled JSON (no XML dependency).
- Check current versions on PyPI when adding dependencies. Use ranges that include the latest release. Run `pip-audit` after changes.

## Architecture rules

- All logic lives in the Engine (`engine/`). Front ends (`lsp/`, `mcp_server/`, `cli/`, `audit/`) only translate types and call `engine/facade.py`.
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

- 4-space indent, double quotes, type hints (`dict[str, Any]`, `X | None`).
- snake_case functions and modules, PascalCase classes, UPPER_SNAKE_CASE constants, underscore-prefixed private helpers.
- Module and function docstrings with Args, Returns and Raises sections (plus Environment Variables for handlers that read them).
- Prefer frozen dataclasses with `slots=True` for data models.
- Use `get_diagnostics` for quick JSON and Python file checks before writing ad hoc scripts.

## Testing

- pytest plus Hypothesis (`@given`, `settings(max_examples=100)` minimum).
- Property tests: one file each at `tests/properties/test_pNN_<name>.py`, tagged `# Feature: soase-validator, Property N: <text>`.
- Strategies live in `tests/strategies/`. Shared fixtures in `tests/conftest.py`.
- Tests needing game files read the path from config or `SOASE_REFERENCE_ROOT_<VERSION>` (for example `SOASE_REFERENCE_ROOT_REBELLION_198`) and `pytest.skip` when absent. Other tests build small synthetic mod trees under `tmp_path`.
- Performance test is marked `perf` and excluded by default.

## Common commands

```
uv venv
uv sync
uv run ruff check
uv run ruff format --check
uv run pytest
uv run pytest -m perf
uv run pip-audit
uv run soase-validator audit --reference-root <path>   # planned
uv run python tools/convert_definitions.py <xml-dir> --output <dir>
```

The converter exits 2 and writes nothing when the output directory's `PROVENANCE.json` lists audit corrections; `--overwrite-corrections` overrides that (then re-apply every correction by hand).

Run `ruff check`, `ruff format --check` and `pytest` before finishing a task.
