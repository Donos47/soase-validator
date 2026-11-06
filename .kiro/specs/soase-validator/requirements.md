# Requirements Document

## Introduction

`soase-validator` is a Java-free language tooling package for Sins of a Solar Empire (Sins 1) mod files. It supports the same game versions as the original Eclipse SoaSE plugin by zombiesrus5: Vanilla, Entrenchment, Diplomacy, and Rebellion, including the Rebellion gate levels 185, 193, and 194 used by the original plugin's definitions, and adds Rebellion 1.98 (the current game version) as its primary target. It reproduces the two capabilities of the legacy Eclipse SoaSE plugin in a form usable from modern editors and AI coding tools:

1. Validation of mod files when they are saved, reported as editor diagnostics.
2. Discovery of valid options for a field (for example `entityType`), offered as completions and hover help.

The core engine is shared by two front ends: a Language Server Protocol (LSP) server for editors, and a Model Context Protocol (MCP) server for AI agents. The package is distributed from GitHub and runs locally.

### Scope

In scope: mod file formats for every supported Game Version (`.entity`, `.galaxy`, `.brushes`, `.sounddata`, `.str`, `.constants`, `.galaxyScenarioDef`, `.particle`, `.explosiondata`, and the other formats covered by the legacy definition set).

Out of scope: Sins of a Solar Empire II, binary asset validation (`.mesh`, `.dds`, `.ogg` contents), and editing features such as formatting or refactoring.

## Glossary

- **Definition**: A declarative rule file describing the structure, fields, types, and allowed values of one mod file type.
- **Registry**: The in-memory merged set of all loaded Definitions.
- **Engine**: The shared core that parses mod files and validates them against the Registry.
- **Mod Root**: A directory containing a mod's files.
- **Reference Root**: A directory containing the base game files for one Game Version, used to resolve cross-file references. Example: `~/path/to/sins-rebellion-reference`.
- **Layer**: A directory that contributes files to the Reference Index. A Layer is either game data (a Reference Root) or a mod.
- **Chain**: The ordered list of Layers from lowest (usually the base game) to highest (the project being edited). A higher Layer overrides a lower one.
- **Project**: The topmost Layer of a Chain, whose files are validated.
- **Manifest**: A `*.manifest` file that lists the names the game will load for one resource type. The game loads only names listed in the manifest of the highest Layer that has one.
- **Reference Index**: A lookup of names (entities, brushes, string IDs, sounds, and so on) built from Mod Roots and Reference Roots.
- **Diagnostic**: A located message with a severity, produced by the Engine.
- **Game Version**: One of Vanilla, Entrenchment, Diplomacy, Rebellion at gate level 185, 193, or 194, or Rebellion 1.98, selecting which version-gated rules apply. The gate levels follow the version tokens in the original plugin's definitions (`Rebellion185`, `Rebellion193`, `Rebellion194`). Rebellion 1.98 is the current game version and the primary target; its files use the template format `SinsArchiveVersion` 194 (a file-format revision, not a game version), so it starts from the gate level 194 rules and is corrected by the audit in Requirement 13. A bare "Rebellion" means Rebellion 1.98.

## Requirements

### Requirement 1: Definition loading

**User Story:** As a mod developer, I want the validator to know the structure of every supported file type, so that validation does not depend on Eclipse or Java.

#### Acceptance Criteria

1. THE Engine SHALL load all bundled Definition files and merge them into a single Registry at startup.
2. THE Engine SHALL support the Definition node types `structure`, `iterative_field`, `field`, `condition_field`, `structure_reference`, `condition_reference`, and `element_rule`, including their documented attributes (`name`, `type`, `required`, `validation`, `values`, `limit`, `version`, `help`, `constraint`).
   1. THE `constraint` attribute SHALL carry the per-field shape of a value. The only form defined is `count=N`, with N a positive integer, on a field with validation type `Position`, giving the exact number of integers.
   2. IF a `constraint` is used on any other validation type, or is not of the form `count=N`, THEN THE Engine SHALL report a Definition load warning (`SOASE-D001`) that names the file and field, and SHALL continue loading.
3. WHEN a Definition file is malformed or references an unknown structure, THE Engine SHALL report a startup warning that names the file and element, and SHALL continue loading the remaining Definitions.
4. THE Engine SHALL expose the Registry for read-only queries by structure name, element rule name, and file extension.
5. THE package SHALL bundle the Definitions so that no external download or Java runtime is needed.

### Requirement 2: Mod file parsing

**User Story:** As a mod developer, I want my files parsed the way the game reads them, so that reported errors correspond to real problems.

#### Acceptance Criteria

