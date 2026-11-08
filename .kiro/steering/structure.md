---
inclusion: always
---

# Project Structure

Entries marked (planned) do not exist yet; everything else is in the repository. Work through `.kiro/specs/soase-validator/tasks.md` for what comes next.

```
soase-validator/
  pyproject.toml, uv.lock, README.md, LICENSE
  docs/version-gates.md          # (planned)
  NOTICE/CREDITS                 # (planned)
  src/soase_validator/
    engine/
      model.py, diagnostics.py   # Span, Diagnostic, code catalogue
      versions.py                # GameVersion, gate_allows
      registry.py                # Definition loader and Registry
      parser.py                  # tolerant parser, Node/Value types, format_tree
      primitives.py              # checkers, validate_constraint
      validator.py               # (planned, task 5.4)
      facade.py                  # (planned) Engine class, the only API front ends use
      config.py, chain.py        # (planned)
      refindex.py, layercache.py # (planned)
      manifests.py, completion.py  # (planned)
    definitions/                 # bundled JSON Definitions, enums.json, manifest_rules.json,
                                 # versions.json, PROVENANCE.json
    lsp/server.py                # placeholder
    mcp_server/app.py            # placeholder
    cli/main.py                  # init, config, manifest, versions; validate (planned, task 15.5)
  tools/convert_definitions.py   # one-off XML -> JSON converter, not shipped at runtime
  tools/audit.py                 # (planned, developer-only) Definition audit, not shipped
  tests/
    conftest.py
    properties/                  # test_pNN_<name>.py (P1-P6, P10, P23, P35-P37 so far)
    strategies/                  # trees.py, definitions.py
    test_parser.py, test_parser_facts.py   # parser unit tests, verified format facts
    test_primitives.py           # primitive checkers
    test_registry.py, test_bundled_definitions.py, test_convert_definitions.py
    test_versions.py, test_engine_model.py, test_smoke.py, ...
  vscode-extension/              # VS Code extension, TypeScript; see below
    package.json, package-lock.json, tsconfig.json, eslint.config.mjs, README.md, LICENSE
    scripts/                     # package.mjs, check-vsix-contents.mjs
    src/                         # extension sources, kebab-case files
    test/                        # unit/, properties/, host/, stub/, fixtures/
    out/                         # git-ignored, tsc output
    dist/                        # git-ignored, packaged .vsix
  reference/                     # git-ignored, local evidence only
    zombiesrus5-xml-definitions/ # original XML Definitions and entity_definitions.xsd
    primitive-survey.md          # Reference Root survey (shapes and counts)
    plugin-bytecode-findings.md  # findings from the plugin jar
  audit-output/                  # git-ignored audit reports
  .kiro/
    specs/soase-validator/       # requirements.md, design.md, tasks.md
    specs/vscode-extension/      # requirements.md, design.md, tasks.md
    steering/
```

## VS Code extension

- `vscode-extension/` is a separate npm project: TypeScript compiled by `tsc` to `out/`, tested with mocha and fast-check, packaged by `scripts/package.mjs` into `dist/`. It uses Node 24 and npm; the Python tooling (`uv`, `ruff`, `pytest`) does not touch it.
- `vscode-extension/` neither imports from nor ships with the Python package. `src/soase_validator/` is the only code in the Python distribution.
- The extension launches `soase-validator-lsp` as a separate process and contains no validation logic.
- `out/`, `dist/`, `node_modules/`, `.vscode-test/` and `*.vsix` are build output and are git-ignored.
- Work through `.kiro/specs/vscode-extension/tasks.md` in order for the extension.
- Any change to the extension's shipped behaviour or manifest increments `version` in `vscode-extension/package.json` and `package-lock.json` under the 0.x rules in `tech.md`, and the `.vsix` is rebuilt with `npm run package`; a released version is never overwritten.

## Conventions

- Engine code must not import from `lsp/`, `mcp_server/`, or `cli/`, and no Python code imports from `vscode-extension/`.
- Definition corrections go only in the bundled JSON, with an entry in `PROVENANCE.json` `audit_corrections` (game version, evidence and a `verify` list that a test checks). Never make one by re-running the converter: it refuses to write into the bundled directory while corrections are recorded, unless `--overwrite-corrections` is given.
- Per-field shape parameters (for example a Position item count) use the Definition `constraint` attribute, for example `count=4`.
- Survey and analysis output goes to `reference/` (git-ignored), never into the repo. Temporary scripts live in the system temp folder and are deleted afterwards.
- `.gitignore` also covers `.venv`, caches, any local reference copies and the extension build output.
- Game files are never stored in the repo. Manifest rules and the base-game-unlisted list contain names only.
- Work through `.kiro/specs/soase-validator/tasks.md` in order; tasks marked `*` are optional tests. Only the orchestrator changes task statuses; sub-agents leave them alone unless told to.
