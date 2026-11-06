# Implementation Plan: soase-validator

## Overview

The plan builds the shared Engine bottom-up (model, versions, definitions, parser, validator, configuration, reference index, manifests, completion), then the Engine facade, then the three front ends (LSP, MCP, CLI), then the audit tool and the Rebellion 1.98 audit, and finally documentation and distribution checks. The implementation language is Python 3.14, as the design specifies. Each step builds on the previous ones and ends wired into the facade or a front end.

Conventions for every task:

- Use `uv` to create and manage the virtual environment (`uv venv`, `uv sync`, `uv run`). Never install packages globally.
- Resolve dependency versions from PyPI when the project is created and use ranges that include the current release. Run `uv run pip-audit` (or `uvx pip-audit`) after adding dependencies and surface high-severity findings.
- Python code uses 4-space indents, double quotes, type hints, `snake_case` names, underscore-prefixed private helpers, and module and function docstrings with Args, Returns and Raises sections.
- Run `uv run ruff check`, `uv run ruff format --check` and `uv run pytest` before finishing a task. Use `get_diagnostics` for quick file checks of JSON and Python files before writing ad hoc scripts.
- Each property test lives in its own file `tests/properties/test_pNN_<name>.py`, uses `@given` with `settings(max_examples=100)` at minimum, and carries the tag comment `# Feature: soase-validator, Property N: <property text>`.
- The reference game files live wherever the user keeps them and are supplied through `--reference-root`, configuration, or `SOASE_REFERENCE_ROOT_<VERSION>`. They are read in place only and MUST NOT be copied into the repository, and no test may embed their content. Tests that need them read the path from configuration or `SOASE_REFERENCE_ROOT_REBELLION_198` (and the other version variants) and call `pytest.skip` with a message when it is absent. Other tests build tiny synthetic mod trees.
- No source file, test, fixture, default configuration or documentation example may contain a machine-specific absolute path. Use placeholders such as `~/path/to/sins-rebellion-reference`.

## Tasks

- [x] 1. Project scaffolding
  - [x] 1.1 Create the Python project with uv
    - Create `pyproject.toml` with `requires-python = ">=3.14"`, the `src/soase_validator` layout, package data for `definitions/*.json`, and `[project.scripts]` entry points `soase-validator`, `soase-validator-lsp` and `soase-validator-mcp`
    - Add runtime dependencies `pygls`, `lsprotocol`, `mcp` and `platformdirs`, and a dev dependency group with `pytest`, `hypothesis`, `ruff` and `pip-audit`, checking current versions on PyPI and using ranges as in the design (`pygls>=2.1,<3`, `mcp>=2.3,<3`)
    - Create the empty package modules from the design's package layout (`engine/`, `lsp/`, `mcp_server/`, `cli/`, `audit/`, `definitions/`) with placeholder entry points so the scripts import
    - Configure `ruff` (lint and format, double quotes) and `pytest` in `pyproject.toml`; add `.gitignore` covering `.venv`, caches, `audit-output/` and any local reference copies
    - Create the venv with `uv venv`, run `uv sync`, and run `pip-audit`
    - _Requirements: 10.1, 10.2, 10.3, 11.1, 11.4, 12.6_

  - [x] 1.2 Set up shared test infrastructure
    - Create `tests/conftest.py` with a `reference_root` fixture that reads configuration or `SOASE_REFERENCE_ROOT_<VERSION>` and skips with a message when absent, a Hypothesis profile (minimum 100 examples), and a helper that builds small synthetic mod trees under `tmp_path`
    - Create `tests/properties/` and `tests/strategies/` packages
    - Add one trivial test proving the package imports under Python 3.14
    - _Requirements: 11.1, 11.2.1, 12.6_

- [x] 2. Model, diagnostics and version gating
  - [x] 2.1 Implement `engine/model.py` and `engine/diagnostics.py`
    - Define `Position`, `Range`, `Span`, `Severity`, `Diagnostic`, `CompletionItem`, `HoverResult`, `Location` and `FieldHelp` as frozen dataclasses with zero-based positions
    - Add the stable code catalogue (`P`, `V`, `R`, `C`, `M`, `D`, `X` families from the design) and a single `filter_disabled(diagnostics, disabled_codes)` function
    - _Requirements: 5.2, 8.5, 9.7_

  - [x] 2.2 Write property test for disabled-code filtering
    - **Property 23: Disabled codes are filtered**
    - **Validates: Requirements 8.5**

  - [x] 2.3 Implement `engine/versions.py`
    - Define the `GameVersion` enum (Vanilla, Entrenchment, Diplomacy, Rebellion 185, 193, 194, 198), map bare "Rebellion" to 1.98, and implement capability sets and `gate_allows(gate, version)` over the gate tokens
    - Make Rebellion 1.98 start from the 194 capability set and load optional `overrides` and `unverified` token lists and per-version audit status from `definitions/versions.json`
    - _Requirements: 3.9, 13.7, 13.8_

  - [x] 2.4 Write property test for gate monotonicity
    - **Property 10: Gate monotonicity for Rebellion 1.98**
    - **Validates: Requirements 3.9, 13.8**