1. WHEN a text mod file begins with a recognised header line (`TXT` or `TXT2`), THE Engine SHALL parse the remaining lines as whitespace-delimited key-value entries.
2. THE Engine SHALL accept both tab and space separators between a key and its value.
3. THE Engine SHALL parse quoted string values, unquoted numeric values, and unquoted `TRUE`/`FALSE` values.
   1. THE Engine SHALL parse an unquoted run of hexadecimal digits that is not a number (for example `ffffffff`) as a hexadecimal token, SHALL parse an all-digit token (for example `0` or `00000000`) as a number, and SHALL keep each token's source text.
   2. WHEN a value begins with `[`, THE Engine SHALL parse it as a bracket list of numbers whose items are separated by commas (`[ 234 , 219 ]`, `[9, 99, 999, 99]`) or by whitespace (`[ 0.000000 0.100000 0.000000 ]`), and SHALL record which separator was used.
   3. IF a bracket list is not closed, is closed more than once, or holds an item that is not a number, THEN THE Engine SHALL report `SOASE-P002` on the line, skip the line, and continue with the next line.
   4. IF a quoted string is not terminated, THEN THE Engine SHALL report `SOASE-P003`, SHALL keep the text to the end of the line as the value, and SHALL continue.
4. WHEN a key has no value and is followed by more deeply indented entries, THE Engine SHALL treat the key as the start of a structure block.
   1. WHEN the first non-blank character of a line is `[`, THE Engine SHALL treat the line as a keyless row, a node with an empty key and a bracket list value, nested under the nearest preceding less-indented key (the rows of an `Orientation` header).
5. WHEN an entry is an iterative count key, THE Engine SHALL associate the following repeated blocks with that count.
6. THE Engine SHALL record the line and column of every key and value for use in Diagnostics.
7. IF a file is missing a recognised header, THEN THE Engine SHALL report an error Diagnostic at line 1.
8. IF a file cannot be fully parsed, THEN THE Engine SHALL still return Diagnostics for the portions that were parsed.
9. THE Engine SHALL parse `.entity`, `.galaxy`, `.brushes`, `.sounddata`, `.str`, `.constants`, `.galaxyScenarioDef`, `.particle`, and `.explosiondata` files, and SHALL ignore file extensions that have no Definition.
10. THE Engine SHALL accept both `TXT` and `TXT2` headers in files of the same mod, and SHALL treat `SinsArchiveVersion` as belonging to `TXT2` files only; THE Engine SHALL NOT report a missing `SinsArchiveVersion` in a `TXT` file.
11. WHEN `SinsArchiveVersion` is present, THE Engine SHALL verify it is an integer, and SHALL report a value not recognised for the active Game Version as informational.
12. WHEN a line has the form key, whitespace, `=`, whitespace, quoted value (the `.constants` form `key = "value"`), THE Engine SHALL parse it as the same key and value as `key "value"`, with the key span covering the key and the value span covering the quoted value.
13. IF a key contains `=`, or an `=` appears in any shape other than the one in criterion 12 (`key= "v"`, `key ="v"`, `key = 5`, a bare `=`), THEN THE Engine SHALL report `SOASE-P002` on the line, skip the line, and continue with the next line.
14. IF a value is none of the forms in criterion 3 (including its sub-criteria), THEN THE Engine SHALL report `SOASE-P002` on the line, skip the line, and continue with the next line.
15. IF any text follows a complete quoted value on the same line, whether stuck to the closing quote (`Value "text""`) or separated by whitespace (`a "x" "y"`, `a = "v" tail`), THEN THE Engine SHALL report `SOASE-P002` on the line, skip the line, and continue with the next line. An unterminated quote remains `SOASE-P003` (criterion 3.4).

### Requirement 3: Structural and value validation

**User Story:** As a mod developer, I want incorrect fields and values flagged, so that I catch mistakes before launching the game.

#### Acceptance Criteria

1. WHEN validating an `.entity` file, THE Engine SHALL select the governing structure from the `entityType` value.
2. IF the `entityType` value is not a known entity type for the active Game Version, THEN THE Engine SHALL report an error Diagnostic on that value.
3. WHEN a field has a primitive validation type (`Boolean`, `Integer`, `Decimal`, `Color`, `Position`, `Coordinate`, `Orientation`, `Any`), THE Engine SHALL verify the value conforms to that type.
   1. THE Engine SHALL accept as a `Color` only an unquoted token of exactly 8, 6 or 4 hexadecimal digits in either letter case, or a lone `0`, SHALL check every digit, and SHALL reject a `0x` prefix, a quoted value and any other length.
   2. THE Engine SHALL accept as a `Position` only a bracketed, comma separated list of integers, and WHERE the field's Definition `constraint` is `count=N`, SHALL require exactly N items.
   3. THE Engine SHALL accept as a `Coordinate` only a bracketed, whitespace separated list of exactly 3 numbers, each written in integer or decimal form (integer items are accepted by decision, to match the zombiesrus5 plugin).
   4. THE Engine SHALL accept as an `Orientation` only a header with no value that has exactly 3 keyless child rows, each a `Coordinate`.
   5. THE Engine SHALL reject a number written with an exponent, with a leading `+`, or with a trailing `.`, for `Integer`, `Decimal` and `Coordinate` items, under every numeric preference setting, and SHALL accept a number with no digit before the point (`.5`, `-.5`).
   6. THE Engine SHALL accept `TRUE` and `FALSE` only, in capitals, as `Boolean` values.
