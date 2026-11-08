# soase-validator

Java-free language tooling for Sins of a Solar Empire (Sins 1) mod files. It
validates mod files, offers completion, hover help and go-to-definition, and
checks and syncs `*.manifest` files. It reproduces the validation and
field-discovery features of the Eclipse SoaSE plugin for modern editors and AI
tools.

One shared Engine sits behind three thin front ends, so identical input gives
identical Diagnostics everywhere:

- `soase-validator-lsp`: a language server for editors.
- `soase-validator-mcp`: an MCP server for AI agents and MCP clients.
- `soase-validator`: a command-line tool (setup, configuration, manifests,
  versions).

This is an unofficial community tool. It is not affiliated with or endorsed by
Stardock Entertainment, Ironclad Games, zombiesrus5 or GoaFan77. See
[Credits](#credits).

The tool runs fully offline and never transmits mod content.

## Game Versions and audit status

| Game Version | Id | Status |
| --- | --- | --- |
| Rebellion 1.98 | `rebellion-1.98` | audited (primary target, default) |
| Rebellion (gate level 194) | `rebellion-194` | unaudited, best-effort |
| Rebellion (gate level 193) | `rebellion-193` | unaudited, best-effort |
| Rebellion (gate level 185) | `rebellion-185` | unaudited, best-effort |
| Diplomacy | `diplomacy` | unaudited, best-effort |
| Entrenchment | `entrenchment` | unaudited, best-effort |
| Vanilla | `vanilla` | unaudited, best-effort |

A bare "Rebellion" means 1.98. Rebellion 1.98 files use the template format
`SinsArchiveVersion` 194, which is a file-format revision and not a game
version. Audited means the bundled rules were checked against a Rebellion 1.98
base game copy. Unaudited versions use the same rules with version gates
applied and may report false errors or miss real ones.

Run `soase-validator versions` to list the versions, their audit status and any
version gate tokens whose interpretation is unverified.

Out of scope: Sins of a Solar Empire II, binary assets (`.mesh`, `.dds`,
`.ogg`), formatting and refactoring.

## What is validated

Text mod files are checked against bundled declarative Definitions. Supported
file types include `.entity` (by its `entityType`), `.galaxy`, `.brushes`,
`.sounddata`, `.str`, `.constants`, `.galaxyScenarioDef`, `.particle`,
`.explosiondata`, `.randomeventdefs`, `.starscapedata`, `.skyboxbackdropdata`,
`.asteroidDef`, `.groups` and `.planetItemTypeCount`.

The checks cover:

- File structure: header, quoting and indentation.
- Keys: unknown keys, required keys, key order, duplicates and iterative count
  lines.
- Values: booleans, integers, decimals, colors, positions, coordinates,
  orientations and enumerated values.
- Game Version gates for fields, enum values and `entityType`.
- References between files, resolved across a Chain of Layers.
- `*.manifest` files: files missing from the governing manifest, entries that
  match no file, count mismatches and duplicates.

## Install and run

The tool needs Python 3.14 or later and [uv](https://docs.astral.sh/uv/). It is
distributed from [GitHub](https://github.com/Donos47/soase-validator) and is not
published on PyPI.

```
uvx --from git+https://github.com/Donos47/soase-validator soase-validator --help
uvx --from git+https://github.com/Donos47/soase-validator soase-validator-lsp
uvx --from git+https://github.com/Donos47/soase-validator soase-validator-mcp
```

The tool runs on Windows, macOS and Linux.

## Command-line tool

```
soase-validator init [--path DIR] [--game-version V] [--reference-root DIR]
                     [--mod-root DIR] [--layer DIR] [--language L]
                     [--overwrite] [--no-prompt]
soase-validator config set-reference-root ROOT [--game-version V] [--path P] [--user]
soase-validator config show [--path P]
soase-validator manifest check [--path P]
soase-validator manifest sync [--path P] [--write] [--remove-stale]
soase-validator versions
```

- `manifest check` prints manifest Diagnostics and exits 1 when any is an
  error.
- `manifest sync` is a dry run that prints a diff. With `--write` it saves each
  changed manifest after copying the old one to `<name>.old`. It adds missing
  names and removes stale entries only with `--remove-stale`.

- `validate` checks files and directories with the same Engine as the MCP
  `validate_file` and `validate_directory` tools, so the Diagnostics are
  identical.

```
soase-validator validate PATH... [--path DIR] [--game-version VERSION] [--format text|json] [--output FILE]
```

  Text output has one line per Diagnostic, `file:line:column: severity code
  message`, with one-based positions. `--format json` prints
  `{"diagnostics": [...]}` using the MCP fields (`file`, `line`, `column`,
  `severity`, `code`, `message`, `end_line`, `end_column`). Without a `PATH`,
  the directory given by `--path` (default: current) is validated.
  `--game-version` applies when no `soase.json` or environment variable sets
  one. The exit status is 1 when any Diagnostic is an error, 2 for a missing
  path, an unknown Game Version or a report that cannot be written, and 0
  otherwise. Errors go to stderr.

  `--output FILE` writes a report to `FILE` in the chosen format and prints one
  summary line (files validated, error, warning and info counts, the report
  path). The exit status is the same as without `--output`. The report lists
  only files with findings. The JSON report holds `files_validated`,
  `files_with_findings`, `counts` (by severity), `by_code` and `files`; the text
  report has the Diagnostic lines followed by the counts line. A file outside
  every Mod Root (`SOASE-C050`) is reported but not counted as validated. An
  existing `FILE` is replaced without a prompt, and its directory must exist.
  A report inside a Mod Root is not validated on later runs, because its
  extension is not a game file type.

## Configuration

Settings live in `soase.json` files. Create one with `init`:

```
soase-validator init --path . --game-version rebellion-1.98 --reference-root ~/path/to/sins-rebellion-reference
```

On a terminal, `init` prompts for anything you leave out. Pass `--no-prompt` to
skip prompts. Re-running `init` keeps keys that already hold a different value
unless you pass `--overwrite`.

### Settings

| Key | Meaning | Default |
| --- | --- | --- |
| `gameVersion` | Game Version id from the table above | `rebellion-1.98` |
| `referenceRoots` | Object from Game Version id to the base game data directory | none |
| `modRoots` | Mod Root directories | nearest directory with a manifest |
| `layers` | Parent Layers, lowest first: directory paths or `@alias` entries | none |
| `aliases` | Object from alias name to directory | none |
| `language` | Localization folder name, such as `en` | `en` |
| `disabledCodes` | Diagnostic codes to hide, such as `SOASE-C030` | none |
| `numeric.integerStrict` | Reject integers written with a decimal point | `false` |
| `numeric.decimalAllowInteger` | Accept integers where decimals are expected | `true` |
| `manifest.unreferencedSeverity` | Severity of `SOASE-M020`: `error`, `warning` or `info` | `info` |
| `manifest.exemptUnlisted` | Patterns exempt from `SOASE-M010` | none |
| `manifest.exemptUnreferenced` | Patterns exempt from `SOASE-M020` | none |
| `reportOverrides` | Report Project files that override a lower Layer (`SOASE-C040`) | `false` |
| `suppressLimitedReferenceNotice` | Hide `SOASE-C030` | `false` |

Relative paths in a file resolve against the directory holding that file. A
leading `~` and `%VAR%`, `$VAR` and `${VAR}` references are expanded.

A parent Layer directory may carry its own `soase.json` with an `extends` list
of further Layers. Those are spliced beneath it, and cycles are reported as
`SOASE-C010`. The Chain is built only from configuration; the game's
`EnabledMods.txt` is never read.

### Where settings come from

Each setting is resolved on its own, highest precedence first:

1. The nearest project `soase.json`, then each one above it.
2. Environment variables: `SOASE_VALIDATOR_GAME_VERSION`,
   `SOASE_VALIDATOR_LANGUAGE` and `SOASE_REFERENCE_ROOT_<VERSION>` (for example
   `SOASE_REFERENCE_ROOT_REBELLION_198`).
3. Editor settings sent by the language client, using the same key names.
4. The user-level file `config.json` in the platform user configuration
   directory. `soase-validator config show` prints its exact location. It
   accepts the same keys, plus `defaultReferenceRoots` for a per-version
   default Reference Root.
5. Built-in defaults.

`soase-validator config show` prints every setting with its source, which
Reference Roots exist on disk, the configuration files in use and the resolved
Chain.

### Reference Roots

A Reference Root is the base game data directory for a Game Version, read in
place and never copied. Set one for a project:

```
soase-validator config set-reference-root ~/path/to/sins-rebellion-reference --game-version rebellion-1.98
```

Add `--user` to store it as a default for every project. A root that does not
exist is still saved and reported with a warning.

### With and without a Reference Root

A Reference Root is optional. Without one, parsing, structure, values and
version gates work as usual, and references are resolved against the Project and
the Layers you declare. A name that none of those Layers provides is reported as
`SOASE-R010`, so a reference to a base game file reports as unresolved until you
configure a Reference Root that provides it. If a configured Layer or Reference
Root directory is missing or unusable, the Chain is incomplete: unresolved
references are not reported, and a single `SOASE-C030` notice per file lists the
missing Layers. With a Reference Root and parent Layers configured, references
resolve across the whole Chain, the highest Layer winning, and `manifest check`
considers files and manifests from every Layer.

## Use from Kiro

Kiro reads MCP servers from `.kiro/settings/mcp.json` in the workspace or from
the user-level settings file:

```json
{
  "mcpServers": {
    "soase-validator": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Donos47/soase-validator",
        "soase-validator-mcp"
      ]
    }
  }
}
```

To start a new mod project, ask the agent to run the `configure` tool, or run
`soase-validator init` yourself. To add a Reference Root afterwards, use the
`set_reference_root` tool or `soase-validator config set-reference-root`.

## Use from VS Code

The language server speaks stdio. Any generic LSP client extension can run it
with the command `uvx` and the arguments
`--from git+https://github.com/Donos47/soase-validator soase-validator-lsp`,
for the file types listed above. This repository does not ship a VS Code
extension. Editor settings are passed as initialization options or through
`workspace/didChangeConfiguration`, using the `soase.json` key names, either
directly or under a `soase-validator` section.

The language server provides diagnostics, completion, hover help,
go-to-definition and a quick fix that adds a file missing from its manifest.

For VS Code's built-in MCP support, add the server to `.vscode/mcp.json`:

```json
{
  "servers": {
    "soase-validator": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/Donos47/soase-validator",
        "soase-validator-mcp"
      ]
    }
  }
}
```

## Use from other MCP clients

Run `soase-validator-mcp` over stdio and register it in the client with the
`uvx` command and arguments shown above. The server writes only protocol
messages to stdout and logs to stderr.

Tools:

| Tool | Purpose |
| --- | --- |
| `validate_file` | Validate one file, optionally from unsaved text |
| `validate_directory` | Validate every supported file below a directory; with `output_path`, write the JSON report there and return a summary |
| `complete` | Completion candidates at a one-based line and column |
| `field_help` | Help for a field of a structure Definition |
| `list_entity_types` | `entityType` values valid for a Game Version |
| `manifest_check` | Check manifests against files |
| `manifest_sync` | Plan, and with `write` apply, a manifest sync (dry run by default) |
| `configure` | First-time `soase.json` setup |
| `get_config` | Effective configuration and Chain |
| `set_reference_root` | Set the Reference Root of a Game Version |
| `edit_layers` | Add, remove, move or reorder parent Layers |
| `versions` | Game Versions with audit status |

The server also serves each structure Definition as a resource at
`soase://definitions/{structure}`. MCP diagnostics use one-based line and
column numbers.

`validate_directory` with `output_path` writes the same JSON report as
`soase-validator validate --format json --output`, replacing an existing file
(its directory must exist, otherwise the call fails). The result holds `report`
(the path), `files_validated`, `files_with_findings`, `counts`, `by_code` and
`top_files` (up to 10 `{file, count}` entries, most findings first, ties by
path). Without `output_path` the result is unchanged.

## Diagnostic codes

Codes are stable. Hide a code with `disabledCodes`.

| Code | Severity | Meaning |
| --- | --- | --- |
| `SOASE-P001` | error | Missing or invalid file header (TXT or TXT2) |
| `SOASE-P002` | error | Line could not be parsed and was skipped |
| `SOASE-P003` | error | Unterminated quoted string |
| `SOASE-P004` | info | Unrecognised `SinsArchiveVersion` for the game version |
| `SOASE-V010` | error | Unknown `entityType` for the game version |
| `SOASE-V020` | error | Unknown key for the structure |
| `SOASE-V030` | error | Iterative count mismatch or limit exceeded |
| `SOASE-V040` | error | Required field missing |
| `SOASE-V050` | error | Invalid value for the field |
| `SOASE-V060` | error | Key out of the declared order |
| `SOASE-V070` | error | Duplicate key in a block |
| `SOASE-V080` | info | Unexpected indentation |
| `SOASE-R010` | error | Unresolved reference |
| `SOASE-C010` | error | Layer chain cycle |
| `SOASE-C020` | warning | Layer missing or unusable |
| `SOASE-C030` | info | Reference checks limited by missing Layers |
| `SOASE-C040` | info | Project file overrides a file of a lower Layer |
| `SOASE-C050` | warning | File is outside every Mod Root; it was not validated |
| `SOASE-M010` | error | File not listed in governing manifest |
| `SOASE-M020` | info | Manifest entry matches no file in any Layer |
| `SOASE-M030` | error | Manifest count differs from the listed names |
| `SOASE-M040` | info | Duplicate manifest entry |
| `SOASE-D001` | warning | Definition load problem |
| `SOASE-X001` | error | Internal error; results may be partial |

Families: `P` parser, `V` validator, `R` reference, `C` chain and
configuration, `M` manifest, `D` Definition load, `X` internal.
`SOASE-M020` severity is configurable through `manifest.unreferencedSeverity`.

## Future improvements

Planned, not yet available:

- A VS Code extension that starts the language server, registers the
  supported file types and exposes the `soase.json` settings in the editor.
- Syntax coloring for the supported file types in code editors.
- Research tier cost standardization
- Review and revise code severities, numbering, and descriptions. 

## Game files

This project does not distribute game assets or base game files. To resolve
references against the base game, supply your own copy of the game data as a
Reference Root. The files are read in place and are never copied or sent
anywhere.

## Development

```
uv venv
uv sync
uv run ruff check
uv run ruff format --check
uv run pytest
uv run pip-audit
```

Tests that need game files read the Reference Root from configuration or from
`SOASE_REFERENCE_ROOT_<VERSION>` and skip when it is absent.

## Credits

This project builds on the work of others.

- zombiesrus5 wrote the Eclipse SoaSE plugin. Its Definitions and validation
  behaviour are what this project reproduces. The bundled Definitions in
  `src/soase_validator/definitions/` are converted from the plugin's XML
  Definitions, and the Engine follows the plugin's validation behaviour.
  Corrections made after conversion are recorded in `PROVENANCE.json`.
- GoaFan77 wrote the Sins manifest updater script. Its behaviour is
  incorporated in `manifest sync`.
- Stardock Entertainment and Ironclad Games created Sins of a Solar Empire.
  The file formats, names and rules this tool checks belong to the game. No
  game content is included here.

This is an unofficial community tool. It is not affiliated with or endorsed by
Stardock Entertainment, Ironclad Games, zombiesrus5 or GoaFan77.

## License

The project's original code is released under the MIT License (see
`LICENSE`). That license does not cover the third-party works credited above:
the zombiesrus5 Definitions and behaviour from which the bundled Definitions
are derived, the GoaFan77 manifest updater script behaviour, and Sins of a
Solar Empire itself, which remains the property of its owners. The terms under
which zombiesrus5 and GoaFan77 allow reuse of their work are not stated in this
repository.
