---
inclusion: always
---

# Project Structure

The repository is at an early stage: only `.kiro/specs/soase-validator/` exists so far. The layout below is the planned one from the design. Follow it when creating files.

```
soase-validator/
  pyproject.toml
  README.md                 # install, config, diagnostic code catalogue, credits
  LICENSE, NOTICE/CREDITS
  docs/version-gates.md
  src/soase_validator/
    engine/
      facade.py             # Engine class: the only API front ends use
      model.py, diagnostics.py, versions.py
      config.py, chain.py   # settings resolution, Layer chain
      registry.py           # Definition loader
      parser.py, validator.py, primitives.py
      refindex.py, layercache.py
      manifests.py, completion.py
    definitions/            # bundled JSON Definitions, enums.json,
                            # manifest_rules.json, versions.json, PROVENANCE.json
    lsp/server.py           # pygls handlers
    mcp_server/app.py       # MCP tools and resources
    cli/main.py             # init, config, manifest, audit, versions
    audit/audit.py
  tools/convert_definitions.py   # one-off XML -> JSON converter, not shipped at runtime
  tests/
    conftest.py
    properties/             # test_pNN_<name>.py
    strategies/             # Hypothesis strategies
  .kiro/
    specs/soase-validator/   # requirements.md, design.md, tasks.md
    steering/
```

## Conventions

- Engine code must not import from `lsp/`, `mcp_server/`, `cli/` or `audit/`.
- Definition changes go in the bundled JSON, with a correction recorded in `PROVENANCE.json` (game version and evidence).
- Audit output goes to a git-ignored `audit-output/` directory. `.gitignore` also covers `.venv`, caches and any local reference copies.
- Game files are never stored in the repo. Manifest rules and the base-game-unlisted list contain names only.
- Work through `.kiro/specs/soase-validator/tasks.md` in order; tasks marked `*` are optional tests.
