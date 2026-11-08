# Implementation Plan: vscode-syntax-highlighting

## Overview

The Extension in `vscode-extension/` gains one static TextMate grammar for the Language Identifier `soase`. The plan first records the dependencies and manifest contribution and bumps the version, then writes the grammar file, the test helper, the unit test and the ten property tests, then changes the VSIX contents-check allow-list (with its one-time manual negative check), then updates the documentation and steering files, and ends with a final checkpoint that rebuilds the VSIX and verifies it holds the grammar once.

Conventions for every task:

- Language is TypeScript on Node 24 for the test code and scripts, and JSON for the grammar. Style: 2-space indent, single quotes, semicolons, trailing commas, kebab-case file names, JSDoc on every exported symbol.
- Comments say why, never what. No change history, task numbers, chat history, survey counts, Reference Root file names or machine-specific absolute paths in code, grammar, tests, manifest or docs. Use placeholders such as `~/path/to/sins-rebellion-reference`.
- Interface names, signatures, Scope Names, regular expressions and file paths follow `design.md` exactly (sections "Scope Names", "Grammar file", "Test helper", "Unit test", "Property test", "Packaging data"). A task that needs to deviate stops, reports the deviation, and updates `design.md` in the same change.
- Evidence and verification (reference-verification rule): the shape rules come from `requirements.md` and `design.md`, which cite the Reference Root survey, the Engine parser and the plugin notes. Tasks add no new shape rule. A shape that cannot be verified against those documents is raised with the user and not guessed.
- The Grammar is static data. No task adds runtime code, a runtime dependency, a setting, a semantic tokens provider, an LSP message or a theme contribution to the Extension. No task changes the Python package.
- `vscode-extension/package.json` and `vscode-extension/package-lock.json` already carry uncommitted changes, and `vscode-extension/images/` is untracked; neither comes from this spec. Before editing either file, read its current content and `git status`, keep every existing change as is, never revert, restore or stage them, and never touch `images/`. The version bump is relative to the version found at that time and must end at `0.2.0`.
- Checks for JSON and TypeScript files use `get_diagnostics` first, then `npm run compile` and `npm run lint`. Temporary files live in the system temp folder and are deleted afterwards.
- Run in `vscode-extension/` with PowerShell: chain with `;` or `if ($?)`, never `&&`. Check current dependency versions on npm before adding a dependency and run `npm audit` afterwards, reporting high and critical findings.
- Task statuses in this file are changed only by the orchestrator.

## Tasks

- [ ] 1. Record dependencies and manifest changes
  - [ ] 1.1 Add the test engine dev dependencies
    - Read the current `vscode-extension/package.json`, `package-lock.json` and `git status` first; keep all existing uncommitted changes
    - Re-check `vscode-textmate` and `vscode-oniguruma` on npm; add them to `devDependencies` with the ranges `^9.3.2` and `^2.0.1` from the design (or the current ranges that include the latest release, noting any deviation), using `npm install --save-dev` in `vscode-extension/`
    - Confirm `dependencies` still lists only `vscode-languageclient`, then run `npm audit` and report findings of high or critical severity
    - _Requirements: 2.3, 11.6_

  - [ ] 1.2 Contribute the grammar in the manifest
    - Read the current `vscode-extension/package.json`; add `contributes.grammars` with exactly one entry: `language` `soase`, `scopeName` `source.soase`, `path` `./syntaxes/soase.tmLanguage.json`
    - Leave the `languages` entry, its nine file extensions, `activationEvents` and `.vscodeignore` as they are; add no `semanticTokenTypes`, `semanticTokenModifiers`, `semanticTokenScopes` or `configurationDefaults`
    - _Requirements: 1.1, 1.3, 1.4, 1.8, 2.3, 2.4_

  - [ ] 1.3 Bump the Extension version
    - Read the current `version` in `package.json` and `package-lock.json`, then run `npm version --no-git-tag-version minor` in `vscode-extension/`
    - Confirm `package.json` `version` and both root entries in `package-lock.json` (`version` and `packages[""].version`) read `0.2.0`, and that the rest of the uncommitted changes in both files is intact
    - _Requirements: 12.1, 12.2_