- [x] 3. Definitions: registry, converter and bundled data
  - [x] 3.1 Implement `engine/registry.py`
    - Define frozen dataclasses for `StructureDef`, `FieldDef`, `IterativeFieldDef`, `ConditionFieldDef`, `StructureReferenceDef`, `ConditionReferenceDef`, `ElementRuleDef` and `EnumDef` with all documented attributes
    - Implement the JSON loader with a second pass for structure references, `LoadWarning` collection for malformed files and dangling references (code `SOASE-D001`), and the read-only `Registry` queries by structure name, element rule, extension and enum
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 3.2 Write Hypothesis strategies for Definitions
    - Create `tests/strategies/definitions.py` with `definitions()` generating structure graphs with all node types, gates and enums, plus a serializer to the bundled JSON schema
    - _Requirements: 1.2, 11.3_

  - [x] 3.3 Write property test for malformed Definitions
    - **Property 35: Malformed Definitions do not block loading**
    - **Validates: Requirements 1.3**

  - [x] 3.4 Write property test for Definition load round trip
    - **Property 36: Definition load round trip**
    - **Validates: Requirements 1.2**

  - [x] 3.5 Implement `tools/convert_definitions.py`
    - Convert the original zombiesrus5 XML Definitions to the bundled JSON schema, taking the XML source directory as a command-line argument and never embedding game files
    - If the original XML is not available in the workspace, ask the user for its location before running the conversion
    - Write the converted files and `enums.json` into `src/soase_validator/definitions/` and report any element it could not convert
    - _Requirements: 1.2, 1.5, 12.1, 12.2_

  - [x] 3.6 Add bundled data files and a registry smoke test
    - Create `definitions/PROVENANCE.json` (origin, author zombiesrus5, source version, conversion date, empty audit corrections list), `definitions/versions.json`, and `definitions/manifest_rules.json` exactly as the design lists them
    - Write a unit test that loads every bundled Definition with zero warnings and that each Definition node type is present
    - _Requirements: 1.1, 1.4, 1.5, 11.3, 12.1, 15.1.1_

- [x] 4. Parser
  - [x] 4.1 Implement `engine/parser.py`
    - Implement the tolerant line-oriented parser with `Node`, `Value` variants, `ParsedFile` and `parse(text)`, relative-indentation block extents using an indent stack (tabs and spaces each count as one unit), keys containing colons, quoted strings including empty and unterminated, numbers, `TRUE`/`FALSE`, bracket lists, and count keys as ordinary nodes
    - Emit `SOASE-P001` for a missing header, `SOASE-P002` for skipped unparseable lines, `SOASE-P003` for unterminated quotes and `SOASE-P004` for unrecognised `SinsArchiveVersion` integers; validate `SinsArchiveVersion` only in `TXT2` files
    - Implement `format_tree(parsed)` for tests, and file reading with `utf-8-sig` falling back to `latin-1`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11_

  - [x] 4.2 Write Hypothesis strategies for trees and indentation
    - Create `tests/strategies/trees.py` with `trees()` (strings including empty, six-place decimals, booleans, bracket lists, colon keys, nested blocks, count-prefixed repeats) and an `indent_style` strategy rendering tabs, spaces or a mix with strictly increasing widths
    - _Requirements: 2.3, 2.4, 2.5_

  - [x] 4.3 Write property test for parse round trip
    - **Property 1: Parse round trip**
    - **Validates: Requirements 2.1, 2.3, 2.4, 2.5**

  - [x] 4.4 Write property test for separator independence
    - **Property 2: Separator independence**
    - **Validates: Requirements 2.2**

  - [x] 4.5 Write property test for recorded spans
    - **Property 3: Recorded spans match source**
    - **Validates: Requirements 2.6**

  - [x] 4.6 Write property test for parser recovery
    - **Property 4: Parser recovery**
    - **Validates: Requirements 2.8**

  - [x] 4.7 Write property test for missing header
    - **Property 5: Missing header**
    - **Validates: Requirements 2.7**

  - [x] 4.8 Write property test for archive version handling
    - **Property 6: Archive version handling**
    - **Validates: Requirements 2.10, 2.11**

  - [x] 4.9 Write property test for indentation style independence
    - **Property 37: Indentation style independence**
    - **Validates: Requirements 2.3, 2.4**

  - [x] 4.10 Write parser unit tests
    - Cover the "verified format facts" in the design using synthetic snippets (`TXT` and `TXT2` headers, `Level:0 0.000000`, `pos [ 234 , 219 ]`, empty strings, zero counts), unknown extensions being ignored, and unterminated quotes
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.9, 2.10_