4. WHEN a field is bound to an enumeration (`type` or `values`), THE Engine SHALL verify the value is a member of the enumeration for the active Game Version.
5. WHEN a field is marked `required` and is absent, THE Engine SHALL report an error Diagnostic on the enclosing block.
6. WHEN a key is not defined by the governing structure, THE Engine SHALL report an error Diagnostic on that key.
7. WHEN an iterative count exceeds its `limit` or does not match the number of repeated blocks, THE Engine SHALL report an error Diagnostic.
8. WHEN a `condition_field` value selects a branch, THE Engine SHALL validate the following fields against that branch only.
9. WHEN a field, structure, or enumeration value carries a `version` gate that excludes the active Game Version, THE Engine SHALL treat it as undefined for that version.
10. WHERE the user has configured numeric strictness preferences, THE Engine SHALL apply them to integer and decimal validation.
11. WHEN keys of a block appear in a different order than the Definition declares them (after version gates are applied, the selected `condition_field` branch counting as sitting right after its selector, and an iterative field's count line with its repeats occupying that field's position), THE Engine SHALL report `SOASE-V060` once on each key that breaks the order, naming the key it must come before or after, and SHALL NOT report the keys that follow a misplaced key. Optional fields MAY be absent.
12. WHEN a plain key or a count line is used more than once in the same block, THE Engine SHALL report `SOASE-V070` on each later use, giving the line of the first use, and SHALL NOT also report it as out of order. Repeats inside a counted run (blocks, value lines or sibling sequences after a count line) are not duplicates.
13. THE Engine SHALL NOT report an unknown key (criterion 6) as out of order.
14. WHEN, in a file whose extension has a root Definition, a line is indented deeper than the source line directly before it, and that previous line has a value, THE Engine SHALL report `SOASE-V080` "Unexpected indentation" (error) on the deeper line's key, naming the previous line (one-based) as probably under-indented, unless the previous line is the count line of an iterative field and the deeper line is the first repeat of that field's run at exactly one level deeper. The Diagnostic SHALL be added alongside any `SOASE-V020` or `SOASE-V030` findings; the tree and those findings SHALL NOT change.
15. THE Engine SHALL accept the repeats of a counted run either at the count line's indentation or exactly one level deeper, one style per run, and SHALL report `SOASE-V080` once, on the first repeat whose indentation differs from the first repeat of its run.
16. THE Engine SHALL report `SOASE-V080` (criterion 14) only when the previous line is known: a plain field, count line or repeat matched in its block (a count mismatch on that count line does not change this), or an unknown key that is a field of the repeat block (an entry of an iterative field) ending right before it at the same indentation. THE Engine SHALL NOT report it after any other unknown key, after a repeat with no count line, after a list row, or for any line inside a block that is not matched to a Definition.

### Requirement 4: Cross-file reference validation

**User Story:** As a mod developer, I want references to other files checked, so that broken links to entities, brushes, strings, and sounds are found.

#### Acceptance Criteria

1. THE Engine SHALL build a Reference Index covering entities, brushes, string IDs, sounds, sound files, meshes, particles, explosions, galaxy designs, galaxy templates, and orbit body types.
2. THE Engine SHALL build the Reference Index from the Layers in the active Chain (see Requirement 14), taking the names of manifest-governed resources from the manifests selected by Requirement 14.4.
   1. WHEN the Game Version is changed, THE Engine SHALL rebuild the Reference Index for the new version.
