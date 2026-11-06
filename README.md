# soase-validator

Java-free language tooling for Sins of a Solar Empire (Sins 1) mod files. It
provides validation, completion, hover and go-to-definition through an LSP
server, an MCP server and a CLI, all backed by one shared Engine.

This is an unofficial community tool. Credits: zombiesrus5 (original Eclipse
plugin and Definitions), GoaFan77 (manifest updater script) and Stardock
Entertainment / Ironclad Games (the game).

## Install and run

```
uvx --from git+https://github.com/<owner>/soase-validator soase-validator --help
uvx --from git+https://github.com/<owner>/soase-validator soase-validator-lsp
uvx --from git+https://github.com/<owner>/soase-validator soase-validator-mcp
```

## Development

```
uv venv
uv sync
uv run ruff check
uv run ruff format --check
uv run pytest
uv run pip-audit
```

Requires Python 3.14 or later.