- [ ] 5. Primitives and validator
  - [x] 5.1 Implement `engine/primitives.py`
    - Implement one pure checker per primitive type (`Boolean`, `Integer`, `Decimal`, `Color`, `Position`, `Coordinate`, `Orientation`, `Any`) with `NumericPrefs` and `PrimitiveResult`; signature `check_<type>(raw, prefs, constraint=None)`, except `check_orientation(node, prefs, constraint=None)`, which takes the header node and checks its child rows
    - Follow the approved rules in the design (Validator, "Primitive rules and evidence"): Color is 8, 6 or 4 hex digits (any case, every digit checked) or a lone `0`, with no `0x` prefix and no quotes; Position is a comma separated integer list whose count comes from the field `constraint` `count=N` (2 for `pos`, 4 for `pixelBox`, `area`, `mainViewIconAreaOffsetFromCenter`); Coordinate is exactly 3 space separated numbers; Orientation is a value-less header with exactly 3 keyless Coordinate rows; numbers reject exponents, a leading `+` and a trailing `.`
    - Read the `key = "value"` form in the parser, correct `GroupType.condition` `param` to `Any`, add the `count=N` constraints to the bundled Definitions and record each in `PROVENANCE.json`
    - _Requirements: 3.3, 3.10_

  - [~] 5.2 Write property test for primitive type acceptance
    - **Property 7: Primitive type acceptance**
    - **Validates: Requirements 3.3**

  - [~] 5.3 Write property test for numeric strictness
    - **Property 8: Numeric strictness**
    - **Validates: Requirements 3.10**

  - [x] 5.4 Implement `engine/validator.py`
    - Select the root structure by extension and by `entityType` for `.entity` files (`SOASE-V010`), walk nodes with a `StructureCursor`, report unknown keys (`SOASE-V020`), iterative count mismatches and limits (`SOASE-V030`), missing required fields (`SOASE-V040`), evaluate `condition_field` branches, apply version gates to structures, fields and enum values, and apply numeric preferences
    - Pass each field's `constraint` to its checker and report `validate_constraint` problems as Definition load warnings; call `check_orientation` with the header node
    - Treat an `iterative_field` as a count line followed by that many repeats, where a repeat may be a sequence of sibling lines (for example particle `NumEmitters N` followed by N repeats of an `EmitterType "x"` line plus an `EmitterContents` block), not only a named block; block extents still come from indentation
    - Define the `ReferenceLookup` protocol (`resolve(kind, name)` returning found, not found or unknown) with a null implementation, and a validation context bundling Registry, GameVersion, settings and lookup
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_

  - [ ] 5.5 Write property test for enumeration membership
    - **Property 9: Enumeration membership is version-gated**
    - **Validates: Requirements 3.2, 3.4, 3.9**

  - [ ] 5.6 Write property test for structural diagnostics
    - **Property 11: Structural diagnostics**
    - **Validates: Requirements 3.5, 3.6, 3.7**

  - [ ] 5.7 Write property test for condition branch isolation
    - **Property 12: Condition branch isolation**
    - **Validates: Requirements 3.8**

  - [ ] 5.8 Write unit tests for validator node types and primitives
    - Add at least one example test per Definition node type and per primitive type using synthetic Definitions
    - _Requirements: 11.3_

  - [ ] 5.9 Correct Definitions against the Rebellion 1.98 survey
    - Work from `reference/primitive-survey.md` and re-survey the Reference Root read-only; correct the bundled JSON for each gap below, and record every correction in `PROVENANCE.json` with game version Rebellion 1.98 and evidence (shapes and counts only)
    - Gaps: `Starscape` structure versus the `.starscapedata` files (mismatch); `.galaxy` `star[]` keys not placed in the Definition (about 2,150 uses); `ResearchSubject` `researchModifier` keys (about 1,281 uses) and 589 selector values with no match; `Player` (about 180); `.constants` `outlawSectorsData` (12); `.randomeventdefs` (12); `Buff` (1)
    - Also list the Position fields the survey never reached (`BrushType` `pixelBox`, `GalaxyStarType` `pos` and `planet[]` `pos`, `GalaxyPlanetType` `pos`, `ResearchBlock` `area`) and decide each constraint from evidence, or leave it unset
    - The zombiesrus5 plugin may not have validated `.galaxy`, so weak `galaxy.xml` coverage is expected. `plugin.xml` registers a Galaxy Editor for `galaxy` and the Definitions ship `galaxy.xml`, but the builder's handling of `.galaxy` is not covered by `reference/plugin-bytecode-findings.md`; verify it before treating a gap as a plugin omission
    - _Requirements: 12.1, 13.5_