3. WHEN the same name exists in more than one Layer, THE Engine SHALL give precedence to the highest Layer in the Chain.
4. WHEN a field has a reference validation type, THE Engine SHALL verify the value resolves in the Reference Index, comparing names case-insensitively.
5. IF a reference does not resolve, THEN THE Engine SHALL report a Diagnostic that names the reference type and value.
6. THE Reference Root and all parent mod Layers SHALL be optional, and all validation, completion, and hover that does not depend on other Layers SHALL work in full when none is configured.
   1. WHILE the Chain is incomplete (no Layer is a usable game Reference Root, or any declared Layer is unusable), THE Engine SHALL resolve references against the usable Layers only, and SHALL NOT report unresolved references as errors or warnings, because a name absent from those Layers may legitimately exist in one that is missing.
   2. WHILE the Chain is incomplete, THE Engine SHALL publish one informational Diagnostic per validated file stating that reference checks are limited, naming which Layers are missing, and naming how to configure them.
   3. IF a configured Layer does not exist, or a game Reference Root does not look like a game data directory, THEN THE Engine SHALL report one warning naming the path, and SHALL treat that Layer as unusable.
   4. WHILE the Chain is incomplete, THE LSP server SHALL limit reference completions to names defined in the usable Layers.
   5. THE informational Diagnostic in 6.2 SHALL be suppressible through configuration.
7. WHEN a file is saved, THE Engine SHALL update the affected portion of the Reference Index without rebuilding the entire index.
8. WHEN a file referenced by a validated file changes, THE Engine SHALL re-validate the dependent open files.

### Requirement 5: Diagnostics on save

**User Story:** As a mod developer, I want errors to appear in my editor when I save, so that I get the same feedback the Eclipse plugin gave me.

#### Acceptance Criteria

1. WHEN the LSP server receives a save notification for a supported file, THE LSP server SHALL publish Diagnostics for that file.
2. THE LSP server SHALL publish each Diagnostic with a range, a severity (error or warning), a stable code, and a message.
3. WHEN a previously reported problem is fixed and the file is saved, THE LSP server SHALL clear that Diagnostic.
4. THE LSP server SHALL also publish Diagnostics when a supported file is opened.
5. WHEN a file is closed, THE LSP server SHALL clear its Diagnostics.
6. THE LSP server SHALL produce Diagnostics for a typical `.entity` file within 500 ms after the Reference Index is warm.

### Requirement 6: Completion of field names and values

**User Story:** As a mod developer, I want to see the valid options for a field, so that I do not have to memorise enumerations or look them up.

#### Acceptance Criteria

1. WHEN completion is requested at a field value position, THE LSP server SHALL return the valid values for that field under the active Game Version.
2. WHEN the field is an enumeration, THE LSP server SHALL return the enumeration members.
3. WHEN the field is a reference type, THE LSP server SHALL return matching names from the Reference Index.
4. WHEN completion is requested at a key position, THE LSP server SHALL return the keys defined for the enclosing structure that are not yet present.
5. WHEN a `condition_field` value is already set, THE LSP server SHALL return only the keys of the selected branch.
6. WHEN the user has typed a partial token, THE LSP server SHALL filter results by that prefix, ignoring case.
7. WHEN completion is requested at the `entityType` value, THE LSP server SHALL return all entity types valid for the active Game Version.
8. THE LSP server SHALL include the Definition `help` text, where present, as completion documentation.

### Requirement 7: Hover help

**User Story:** As a mod developer, I want to read what a field means, so that I can use it correctly.

#### Acceptance Criteria

1. WHEN hover is requested over a key, THE LSP server SHALL return the field's help text, validation type, required status, and Game Version gate.
2. WHEN hover is requested over an enumerated value, THE LSP server SHALL return that value's help text where one exists.
3. WHEN the hovered key has no Definition, THE LSP server SHALL return no hover content.

### Requirement 8: Configuration

**User Story:** As a mod developer, I want to describe my mod and the game files once, so that validation works across my projects.

#### Acceptance Criteria

1. THE package SHALL resolve each setting from the following sources, highest precedence first: the project file (`soase.json`) located at or above the validated file, environment variables, editor-supplied settings (see criterion 14), a user-level configuration file, and built-in defaults.
2. THE configuration SHALL include the Game Version, an optional Reference Root for each Game Version the user wants to validate against, one or more Mod Roots, and an optional ordered list of parent Layers as described in Requirement 14.
3. WHERE no configuration file is present, THE Engine SHALL default the Game Version to Rebellion 1.98 and SHALL treat the nearest directory containing a manifest file as the Mod Root.
4. IF the configuration is invalid, THEN THE package SHALL report a clear error naming the setting and SHALL continue with defaults for unaffected settings.
5. THE configuration SHALL allow disabling individual Diagnostic codes.
6. THE user-level configuration file SHALL allow a default Reference Root per Game Version, so that a new project does not need to repeat the location.
7. THE package SHALL provide an `init` command that creates a `soase.json` in the current directory, accepting the Game Version, Reference Roots, Mod Roots, and parent Layers as options, and prompting for them when run interactively.
8. WHEN `init` is run without a Reference Root and a default exists in the user-level configuration, THE `init` command SHALL use the default and SHALL tell the user which path it used.
9. THE `init` command SHALL succeed when no Reference Root is supplied, and SHALL print how to add one later.
10. THE package SHALL provide a command to set or change a Reference Root in the project file or the user-level file without editing JSON by hand.
11. WHEN a Reference Root is supplied, THE package SHALL check that the path exists and contains the expected game data layout, and SHALL warn if it does not, while still saving the setting.
12. THE package SHALL resolve relative paths in a configuration file relative to that file, and SHALL expand a leading `~` and environment variables.
13. WHEN `soase.json` or the user-level file changes while the LSP server is running, THE LSP server SHALL apply the new settings and re-validate open files without a restart.
14. THE LSP server SHALL accept settings supplied by the editor through initialization options and configuration-change notifications, which SHALL rank above the user-level file and below environment variables.
15. THE MCP server SHALL expose a tool that reports the effective configuration, including the source of each setting and whether each Reference Root was found.
16. THE MCP server SHALL expose a tool that sets a Reference Root for a project, and a tool that adds, removes, or reorders parent Layers, so an AI agent can configure a new project at the user's request.

