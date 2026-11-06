---
inclusion: always
---
# Verify Against Reference Material

This tool exists to match real game data and the zombiesrus5 Definitions exactly. Guessing, or choosing a permissive behaviour "to be safe", produces wrong diagnostics and is not acceptable. This rule applies to the main agent and to every sub-agent, including `spec-task-execution`. Pass it on when delegating.

## Sources, in order of authority

1. The Rebellion 1.98 Reference Root (`SOASE_REFERENCE_ROOT_REBELLION_198` or the configured `referenceRoots` entry). Read in place only.
2. `reference/zombiesrus5-xml-definitions/` (the original Definitions and `entity_definitions.xsd`).
3. The zombiesrus5 compiled plugin jar (`~/Downloads/com.zombiesrus5.plugin.sose_1.0.0.<build>.jar`). Read in place, class files only; record findings in `reference/plugin-bytecode-findings.md`.
4. `.kiro/specs/soase-validator/requirements.md` and `design.md`.

If sources disagree, real files in the Reference Root win over the design text. Record the disagreement, do not paper over it.

Game data outranks the plugin. The plugin is a cross-check for shapes the game data does not show, not a source of rules. Where this tool deliberately differs from the plugin, or accepts a shape no real file uses, that must be an explicit user decision recorded in `design.md` (example: Coordinate items written as integers).

## Rules

- Before implementing any rule about a value shape, count, range, enum member, key or file layout, find evidence in the sources above. Cite the evidence (file kind, key, observed shapes and counts) in the task summary and in the module or test docstring.
- Never use "lenient", "tolerant" or "accept what occurs" as a stand-in for knowing the rule. Tolerance belongs to parser recovery only (report the parsed portion, keep going). Validators and checkers accept exactly what the evidence supports and reject the rest.
- Do not invent constants such as accepted list lengths, hex digit counts or numeric ranges. Derive them from the sources. Where the sources are silent or contradictory, stop and ask the user. Do not choose a default.
- Survey the Reference Root with a read-only script (tally shapes per key, per extension) before writing the checker. Do not copy game content into the repo, tests, or docs. Record only names, shapes and counts. Use placeholders for paths, never machine-specific absolute paths.
- If the survey shows an upstream component (for example the parser) cannot represent real data, report it. Do not work around it inside the downstream component.
- Tests must include real-shaped examples from the survey (synthetic reproductions of the shape, not copied game files), plus at least one rejected shape per rule.
- A Definition correction goes in the bundled JSON and is recorded in `PROVENANCE.json` with game version and evidence.
- When delegating a task, the brief must say which sources to read first and that unverifiable rules must be raised, not guessed.
- If a rule would reject a shape that real files use, stop and report instead of enforcing it.
- Sub-agents must not change task statuses in `tasks.md` unless told to.