- [ ] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Configuration and chain resolution
  - [ ] 7.1 Implement `engine/config.py`
    - Implement `ResolvedSettings`, `NumericPrefs`, `ManifestPrefs`, `ConfigProblem` and per-setting `SettingSource`
    - Resolve per setting in the order project `soase.json` (nearest, falling through to the next one above), environment variables, editor settings, user file via `platformdirs`, defaults (Rebellion 1.98, nearest manifest directory as Mod Root)
    - Resolve relative paths against the containing file, expand `~` and `%VAR%`/`$VAR`, report invalid settings by name and fall back to defaults, support `disabledCodes`, `defaultReferenceRoots` and `aliases`, and implement `effective_config`
    - Implement helpers that write `soase.json`/user-file values for Reference Roots and Layers (used by `init`, `config` and the MCP tools)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.12, 8.14, 8.15, 14.7, 14.18_

  - [ ] 7.2 Write property test for settings precedence
    - **Property 20: Settings precedence**
    - **Validates: Requirements 8.1, 8.14, 14.18**

  - [ ] 7.3 Write property test for invalid settings
    - **Property 21: Invalid settings degrade locally**
    - **Validates: Requirements 8.4**

  - [ ] 7.4 Write property test for path resolution
    - **Property 22: Path resolution**
    - **Validates: Requirements 8.12**

  - [ ] 7.5 Implement `engine/chain.py`
    - Implement `Layer`, `Chain`, `ChainProblem` and chain resolution: configured `layers` with alias expansion, depth-first `extends` splicing, cycle detection (`SOASE-C010`), lowest-position de-duplication, implicit Project top Layer, `missing`/`unusable` marking (`SOASE-C020`), and the `complete` flag
    - Use the Project's single Game Version and never read `EnabledMods.txt`
    - _Requirements: 4.6.1, 4.6.3, 14.1, 14.2, 14.3, 14.6, 14.7, 14.8, 14.9, 14.17_

  - [ ] 7.6 Write property test for chain construction
    - **Property 17: Chain construction**
    - **Validates: Requirements 14.1, 14.2, 14.6**