### Requirement 9: MCP interface for AI agents

**User Story:** As a user of an AI coding tool, I want the assistant to validate and query mod files on demand, so that it can check its own edits.

#### Acceptance Criteria

1. THE MCP server SHALL expose a tool that validates a single file and returns its Diagnostics.
2. THE MCP server SHALL expose a tool that validates a directory and returns Diagnostics grouped by file.
3. THE MCP server SHALL expose a tool that returns completions for a file and a field.
4. THE MCP server SHALL expose a tool that returns help for a field, and a tool that lists valid entity types.
5. THE MCP server SHALL expose structure Definitions as readable resources.
6. THE MCP server and the LSP server SHALL use the same Engine, so that identical input produces identical Diagnostics.
7. THE MCP server SHALL return Diagnostics as structured data containing file, line, column, severity, code, and message.

### Requirement 10: Distribution and runtime

**User Story:** As a member of the modding community, I want to install the tool with one command, so that setup is trivial.

#### Acceptance Criteria

1. THE package SHALL be installable and runnable from a GitHub URL using `uvx`, with no PyPI publication.
2. THE package SHALL provide separate entry points for the LSP server and the MCP server.
3. THE package SHALL run on Windows, macOS, and Linux with Python 3.14 or later.
4. THE package SHALL operate fully offline and SHALL NOT transmit mod content over the network.
5. THE package SHALL include a README documenting installation and configuration for Kiro, VS Code, and MCP clients, including how to run with and without a Reference Root and how to set one for a new project.

### Requirement 11: Quality and maintainability

**User Story:** As a maintainer, I want the tool to be testable and diagnosable, so that rule fixes are safe to ship.

#### Acceptance Criteria

1. THE project SHALL include an automated test suite using pytest.
2. THE test suite SHALL include a golden-file test that validates the base game files in each available Reference Root against its matching Game Version and asserts that they produce no errors.
   1. WHEN no Reference Root is available, THE golden-file test SHALL be skipped with a message rather than fail, so that the suite passes on machines and CI runners without game files.
3. THE test suite SHALL cover every primitive validation type and every Definition node type.
4. THE project SHALL pass `ruff check` and `ruff format --check` without errors.
5. WHEN validation produces an unexpected internal error, THE Engine SHALL log the error and return the Diagnostics gathered so far rather than terminating the server.

### Requirement 12: Definition provenance

**User Story:** As a maintainer, I want the origin and licensing of the bundled rules to be clear, so that the project can be shared responsibly.

#### Acceptance Criteria

1. THE project SHALL record the origin, author, and version of the Definitions it bundles.
2. THE project SHALL keep Definitions in a format that can be updated independently of the Engine code.
3. THE repository SHALL include attribution crediting zombiesrus5 as the author of the original Eclipse plugin, whose Definitions and validation behaviour this project reproduces, and crediting GoaFan77 as the author of the Sins manifest updater script whose behaviour `manifest sync` incorporates.
4. THE repository SHALL include attribution crediting Stardock Entertainment and Ironclad Games as the creators of Sins of a Solar Empire.
5. THE README SHALL state that the project is an unofficial community tool, not affiliated with or endorsed by Stardock, Ironclad Games, or zombiesrus5.
6. THE repository SHALL NOT include any game assets or base game files from Sins of a Solar Empire.
7. THE project SHALL make every Definition correction only in the bundled JSON, and SHALL record each one in `PROVENANCE.json` `audit_corrections` with the Game Version, the evidence (shapes and counts only) and a machine-checkable `verify` entry.
8. THE conversion tool SHALL refuse to write into a directory whose `PROVENANCE.json` lists audit corrections unless an explicit option is given, and SHALL state the reason on standard error.
9. THE test suite SHALL fail if any audit correction recorded in `PROVENANCE.json` is absent from the bundled Definitions.