- [ ] 2. Write the grammar
  - [ ] 2.1 Create the TextMate grammar file
    - Create `vscode-extension/syntaxes/soase.tmLanguage.json` with the JSON from the design section "Grammar file": scope name `source.soase`, the eight flat line-anchored rules in the given order (Equals Form, Number, Hex, Bool, String, List with Key, Keyless Row, Key only) and the `items` repository entry; no `begin` or `end` property at any depth, no comment scope, ASCII character classes only
    - Use exactly the seven Scope Names of the design table (`support.type.property-name.soase`, `string.quoted.double.soase`, `constant.numeric.soase`, `constant.other.color.soase`, `constant.language.boolean.soase`, `punctuation.definition.list.soase`, `keyword.operator.assignment.soase`)
    - Check the file with `get_diagnostics`; keep it free of counts, file names and paths
    - _Requirements: 1.2, 1.5, 1.6, 1.7, 2.1, 2.2, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 10.4, 12.9_

- [ ] 3. Test support and unit test
  - [ ]* 3.1 Implement the grammar test helper
    - Create `vscode-extension/test/support/grammar-loader.ts` exporting `CharScopes`, `loadGrammar`, `readGrammarContribution`, `scopesOf` and `tokenizeFile` exactly as in the design: read the manifest with `fs`, load `vscode-oniguruma/release/onig.wasm` once per process, build the `Registry` with `onigLib`, clip token end indexes to the Line length, return the leaf scope per UTF-16 code unit, and compare stacks against the stack of an empty Line
    - Add the failure reporter `expectScope(line, start, end, expected)` that throws an `assert.AssertionError` naming the snippet text, the expected Scope Name and the actual Scope Name
    - Import no `vscode` module, start no Server, use no network; confirm `npm run compile` and `npm run lint` accept the file and that mocha does not pick it up as a test file
    - _Requirements: 11.1, 11.5, 11.6, 11.8_

  - [ ]* 3.2 Write the grammar unit test
    - File `vscode-extension/test/unit/grammar.test.ts` with synthetic text only, covering the design section "Unit test": the manifest test (language, scope name, existing path, nine extensions with no `.manifest`, no semantic token or `configurationDefaults` keys, `dependencies` limited to `vscode-languageclient`); the pairwise-different Scope Names and the absence of any comment scope; one test per snippet of Requirement 11.2 (quoted string, empty string, string with `'` and `\`, unterminated string, integer, signed decimal, lowercase and uppercase Hex, digits-only token, `TRUE`, `FALSE`, `true`, `True`, comma list, whitespace list, Keyless Row, Equals Form, `k = "v`); the rejected shapes of Requirement 11.3 (`'text'`, `1.2.3`, `0x10`, `ffg`, `TRUEX`, `truex`, `[ 1 , x ]`, `key= "v"`) and text after `]`; a `//`-prefixed Line; `k ="v"`, `k = 5`, `k =`, `1e5` as number, `"TRUE"` as string, `TXT` and `TXT2` as Key and `TXT` on line 2 as Key; and the check that the grammar JSON holds no `begin` or `end` property
    - _Requirements: 1.1, 1.4, 1.8, 2.3, 2.4, 3.4, 4.5, 6.3, 7.4, 7.5, 9.2, 10.1, 10.3, 10.4, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8_

- [ ] 4. Property tests
  - [ ]* 4.1 Write property test for single-line dependence
    - **Property 1: Grammar scopes depend only on a single line**
    - **Validates: Requirements 2.1, 4.4, 8.4, 8.5**
    - File `vscode-extension/test/properties/grammar.property.test.ts`, first line of the property tagged `// Feature: vscode-syntax-highlighting, Property 1: Grammar scopes depend only on a single line`, `numRuns` of 200; add the oracle regular expressions `NUMBER_VALUE`, `HEX_VALUE` and `BOOL_VALUE` and the generators of the design table once in this file, written from the glossary and not copied from the grammar
    - _Requirements: 2.1, 4.4, 8.4, 8.5_

  - [ ]* 4.2 Write property test for Key independence of the Value
    - **Property 2: A Value's scope does not depend on its Key**
    - **Validates: Requirements 2.2, 4.8**
    - Same file, tagged `Property 2`, `numRuns` of 200
    - _Requirements: 2.2, 4.8_

  - [ ]* 4.3 Write property test for the exact Key span
    - **Property 3: The Key span is exact**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.5, 3.6, 3.7, 10.2**
    - Same file, tagged `Property 3`, Keys include the `//`, `#` and `;` prefixes and `=`, `"` and `'` characters
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 3.7, 10.2_

  - [ ]* 4.4 Write property test for exact string spans
    - **Property 4: String spans are exact**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.6, 4.7**
    - Same file, tagged `Property 4`, content without `"`, `\n` and `\r`, with and without trailing text and closing quote
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6, 4.7_

  - [ ]* 4.5 Write property test for Number Values
    - **Property 5: Number Values get the number scope**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.6, 6.3**
    - Same file, tagged `Property 5`, any digit count, sign, leading or trailing point and exponent, with optional trailing whitespace
    - _Requirements: 5.1, 5.2, 5.3, 5.6, 6.3_

  - [ ]* 4.6 Write property test for Hex Values
    - **Property 6: Hex Values that are not numbers get the hex scope**
    - **Validates: Requirements 6.1, 6.2, 6.4, 6.7**
    - Same file, tagged `Property 6`, generator filtered with the `NUMBER_VALUE` oracle
    - _Requirements: 6.1, 6.2, 6.4, 6.7_

  - [ ]* 4.7 Write property test for booleans
    - **Property 7: Booleans in any capitalization get the boolean scope**
    - **Validates: Requirements 7.1, 7.3**
    - Same file, tagged `Property 7`, random case per character of `true` and `false`
    - _Requirements: 7.1, 7.3_

  - [ ]* 4.8 Write property test for tokens of no value shape
    - **Property 8: Tokens of no value shape get no value scope**
    - **Validates: Requirements 5.4, 5.5, 6.6, 7.2, 9.4**
    - Same file, tagged `Property 8`, includes `boolNearMiss`, `denseToken`, `=`-led tokens and a Number Value followed by a further token
    - _Requirements: 5.4, 5.5, 6.6, 7.2, 9.4_

  - [ ]* 4.9 Write property test for lists and Keyless Rows
    - **Property 9: List items and delimiters**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.6, 8.7**
    - Same file, tagged `Property 9`, comma and whitespace separated items, with and without `]`, Keyed and Keyless, text after the first `]`
    - _Requirements: 8.1, 8.2, 8.3, 8.6, 8.7_

  - [ ]* 4.10 Write property test for the Equals Form
    - **Property 10: Equals Form operator**
    - **Validates: Requirements 4.8, 9.1, 9.2, 9.3, 9.5**
    - Same file, tagged `Property 10`, terminated and unterminated strings, and the attached `=` variant with no operator scope
    - _Requirements: 4.8, 9.1, 9.2, 9.3, 9.5_

- [ ] 5. Packaging contents check
  - [ ] 5.1 Add the grammar to the contents-check allow-list
    - Read `vscode-extension/scripts/check-vsix-contents.mjs` first. Add the constant `GRAMMAR_FILE = 'syntaxes/soase.tmLanguage.json'`, add it to `REQUIRED_FILES`, and exempt that exact path in the first-party JSON rule (`file !== GRAMMAR_FILE`); an exact path match, not a directory or pattern
    - Keep every other first-party data file, `definitions` directory, game extension and Python file rejected, with a non-zero exit code and the rejected file named
    - Keep JSDoc and comments in the script free of change history
    - _Requirements: 12.3, 12.4_

  - [ ] 5.2 Run the one-time manual negative check
    - Run once, outside the test suite: add a second first-party JSON file (for example `vscode-extension/syntaxes/extra.json`), run `node node_modules/@vscode/vsce/vsce ls | node scripts/check-vsix-contents.mjs` in `vscode-extension/` using the design's command adapted to PowerShell, observe a non-zero exit code and the file named, then delete the file
    - Run the same command with the file removed: exit code 0 and `syntaxes/soase.tmLanguage.json` listed exactly once
    - Leave no stray file in the repository; do not add this check to the test suite
    - _Requirements: 12.3, 12.4_

- [ ] 6. Documentation and steering updates
  - [ ] 6.1 Update the Extension README
    - Add a "Syntax coloring" section to `vscode-extension/README.md` naming the categories (key, string, number, hex color, boolean, list punctuation) and the `=` operator, stating that coloring follows token shape only, that Definition-aware coloring is not provided, that coloring works without the Server, and that booleans are matched in any capitalization although the Server reports lowercase ones; leave "Supported files" as it is; placeholder paths only
    - _Requirements: 12.7, 12.9_

  - [ ] 6.2 Update the project README
    - In the root `README.md`, remove the "Syntax coloring for the supported file types in code editors." bullet from the planned list and state syntax coloring as available in the VS Code section; read the current file first and keep unrelated edits
    - _Requirements: 12.6, 12.9_

  - [ ] 6.3 Update the structure steering file
    - In `.kiro/steering/structure.md` add `syntaxes/  # soase.tmLanguage.json, the contributed TextMate grammar` and `test/support/` to the `vscode-extension/` tree
    - _Requirements: 12.8_

  - [ ] 6.4 Update the tech steering file
    - In `.kiro/steering/tech.md` add `vscode-textmate` and `vscode-oniguruma` to the "Extension libraries" dev tooling list and keep the wording otherwise; this is a steering change the user may want to review
    - _Requirements: 11.2, 12.9_

  - [ ] 6.5 Update the extension design dependency table
    - In `.kiro/specs/vscode-extension/design.md` add the rows for `vscode-textmate` and `vscode-oniguruma` (dev, ranges `^9.3.2` and `^2.0.1`, MIT, role: grammar interpreter and oniguruma for tests) to the dependency table, matching the existing row format
    - _Requirements: 11.2, 12.9_

- [ ] 7. Final checkpoint - Ensure all tests pass
  - Run in `vscode-extension/`: `npm ci`, `npm run compile`, `npm run lint`, `npm run test`, `npm audit` and `npm run package`. Confirm `dist/soase-validator-0.2.0.vsix` exists, `dist/soase-validator-0.1.0.vsix` is unchanged if present, and the VSIX holds `syntaxes/soase.tmLanguage.json` exactly once (list it with `vsce ls` or by inspecting the package). Report any `npm audit` finding of high or critical severity. Confirm `git status` still shows the pre-existing `package.json` and `package-lock.json` changes and untracked `images/` as found. Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; core implementation tasks are never optional. The test helper, unit test and property tests are optional, as in the `vscode-extension` plan.
- Each task references specific requirements for traceability.
- Property tests validate the universal correctness properties of the design (fast-check, at least 100 examples, 200 here); the unit test validates specific examples and edge cases.
- All ten property tests live in one file, so they sit in separate waves of the dependency graph.
- Requirement 12.1 names `0.1.0` as the starting version; the manifest may already read a later patch version, and the bump must end at `0.2.0`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3"] },
    { "id": 3, "tasks": ["3.1", "5.1", "6.1", "6.2", "6.3", "6.4", "6.5"] },
    { "id": 4, "tasks": ["3.2", "4.1", "5.2"] },
    { "id": 5, "tasks": ["4.2"] },
    { "id": 6, "tasks": ["4.3"] },
    { "id": 7, "tasks": ["4.4"] },
    { "id": 8, "tasks": ["4.5"] },
    { "id": 9, "tasks": ["4.6"] },
    { "id": 10, "tasks": ["4.7"] },
    { "id": 11, "tasks": ["4.8"] },
    { "id": 12, "tasks": ["4.9"] },
    { "id": 13, "tasks": ["4.10"] }
  ]
}
```