- [ ] 8. Reference index and layer cache
  - [ ] 8.1 Implement `engine/refindex.py`
    - Define a `FileSystem` protocol with real and in-memory implementations, `RefKind`, `Entry`, `LayerIndex` (casefolded names, manifests, files, signature) and the per-Layer builder that scans only standard game data directories and root files and skips hidden and VCS directories
    - Implement incremental update of a single changed file and signature computation from `(relpath, size, mtime_ns)`
    - _Requirements: 4.1, 4.2, 4.2.1, 4.7, 14.4.1, 14.10_

  - [ ] 8.2 Implement `engine/layercache.py`
    - Add the in-memory cache keyed by `(resolved path, game version)` and the JSON on-disk cache in the platform cache directory with schema version, discarding corrupt or stale files and ignoring write failures
    - _Requirements: 14.10_

  - [ ] 8.3 Implement merged lookup and wire references into validation
    - Implement `ChainIndex.resolve` (highest Layer wins, casefolded, `Resolution` with `overrides`), manifest-governed name sets limited to the governing manifest, and `Unknown` results for incomplete chains
    - Plug it into the validator as the `ReferenceLookup`, emit unresolved-reference diagnostics (`SOASE-R010`) naming type and value, and emit the single suppressible informational `SOASE-C030` per file listing missing Layers
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6.1, 4.6.2, 4.6.5, 14.4, 14.5, 14.12_

  - [ ] 8.4 Implement dependency tracking
    - Record per validated file the set of `(Layer, RefKind, name)` it resolved, and compute dependents to re-validate from added and removed index names on save or file-watcher events
    - _Requirements: 4.8, 14.11_

  - [ ] 8.5 Write Hypothesis strategies for chains
    - Create `tests/strategies/chains.py` generating Layers on the in-memory `FileSystem` with overlapping names in varying case, hidden and VCS directories, and complete and incomplete chains
    - _Requirements: 4.3, 14.4.1, 14.5_

  - [ ] 8.6 Write property test for highest Layer wins
    - **Property 13: Highest Layer wins, case-insensitively**
    - **Validates: Requirements 4.3, 4.4, 14.5, 14.12**

  - [ ] 8.7 Write property test for directory scanning
    - **Property 18: Directory scanning excludes non-game data**
    - **Validates: Requirements 14.4.1**

  - [ ] 8.8 Write property test for incremental index
    - **Property 15: Incremental index equals full rebuild**
    - **Validates: Requirements 4.7**

  - [ ] 8.9 Write property test for layer cache validity
    - **Property 16: Layer cache validity**
    - **Validates: Requirements 14.10**

  - [ ] 8.10 Write property test for unresolved references on complete chains only
    - **Property 14: Unresolved references are reported only on complete chains**
    - **Validates: Requirements 4.5, 4.6.1, 4.6.2**

  - [ ] 8.11 Write unit tests for the reference index
    - Cover incomplete-chain messages, the missing-Layer warning, override reporting, corrupt cache recovery, and validation with no Reference Root configured
    - _Requirements: 4.6, 14.9, 14.15_

- [ ] 9. Manifest service
  - [ ] 9.1 Implement manifest parsing and formatting in `engine/manifests.py`
    - Load `manifest_rules.json`, implement `ManifestData` parsing with per-type count and name keys, extension rules, case-insensitive matching, header style and line-ending detection, and a formatter
    - _Requirements: 15.1, 15.1.1_

  - [ ] 9.2 Write property test for manifest round trip
    - **Property 27: Manifest parse and format round trip**
    - **Validates: Requirements 15.1**

  - [ ] 9.3 Implement governing-manifest selection and `manifest_check`
    - Select the governing manifest from the highest Layer providing each type, compute governed file sets by extension and directory (skybox subset from `.skyboxbackdropdata` `meshName` values), and emit `SOASE-M010`, `SOASE-M020` (configurable severity), `SOASE-M030` and `SOASE-M040`
    - Honour the shipped base-game-unlisted list and user exemption patterns, and include the lower-Layer wording in `SOASE-M010`
    - _Requirements: 14.4, 14.19, 15.2, 15.3, 15.3.1, 15.3.2, 15.3.3, 15.3.4, 15.3.5, 15.4, 15.4.1, 15.5, 15.6_

  - [ ] 9.4 Write property test for governing manifest selection
    - **Property 19: Governing manifest selection**
    - **Validates: Requirements 14.4, 14.19**

  - [ ] 9.5 Write property test for unlisted-file detection
    - **Property 28: Unlisted file detection**
    - **Validates: Requirements 15.2, 15.3**

  - [ ] 9.6 Write property test for manifest hygiene diagnostics
    - **Property 29: Manifest hygiene diagnostics**
    - **Validates: Requirements 15.4, 15.5, 15.6**

  - [ ] 9.7 Implement `plan_sync`, `SyncPlan` and `manifest_apply`
    - Implement the pure planner that preserves entries, order, header and line endings, appends only unlisted names, rewrites the count line, supports opt-in removal, and returns advisories instead of edits for lower-Layer manifests
    - Implement the side-effecting apply with `.bak` backups (numeric suffix when present), temporary file plus atomic replace, and dry-run diff output
    - _Requirements: 15.8, 15.8.1, 15.8.2, 15.8.3, 15.8.4, 15.8.5, 15.8.6_

  - [ ] 9.8 Write property test for sync preserving content
    - **Property 30: Sync preserves existing content**
    - **Validates: Requirements 15.8.1**

  - [ ] 9.9 Write property test for sync then check
    - **Property 31: Sync then check is clean**
    - **Validates: Requirements 15.3, 15.5, 15.8**

  - [ ] 9.10 Write property test for opt-in removal
    - **Property 32: Removal is opt-in**
    - **Validates: Requirements 15.8.4**

  - [ ] 9.11 Write property test for lower-Layer manifests
    - **Property 33: Lower-Layer manifests are never edited**
    - **Validates: Requirements 15.8.5, 15.3.1**

  - [ ] 9.12 Write manifest unit tests
    - Cover the `skybox.manifest` governed subset, an overlay without manifests, extension-less `galaxy.manifest` names, backup creation and failed-write safety
    - _Requirements: 14.19, 15.3.3, 15.8.3_