### Requirement 13: Definition completeness audit

**User Story:** As a mod developer, I want confidence that the bundled rules accept everything the game accepts, so that valid mods are not flagged as broken.

#### Acceptance Criteria

1. THE project SHALL include an audit tool that validates every file in a Reference Root against the Definitions for the matching Game Version and reports each Diagnostic, and SHALL exit with a clear message when no Reference Root is supplied.
2. THE audit tool SHALL classify each Diagnostic as a likely Definition gap or a likely real file problem, based on whether the same key or value occurs across multiple base game files.
3. THE audit tool SHALL report keys and enumeration values that occur in base game files but are absent from the Definitions.
4. THE audit tool SHALL report Definition fields and enumeration values that never occur in any base game file, as candidates for review.
5. WHEN the audit finds a Definition gap, THE project SHALL record the correction in the Definitions with a note identifying the Game Version and the evidence.
6. THE audit tool SHALL produce a report in a machine-readable format and a human-readable summary.
7. THE project SHALL complete the audit for Rebellion 1.98 before the first release. THE project SHALL NOT audit any other Game Version, and SHALL mark every other Game Version as unaudited and best-effort in the README and in the tool's version listing.
8. THE project SHALL document its interpretation of each version-gate token (`Vanilla`, `Entrenchment`, `EntrenchmentOnly`, `Diplomacy`, `DiplomacyOnly`, `Rebellion`, `NotRebellion`, `NotDiplomacyOrRebellion`, `Rebellion185`, `Rebellion193`, `Rebellion194`), SHALL verify that interpretation against the base game files for Rebellion 1.98, and SHALL determine whether Rebellion 1.98 needs rules beyond gate level 194. Support for earlier Game Versions SHALL follow the original plugin's definitions on a best-effort basis, and tokens whose interpretation cannot be verified against available data SHALL be marked as unverified.

### Requirement 14: Layered mod chains

**User Story:** As a developer of a mod built on other mods, I want to declare the full stack of parent mods and the base game, so that references resolve correctly across the whole chain.

For example, a project's Chain might be the Sins 1.98 base game, then E4X, then Interregnum, then the mod being edited.

#### Acceptance Criteria

1. THE configuration SHALL allow an ordered list of Layers from lowest to highest, where each entry is a directory path or a named alias.
2. THE Project's own Mod Root SHALL be the implicit topmost Layer unless it is listed explicitly.
3. THE Engine SHALL treat Layers other than the Project as read-only reference material, and SHALL validate only files in the Project's Mod Roots.
4. THE Engine SHALL treat the manifest of the highest Layer that provides a given manifest type as the only list of names the game will load for that type, and SHALL locate each listed file by searching the Chain from the highest Layer down.
   1. THE Engine SHALL locate files only in the standard game data directories and the files directly in a Layer root, and SHALL skip version-control directories, hidden directories, and any other directory that does not hold game data.
   2. WHERE a Project is an overlay mod without its own manifest, THE Engine SHALL use the manifest from the highest lower Layer that has one, so that the names the overlay adds are valid only if that manifest lists them (see Requirement 15).
5. WHEN a name or file exists in more than one Layer, THE Engine SHALL resolve it from the highest Layer that provides it, independently for each reference type.
6. A Layer's directory MAY contain its own `soase.json` with an `extends` entry naming its parent Chain, and WHERE it does, THE Engine SHALL include that parent Chain beneath the Layer.
   1. THE Engine SHALL detect cycles in `extends` and report an error naming the Layers involved.
   2. WHEN a Layer appears more than once, THE Engine SHALL keep only its lowest position.
