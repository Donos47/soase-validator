---
inclusion: always
---

# Product

`soase-validator` is Java-free language tooling for Sins of a Solar Empire (Sins 1) mod files. It reproduces the validation and field-discovery features of zombiesrus5's Eclipse SoaSE plugin for modern editors and AI tools.

## Capabilities

- Validate mod files from the CLI, the MCP server and the LSP server (`.entity`, `.galaxy`, `.brushes`, `.sounddata`, `.str`, `.constants`, `.galaxyScenarioDef`, `.particle`, `.explosiondata`, and others) against declarative Definitions.
- Completion, hover help and go-to-definition for keys, enum values and cross-file references.
- Resolve references across a Chain of Layers (base game, parent mods, the project).
- Check and sync `*.manifest` files (`manifest check`, `manifest sync`).

## Front ends

One shared Engine, three thin front ends: LSP server, MCP server (for AI agents) and CLI. Identical input must produce identical Diagnostics in all of them.

The MCP server also exposes configuration (`configure`, `get_config`, `set_reference_root`, `edit_layers`) and `versions`, and is intended to cover everything the CLI does.

Definitions are audited against a base game Reference Root by a developer-only script (`tools/audit.py`), which is not shipped.

## Targets

- Game versions: Vanilla, Entrenchment, Diplomacy, Rebellion (gate levels 185, 193, 194) and Rebellion 1.98.
- Rebellion 1.98 is the primary target and the only audited version. Its files use the template format `SinsArchiveVersion` 194, which is a file-format revision and not a game version. All others are "unaudited, best-effort". A bare "Rebellion" means 1.98.
- Out of scope: Sins II, binary assets (`.mesh`, `.dds`, `.ogg`), formatting and refactoring.

## Key rules

- Runs fully offline and never transmits mod content.
- Reference Roots and parent Layers are optional. Without them, everything not dependent on other Layers still works. Unresolved references are still reported against the Layers that are configured, including the Project alone, so a reference to a base game name reports as unresolved until a Reference Root provides it. Reference checks are limited (no unresolved-reference errors, one `SOASE-C030` notice per file) only when a declared Layer is missing or unusable.
- Never include or copy game assets or base game files into the repo, tests or docs. Read them in place only.
- Never put machine-specific absolute paths in source, tests, fixtures or docs. Use placeholders like `~/path/to/sins-rebellion-reference`.
- Unofficial community tool. Credit zombiesrus5 (original plugin and Definitions), GoaFan77 (manifest updater script) and Stardock Entertainment / Ironclad Games (the game).
- The feature spec lives in `.kiro/specs/soase-validator/` (requirements, design, tasks). Consult it before implementing.