- [ ] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Completion, hover and go-to-definition
  - [ ] 11.1 Implement `engine/completion.py`
    - Locate the cursor context in a tolerant `ParsedFile`; return key completions (enclosing structure or selected branch, excluding present keys), value completions (version-gated enum members, `entityType` values, reference names from the `ChainIndex` shown once with the originating Layer in `detail`), case-insensitive prefix filtering and Definition help as documentation
    - Implement hover for keys, enum values and reference values (providing and overridden Layer) returning nothing for undefined keys, and go-to-definition returning the highest Layer's file
    - Limit reference completions to usable Layers on incomplete chains
    - _Requirements: 4.6.4, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 7.1, 7.2, 7.3, 14.12, 14.13, 14.14_

  - [ ] 11.2 Write property test for completion correctness
    - **Property 24: Completion correctness**
    - **Validates: Requirements 6.2, 6.4, 6.5, 6.6**

  - [ ] 11.3 Write property test for reference completions
    - **Property 25: Reference completions are unique and layer-attributed**
    - **Validates: Requirements 4.6.4, 6.3, 14.14**

  - [ ] 11.4 Write completion and hover unit tests
    - Cover `entityType` completion, hover with no Definition, hover on overridden references and go-to-definition across Layers
    - _Requirements: 6.7, 7.3, 14.12, 14.13_

- [ ] 12. Engine facade
  - [ ] 12.1 Implement `engine/facade.py`
    - Implement the `Engine` class with the methods in the design: settings and effective config, `validate_file`, `validate_directory`, `complete`, `hover`, `definition`, `field_help`, `entity_types`, `on_file_saved`, `on_layer_files_changed`, `manifest_check`, `manifest_plan`, `manifest_apply`
    - Combine parser, validator, chain and manifest diagnostics, apply disabled codes in one place, report optional override informational diagnostics when `reportOverrides` is set, cache the Registry, indexes and Chain, and catch unexpected exceptions logging to stderr, returning partial diagnostics plus `SOASE-X001`
    - Validate only files within the Project's Mod Roots and rebuild indexes when the Game Version changes
    - _Requirements: 4.2.1, 4.7, 4.8, 8.5, 9.6, 11.5, 14.3, 14.15, 15.7_

  - [ ] 12.2 Write Engine integration tests
    - Cover internal-error recovery, `validate_directory`, `on_file_saved` dependent discovery, overlay projects, and per-folder `soase.json` chains using synthetic trees
    - _Requirements: 4.8, 11.5, 14.11, 14.18, 14.19_

  - [ ] 12.3 Write the opt-in performance check
    - Add a test marked `perf` (excluded from the default run) that checks a typical `.entity` validation completes within 500 ms on a warm index using a synthetic file, and skips when the reference root is absent
    - _Requirements: 5.6_

- [ ] 13. LSP server
  - [ ] 13.1 Implement `lsp/server.py`
    - Build the pygls server with full-text sync, publishing diagnostics on `didOpen` and `didSave`, clearing on `didClose`, completion, hover and definition handlers, running Engine calls via `asyncio.to_thread`, and logging to stderr only
    - Convert Engine `Diagnostic` to `lsprotocol` types (info maps to Information) and wire the `soase-validator-lsp` entry point
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 7.1, 14.13_

  - [ ] 13.2 Add code actions, file watching and configuration reload
    - Offer the "Add to manifest" code action for `SOASE-M010` only when the governing manifest is in the Project, using `plan_sync` to build the `WorkspaceEdit`
    - Handle `didChangeWatchedFiles` for Layer files, `soase.json` and the user file, and handle initialization options and `didChangeConfiguration` as the editor settings tier, re-validating open files and dependents
    - _Requirements: 4.8, 8.13, 8.14, 14.11, 15.9_

  - [ ] 13.3 Write LSP tests with the pygls test client
    - Cover publish on open and save, clearing on close and after a fix, completion, hover, definition, the code action and configuration reload
    - _Requirements: 5.1, 5.3, 5.4, 5.5, 8.13, 15.9_