7. THE user-level configuration SHALL allow named Layer aliases, and a project file SHALL be able to reference them by name, so that a shared parent mod need only be located once per machine.
8. THE Chain SHALL use a single Game Version, taken from the Project.
9. IF a Layer is missing or unusable, THEN THE Engine SHALL report one warning naming the Layer and its path, and SHALL continue with the remaining Layers, subject to Requirement 4.6.
10. THE Engine SHALL build and cache the Reference Index for each Layer independently, SHALL reuse a cached Layer index across Projects whose Chains share that Layer, and SHALL invalidate it when files in the Layer change.
11. WHEN a file in a Layer below the Project changes, THE Engine SHALL re-validate the dependent open files in the Project.
12. WHEN hover is requested over a reference value, THE LSP server SHALL name the Layer that provides it, and SHALL note when it overrides the same name in a lower Layer.
13. WHEN go-to-definition is requested over a reference value, THE LSP server SHALL open the file from the highest Layer that provides it.
14. WHEN reference completions are returned, THE LSP server SHALL list each name once, using the highest Layer's version, and SHALL identify the originating Layer in the item detail.
15. WHERE the user enables it, THE Engine SHALL report as informational each Project file that overrides a file from a lower Layer.
16. THE MCP configuration tool SHALL report the resolved Chain in order, including each Layer's path, kind, and whether it was found.
17. THE Chain SHALL be defined only by the project configuration and the user-level configuration, and THE Engine SHALL NOT read it from the game's `EnabledMods.txt` or any other per-user game state.
18. WHEN more than one `soase.json` exists above a validated file, THE nearest SHALL define that file's Project and Chain, and settings it omits SHALL be taken from the next file above it, so that a repository holding many overlay mods can give each its own Chain by placing a `soase.json` in each overlay's folder.
19. WHERE a Project is an overlay mod that contains only a small subset of files, THE Engine SHALL NOT require it to contain manifests, or files that lower Layers provide.

### Requirement 15: Manifest consistency and synchronisation

**User Story:** As a mod developer, I want my manifests and files kept in step, so that no file is silently left unloaded or crashes the game because it is not listed.

#### Acceptance Criteria

1. THE Engine SHALL parse every manifest type present in the Chain, including `entity.manifest`, `brush.manifest`, `galaxy.manifest`, `playerPictures.manifest`, `playerThemes.manifest`, and `skybox.manifest`, using per-type rules for the count key, the name key, and whether names include a file extension (for example `entityName`/`entityNameCount`, `brushFile`/`brushFileCount`, `fileName`/`fileCount`, `meshFileName`/`meshFileCount`, and extension-less names in `galaxy.manifest`).
   1. THE per-type rules SHALL be held as data alongside the Definitions, recording for each manifest type its keys, the directory and extension of the files it names, and how the set of governed files is identified.
2. For every manifest type, THE Engine SHALL treat a file as loadable only if its name appears, ignoring case, in the manifest that Requirement 14.4 selects, even though the base game itself ships some files unlisted.
3. IF a Project file is governed by a manifest and is not listed in it, THEN THE Engine SHALL report an error that names the file, the manifest, and the Layer that owns the manifest, and states that the game will not load the file and may fail to start.
   1. WHEN the manifest belongs to a lower Layer than the Project, THE message SHALL state that the entry must be added to that Layer's manifest.
   2. THE Engine SHALL decide which manifest governs a file from the file's extension and directory, using the per-type rules in 1.1.
   3. WHERE a manifest governs only a subset of a file type, THE per-type rule SHALL define how the subset is identified. For `skybox.manifest`, the governed files SHALL be the meshes named by `meshName` entries in the Chain's `.skyboxbackdropdata` files, not every `.mesh` file.
   4. THE project SHALL ship a list, derived from auditing the Reference Root, of base game files that the base game leaves unlisted, and THE Engine SHALL NOT report a Project file that overrides one of them.
   5. THE configuration SHALL allow further name patterns to be exempted.
4. WHEN a name in a Project manifest resolves to no file in any Layer, THE Engine SHALL report a diagnostic at a configurable severity that defaults to informational, because a base mod may list reserved entries for files supplied only by overlay mods.
   1. THE configuration SHALL allow name patterns to be exempted from this diagnostic.
5. IF a manifest's count line does not equal the number of names it lists, THEN THE Engine SHALL report an error on the count line.
6. WHEN a manifest lists the same name more than once, ignoring case, THE Engine SHALL report an informational diagnostic, because base game manifests are known to contain such entries.
7. THE package SHALL provide a `manifest check` command that reports the Diagnostics in this requirement for a Project, for all manifest types.
8. THE package SHALL provide a `manifest sync` command that adds missing names for Project files to the Project's manifests.
   1. THE command SHALL preserve the existing entries, their order, the header style, and the line endings, SHALL append new names, and SHALL update the count line.
   2. THE command SHALL print the changes it would make by default, and SHALL write them only when an explicit option is given.
   3. WHEN it writes a manifest, THE command SHALL first save a backup copy beside it and report the backup's path.
   4. THE command SHALL NOT remove entries unless an explicit option is given, and SHALL list the entries it would remove before doing so.
   5. THE command SHALL edit only manifests within the Project; WHERE the governing manifest belongs to a lower Layer, THE command SHALL print the entries that Layer's manifest needs instead of editing it.
   6. THE command SHALL cover all manifest types, not only entities.
9. WHERE the governing manifest is within the Project, THE LSP server SHALL offer a code action on the Diagnostic in 3 that adds the file to the manifest.
10. THE MCP server SHALL expose tools equivalent to `manifest check` and `manifest sync`, with `manifest sync` defaulting to a dry run.

