---
inclusion: always
---

# Product

`sose-validator` is Java-free language tooling for Sins of a Solar Empire (Sins 1) mod files. It reproduces the validation and field-discovery features of zombiesrus5's Eclipse SoSE plugin for modern editors and AI tools.

## Capabilities

- Validate mod files (`.entity`, `.galaxy`, `.brushes`, `.sounddata`, `.str`, `.constants`, `.galaxyScenarioDef`, `.particle`, `.explosiondata`, and others) against declarative Definitions.
- Completion, hover help and go-to-definition for keys, enum values and cross-file references.
- Resolve references across a Chain of Layers (base game, parent mods, the project).
- Check and sync `*.manifest` files (`manifest check`, `manifest sync`).
- Audit Definitions against a base game Reference Root.

## Front ends

One shared Engine, three thin front ends: LSP server, MCP server (for AI agents) and CLI. Identical input must produce identical Diagnostics in all of them.

## Targets

- Game versions: Vanilla, Entrenchment, Diplomacy, Rebellion (gate levels 185, 193, 194) and Rebellion 1.96.
- Rebellion 1.96 is the primary target and the only audited version. All others are "unaudited, best-effort". A bare "Rebellion" means 1.96.
- Out of scope: Sins II, binary assets (`.mesh`, `.dds`, `.ogg`), formatting and refactoring.

## Key rules

- Runs fully offline and never transmits mod content.
- Reference Roots and parent Layers are optional. Without them, everything not dependent on other Layers still works, and unresolved-reference errors are suppressed.
- Never include or copy game assets or base game files into the repo, tests or docs. Read them in place only.
- Never put machine-specific absolute paths in source, tests, fixtures or docs. Use placeholders like `~/path/to/sins-rebellion-reference`.
- Unofficial community tool. Credit zombiesrus5 (original plugin and Definitions), GoaFan77 (manifest updater script) and Stardock Entertainment / Ironclad Games (the game).
- The feature spec lives in `.kiro/specs/sose-validator/` (requirements, design, tasks). Consult it before implementing.
