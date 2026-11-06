---
inclusion: always
---

# Tech Stack

## Language and tooling

- Python 3.14+ (`requires-python = ">=3.14"`), `src/` layout, package `sose_validator`.
- `uv` manages the environment. Never install packages globally.
- Distributed from GitHub and run via `uvx --from git+https://github.com/<owner>/sose-validator <entry-point>`. No PyPI publication.
- Entry points: `sose-validator` (CLI), `sose-validator-lsp`, `sose-validator-mcp`.

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
- The parser is hand-written and tolerant: always return Diagnostics for the parsed portion of a broken file.
- Unexpected exceptions are caught at the facade, logged to stderr, and returned as partial Diagnostics plus `SOSE-X001`.
- stdout must stay clean in the MCP stdio server and LSP; log to stderr only.
- Positions are zero-based internally; MCP output uses one-based line and column.
- Diagnostic codes are stable: `SOSE-` plus family letter `P` parser, `V` validator, `R` reference, `C` chain/config, `M` manifest, `D` definition load, `X` internal.
- Settings precedence: project `sose.json` (nearest) > environment > editor settings > user file > defaults.
- Never read `EnabledMods.txt`. Chains come from configuration only.

## Code style (Python)

- 4-space indent, double quotes, type hints (`dict[str, Any]`, `X | None`).
- snake_case functions and modules, PascalCase classes, UPPER_SNAKE_CASE constants, underscore-prefixed private helpers.
- Module and function docstrings with Args, Returns and Raises sections (plus Environment Variables for handlers that read them).
- Prefer frozen dataclasses with `slots=True` for data models.
- Use `get_diagnostics` for quick JSON and Python file checks before writing ad hoc scripts.

## Testing

- pytest plus Hypothesis (`@given`, `settings(max_examples=100)` minimum).
- Property tests: one file each at `tests/properties/test_pNN_<name>.py`, tagged `# Feature: sose-validator, Property N: <text>`.
- Strategies live in `tests/strategies/`. Shared fixtures in `tests/conftest.py`.
- Tests needing game files read the path from config or `SOSE_REFERENCE_ROOT_<VERSION>` (for example `SOSE_REFERENCE_ROOT_REBELLION_196`) and `pytest.skip` when absent. Other tests build small synthetic mod trees under `tmp_path`.
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
uv run sose-validator audit --reference-root <path>
```

Run `ruff check`, `ruff format --check` and `pytest` before finishing a task.