### Requirement 16: README and licensing

**User Story:** As a community member evaluating or contributing to the project, I want clear documentation, credits, and licensing, so that I know how to use the tool, who made what it builds on, and what I may do with it.

#### Acceptance Criteria

1. THE repository SHALL contain a `README.md` at its root.
2. THE README SHALL describe what the tool does, the supported Game Versions with the audit status of each, and what is validated.
3. THE README SHALL document installation with `uvx` from the GitHub URL, configuration of Reference Roots, parent Layers, and the Game Version (including `init` and the user-level file), and use from Kiro, VS Code, and MCP clients.
4. THE README SHALL contain a Credits section that names each credited party, states what they contributed, and states where that contribution is used in this project. The section SHALL credit:
   1. zombiesrus5, for the Eclipse SoaSE plugin whose Definitions and validation behaviour this project reproduces;
   2. GoaFan77, for the Sins manifest updater script whose behaviour `manifest sync` incorporates; and
   3. Stardock Entertainment and Ironclad Games, as the creators of Sins of a Solar Empire.
5. THE README SHALL state that the project is an unofficial community tool and is not affiliated with or endorsed by any credited party.
6. THE README SHALL state that the project does not distribute game assets or base game files and that users must supply their own for Reference Roots.
7. THE repository SHALL contain a `LICENSE` file at its root containing the MIT License, which applies to the project's original code.
8. THE README and `LICENSE` SHALL state which parts of the repository are covered by the project's license and which parts are third-party works credited to their authors.
9. THE repository SHALL keep the credits in step with the code, so that a contribution is credited in the README before it is released.

## Decisions

1. **Unknown keys are errors.** This matches the original plugin (see Requirement 3.6). Because this makes any Definition gap visible as a false error, Requirement 13 is a release prerequisite.
2. **Definition currency.** The bundled Definitions date from 2020, so the audit in Requirement 13 is how gaps are found and fixed.
3. **Golden-file testing** against the base game files is accepted (Requirement 11.2), and the fixes it drives are in scope.
4. **Chains come from configuration only.** The set of enabled mods in the game changes with how a developer plays or works across projects, so a Chain is never read from `EnabledMods.txt` or other per-user game state.
5. **Primary target is Rebellion 1.98.** Its files use the template format `SinsArchiveVersion` 194, which is a file-format revision and not a game version, so the gate level 194 rules are the starting point.
6. **Manifest behaviour.** A file must appear in the manifest of the highest loaded Layer to be loaded, and an unlisted file crashes the game. Overlay mods work around this by having the base mod list reserved entries for files that only the overlay supplies.
7. **Manifest checking and synchronisation are in scope** (Requirement 15), replacing the legacy single-purpose Python script.
8. **The reference data is Rebellion 1.98.** The audit and the reference checks use a Rebellion 1.98 base game copy with its binary data files converted to text by the game's own `ConvertData_Rebellion` tool. Compared with the earlier 1.94 data it has the same `GameInfo`, `Galaxy`, `Mesh` and `Sound` file lists, the same `entityType` values and an identical `entity.manifest`, and adds only `explosion_techstarbase2.particle` and `playersetup.window`.
9. **Manifest types differ in structure, not in rule.** Surveying the Rebellion 1.98 reference set and the E4X and Interregnum mods showed six manifest types with different key names. In the base game, `entity.manifest` omits 29 of 1,872 entity files, none referenced by any loaded file; `galaxy.manifest` omits 9 of 126 files (the front end, tutorials, and a random template); `skybox.manifest` names the 7 meshes used as skybox backdrops out of 430 `.mesh` files; and the `brush`, `playerPictures`, and `playerThemes` manifests match their files exactly. The maintainer regards the base game's unlisted files as artifacts of its development, so for mod validation a governed file missing from its manifest is an error for every manifest type (Requirement 15.3).
10. **Credits for incorporated tooling.** zombiesrus5 and GoaFan77 are credited for the portions of their tooling that this project incorporates (Requirements 12 and 16).
11. **Version gates are best effort.** Most mod development targets current Rebellion, so Rebellion 1.98 is verified against the reference data and earlier versions follow zombiesrus5's definitions on a best-effort basis (Requirement 13.8). Only Rebellion 1.98 is audited (Requirement 13.7).
12. **Per-folder configuration.** A Chain is set by the nearest `soase.json`. A repository of overlay mods places one in each overlay folder, and no path-pattern chain selection is provided (Requirement 14.18).
13. **Permissions are handled outside this project.** The maintainer arranges any redistribution permission with the original authors separately; the project records credit (Requirements 12 and 16).
14. **The project's original code is MIT licensed** (Requirement 16.7).