- [ ] 14. MCP server
  - [ ] 14.1 Implement `mcp_server/app.py` core tools
    - Using `MCPServer` from `mcp.server`, register `validate_file`, `validate_directory`, `complete`, `field_help`, `list_entity_types`, `manifest_check` and `manifest_sync` (dry run by default) and the `soase://definitions/{structure}` resource, returning diagnostics as structured data with one-based `file`, `line`, `column`, `severity`, `code`, `message`
    - Keep all SDK-specific code in this module, keep stdout clean for the stdio transport, and wire the `soase-validator-mcp` entry point
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 15.10_

  - [ ] 14.2 Add configuration tools
    - Add `get_config` (effective config with sources, Reference Root found status and the resolved Chain in order with path, kind and found status), `set_reference_root` and `edit_layers` (add, remove, reorder)
    - _Requirements: 8.15, 8.16, 14.16_

  - [ ] 14.3 Write property test for diagnostic conversion
    - **Property 26: Diagnostic conversion is lossless**
    - **Validates: Requirements 5.2, 9.6, 9.7**

  - [ ] 14.4 Write MCP tests
    - Invoke each tool function directly and through the SDK in-memory client, covering validation, completion, help, entity types, config tools, manifest tools, resources, and identical diagnostics to the Engine
    - _Requirements: 8.15, 8.16, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 15.10_

- [ ] 15. Command-line interface
  - [ ] 15.1 Implement `cli/main.py` with `init` and `config`
    - Add the argparse entry point, `init` (options and TTY prompts, using the user-level default Reference Root and printing which path was used, succeeding without a root and printing how to add one), `config set-reference-root` (warn when the path is missing or not game data but still save) and `config show`
    - _Requirements: 8.7, 8.8, 8.9, 8.10, 8.11, 8.15_

  - [ ] 15.2 Add `manifest check` and `manifest sync`
    - Implement `manifest check`, and `manifest sync [--write] [--remove-stale]` printing a unified diff by default, writing with backups only with `--write`, listing entries before removal, and printing advisories for lower-Layer manifests
    - _Requirements: 15.7, 15.8, 15.8.2, 15.8.3, 15.8.4, 15.8.5, 15.8.6_

  - [ ] 15.3 Add the `versions` command
    - List Game Versions with audit status (Rebellion 1.98 audited, others "unaudited, best-effort") and unverified gate tokens from `versions.json`
    - _Requirements: 13.7, 13.8_

  - [ ] 15.4 Write CLI tests
    - Cover `init` with and without a root and with a user default, `set-reference-root` warnings, dry-run default for `manifest sync`, `--write` backup creation, `--remove-stale` listing and `versions` output
    - _Requirements: 8.7, 8.8, 8.9, 8.10, 8.11, 13.7, 15.7, 15.8_

- [ ] 16. Audit tool and Rebellion 1.98 audit
  - [ ] 16.1 Implement `audit/audit.py`
    - Validate every file in a Reference Root with no Chain beyond that root, classify diagnostics as likely Definition gap (key or value in at least `N` distinct files, default 3) or likely file problem, list keys and enum values seen in files but absent from Definitions, list Definition fields and enum values never seen, and write `audit-report.json` and a human summary to a git-ignored output directory
    - Exit non-zero with a clear message when no Reference Root is supplied or configured
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.6_

  - [ ] 16.2 Add the `audit` CLI command
    - Wire `audit --reference-root PATH` into `cli/main.py` with a threshold option and output directory
    - _Requirements: 13.1, 13.6_

  - [ ] 16.3 Write property test for audit classification
    - **Property 34: Audit classification and coverage sets**
    - **Validates: Requirements 13.2, 13.3, 13.4**

  - [ ] 16.4 Run the Rebellion 1.98 audit and correct the Definitions
    - Run the audit with `--reference-root` or `SOASE_REFERENCE_ROOT_REBELLION_198` using the path the user supplies (ask the user for it if it is not configured), reading it in place and writing reports only to the git-ignored output directory
    - Fix each Definition gap in the bundled JSON, record every correction with the Game Version and evidence in `PROVENANCE.json`, and re-run until the audit reports zero errors
    - Do not copy any reference file or content into the repository
    - _Requirements: 13.5, 13.7, 11.2, 12.6_

  - [ ] 16.5 Verify version gates and derive the base-game-unlisted list
    - Verify each gate token interpretation against the Rebellion 1.98 data, determine whether 1.98 needs rules beyond gate level 194, record overrides and `unverified` tokens in `versions.json`, and write `docs/version-gates.md`
    - Derive the list of base-game files left unlisted by each manifest and store it in `manifest_rules.json` as names only, with no game content
    - _Requirements: 13.7, 13.8, 15.3.4_

  - [ ] 16.6 Write the golden-file test
    - Create `tests/test_golden.py` running the audit routine over each available Reference Root (configuration or `SOASE_REFERENCE_ROOT_<VERSION>`), asserting zero errors, and skipping with an explanatory message when none is available
    - _Requirements: 11.2, 11.2.1_

- [ ] 17. Documentation, attribution and distribution checks
  - [ ] 17.1 Write `README.md`
    - Describe the tool, supported Game Versions with audit status, what is validated, `uvx --from git+https://github.com/<owner>/soase-validator` installation, configuration (`init`, `soase.json`, user file, Reference Roots, parent Layers, Game Version), use from Kiro, VS Code and MCP clients with and without a Reference Root, the diagnostic code catalogue, and the unofficial-tool and no-game-assets statements
    - Add the Credits section naming zombiesrus5, GoaFan77, and Stardock Entertainment and Ironclad Games with what each contributed and where it is used, and the scope of the MIT license versus third-party works
    - _Requirements: 10.5, 12.3, 12.4, 12.5, 12.6, 13.7, 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.8_

  - [ ] 17.2 Add `LICENSE`, `NOTICE` and finalize provenance
    - Add the MIT `LICENSE`, a `NOTICE` file listing the third-party attribution, and make sure `PROVENANCE.json` records origin, author, version and audit corrections
    - _Requirements: 12.1, 12.3, 12.4, 16.7, 16.8_

  - [ ] 17.3 Write the credits test
    - Fail if the README lacks any credited party named in the requirements (zombiesrus5, GoaFan77, Stardock Entertainment, Ironclad Games) or the unofficial-tool statement
    - _Requirements: 16.4, 16.5, 16.9_

  - [ ] 17.4 Write smoke and repository hygiene tests
    - Check that `import soase_validator` works, the three entry points start and answer (LSP and MCP initialize), no network use occurs, and the repository tree contains no game asset extensions (`.mesh`, `.dds`, `.ogg`, base game `.entity` sets)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 12.6_

- [ ] 18. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP.
- Each task references specific requirements for traceability.
- Checkpoints ensure incremental validation.
- Property tests validate universal correctness properties; unit tests validate specific examples and edge cases.
- Requirement 13.7 makes completing task 16.4 a release prerequisite, because unknown keys are errors and Definition gaps appear as false errors.
- Reference game files are only ever read in place from the user-supplied location. Tests that need them skip when the path is absent.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "2.3"] },
    { "id": 3, "tasks": ["2.2", "2.4", "3.1", "4.1", "5.1", "7.1"] },
    { "id": 4, "tasks": ["3.2", "3.5", "4.2", "4.10", "5.2", "5.3", "5.4", "7.2", "7.3", "7.4", "7.5"] },
    { "id": 5, "tasks": ["3.3", "3.4", "3.6", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9", "5.5", "5.6", "5.7", "5.8", "5.9", "7.6", "8.1"] },
    { "id": 6, "tasks": ["8.2", "8.3", "8.5", "9.1"] },
    { "id": 7, "tasks": ["8.4", "8.6", "8.7", "8.8", "8.9", "8.10", "8.11", "9.2", "9.3"] },
    { "id": 8, "tasks": ["9.4", "9.5", "9.6", "9.7", "11.1"] },
    { "id": 9, "tasks": ["9.8", "9.9", "9.10", "9.11", "9.12", "11.2", "11.3", "11.4"] },
    { "id": 10, "tasks": ["12.1"] },
    { "id": 11, "tasks": ["12.2", "12.3", "13.1", "14.1", "15.1", "16.1"] },
    { "id": 12, "tasks": ["13.2", "14.2", "14.3", "15.2", "16.3"] },
    { "id": 13, "tasks": ["13.3", "14.4", "15.3"] },
    { "id": 14, "tasks": ["15.4", "16.2"] },
    { "id": 15, "tasks": ["16.4"] },
    { "id": 16, "tasks": ["16.5", "16.6", "17.2"] },
    { "id": 17, "tasks": ["17.1", "17.4"] },
    { "id": 18, "tasks": ["17.3"] }
  ]
}
```
