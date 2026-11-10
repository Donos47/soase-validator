# Requirements Document

## Introduction

The VS Code Extension in `vscode-extension/` registers the language identifier `soase` for nine SoaSE file types and connects them to the `soase-validator-lsp` Server for diagnostics, completion, hover help and go-to-definition. It contributes no syntax coloring, so mod files appear as plain text until the Server answers. The project README lists syntax coloring as planned.

This feature adds a static TextMate grammar (Option A) to the Extension. The Grammar colors by token shape only: a line is split into a key and a value, and the value is classified as a quoted string, a number, a hexadecimal color token, a boolean or a bracket list. The Grammar does not use the Engine, the Server or the Definitions, so it works before the Server starts, when `uv` is missing and in untrusted workspaces. It reproduces the four color categories of the original ZombiesRus5 Eclipse SoaSE plugin (key word, string value, number and boolean) and adds a fifth category for hexadecimal color tokens.

### Evidence basis

The surface syntax below is derived from these sources, in order of authority. No token shape is assumed.

1. The Rebellion 1.98 Reference Root (`~/path/to/sins-rebellion-reference`), surveyed read-only over every file type the Extension registers. Observed: every file begins with a line `TXT` or `TXT2`. Every other non-blank line begins, after optional tab or space indentation, with a letter or with `[`. Keys consist of letters, digits, `:`, `-` and `_`. Values are quoted strings (which may contain apostrophes and backslashes), unsigned and signed integers and decimals, the uppercase words `TRUE` and `FALSE`, bracket lists (comma separated or whitespace separated numbers), and runs of hexadecimal digits for colors. No line starts with a comment marker, no value is single-quoted, and no boolean is written in lowercase or mixed case. A few lines carry text after the closing quote of a string. A `key = "value"` form occurs in the constants file type.
2. The Engine parser (`src/soase_validator/engine/parser.py`) and its verified-format tests (`tests/test_parser_facts.py`): key is the text before the first tab or space; a number is tried before a hexadecimal run; a quoted string ends at the next `"`; `TRUE` and `FALSE` are accepted only in uppercase; a list is `[` numbers `]`; a row beginning with `[` is a keyless list row; the `=` form is accepted only as `key = "value"`; the parser defines no comment syntax.
3. The ZombiesRus5 plugin (compiled jar, class files only; notes in `reference/plugin-bytecode-findings.md`): the editor colors four categories, labelled in its preferences page as key word, string value, number and boolean; it defines no comment syntax.

Where the plugin and the game data differ, the game data wins (see Decisions 3 and 5). One user decision deliberately goes beyond the game data: the Grammar matches booleans case-insensitively (Decision 5). Coloring never judges validity, and the Server still reports what the Engine rejects.

### Scope

In scope: a TextMate grammar for the Language Identifier `soase`; its registration for each file extension the Extension already registers; coloring of keys, quoted strings, numbers, hexadecimal color tokens, booleans, bracket lists and the `=` form; the stance on comments; one small automated test; the minor version bump of the Extension; rebuilding the VSIX; the README updates that follow.

Out of scope: Definition-aware semantic tokens (Option B), which could color a value by the type its Definition declares and is a possible future specification; any use of the Engine, the Server or the Definitions for coloring; validation and diagnostics; registration of further file extensions (the six Engine file types deferred by the specification `vscode-extension`, and `.manifest`); language configuration for brackets, auto-closing pairs and folding; theme contributions and default color values (see Decision 8); any change to the Python package.

## Glossary

- **Extension**: The VS Code extension in `vscode-extension/`.
- **Grammar**: The TextMate grammar contributed by the Extension for the Language Identifier.
- **Language Identifier**: The VS Code language identifier `soase` contributed by the Extension.
- **SoaSE File**: A file with one of the extensions `.entity`, `.galaxy`, `.brushes`, `.sounddata`, `.str`, `.constants`, `.galaxyScenarioDef`, `.particle` or `.explosiondata`.
- **Server**: The `soase-validator-lsp` process started by the Extension.
- **Line**: One line of a SoaSE File, without its line terminator.
- **Indentation**: Zero or more tab or space characters at the start of a Line.
- **Key**: The first run of non-whitespace characters of a Line after the Indentation, when that run does not begin with `[`.
- **Value**: The text of a Line after the Key and the whitespace that follows the Key, without trailing whitespace.
- **Header Line**: The first Line of a SoaSE File, which holds only `TXT` or `TXT2`.
- **String Value**: A Value that begins with `"`.
- **Number Value**: A Value that is a whole token matching an optional sign `+` or `-`, then either digits with an optional fractional part (a decimal point followed by zero or more digits) or a decimal point followed by one or more digits, then an optional exponent (`e` or `E`, an optional sign and one or more digits).
- **Hex Value**: A Value that is a whole token of one or more characters from `0-9`, `a-f` and `A-F` and is not a Number Value.
- **Bool Value**: A Value that is a whole token equal to `true` or `false` in any capitalization (`TRUE`, `true`, `True`, `tRuE`, `FALSE`, `false` and so on).
- **List Value**: A Value, or the content of a Keyless Row, that begins with `[` and holds Number Value tokens separated by commas or by whitespace and closed by `]`.
- **Keyless Row**: A Line whose first non-whitespace character after the Indentation is `[`; the Line has no Key.
- **Equals Form**: A Line of the shape Key, whitespace, `=`, whitespace, String Value (terminated or not).
- **Scope Name**: A TextMate scope name assigned to a token by the Grammar.
- **Grammar Test**: The automated test defined in Requirement 11.
- **VSIX**: The packaged Extension file produced by `npm run package`.
- **Reference Root, Engine, Definition**: As defined in the specification `soase-validator`.

## Requirements

### Requirement 1: Grammar registration

**User Story:** As a mod developer, I want every SoaSE file type colored, so that all my mod files are readable in VS Code.

#### Acceptance Criteria

1. THE Extension SHALL contribute exactly one grammar in the `grammars` contribution of the Extension manifest, with the scope name `source.soase` and bound to the Language Identifier.
2. WHEN a SoaSE File is opened in VS Code, THE Grammar SHALL be the only TextMate grammar that colors the file.
3. THE Extension SHALL NOT bind the Grammar to any file extension other than the extensions registered under the Language Identifier.
4. THE Extension SHALL NOT register the file extension `.manifest` under the Language Identifier.
5. WHILE the Server is not running, THE Grammar SHALL color SoaSE Files.
6. WHILE the Extension has not activated, THE Grammar SHALL color SoaSE Files.
7. WHILE a workspace is untrusted, THE Grammar SHALL color SoaSE Files.
8. THE Extension SHALL keep the set of file extensions registered under the Language Identifier identical to the set registered before this feature, with no extension added or removed.

### Requirement 2: Coloring by token shape only

**User Story:** As a maintainer, I want the Grammar to stay independent of the Engine, so that coloring never disagrees with a Definition or depends on a running process.

#### Acceptance Criteria

1. THE Grammar SHALL assign every Scope Name from the characters of a single Line and the position of the token within that Line, and SHALL NOT use the content of any other Line, the file name, the file extension, any setting, or any state held outside the Grammar.
2. THE Grammar SHALL assign the same Scope Name to a Value of a given shape (String Value, Number Value, Hex Value, Bool Value or List Value) regardless of the text of the Key it follows, including a Value in a Keyless Row and a Value in the Equals Form.
3. THE Extension SHALL NOT add, for coloring, any executable code to the Extension's runtime sources, any entry under `dependencies` in `vscode-extension/package.json`, any LSP request or notification handled by the Server, or any Extension setting.
4. THE Extension SHALL NOT contribute `semanticTokenTypes`, `semanticTokenModifiers` or `semanticTokenScopes` in the Extension manifest, and SHALL NOT register a semantic tokens provider.
5. WHEN the Grammar colors a SoaSE File, THE Grammar SHALL NOT read the Engine, the Definitions, a Reference Root or any game file, and the Grammar SHALL consist of static data that holds no reference to any of them.

### Requirement 3: Keys

**User Story:** As a mod developer, I want keys colored differently from values, so that I can scan a file by its structure.

#### Acceptance Criteria

1. WHEN a Line has a Key, THE Grammar SHALL assign a key Scope Name to every character of the Key and to no character outside it.
2. THE Grammar SHALL treat as part of the Key every character after the Indentation up to, but excluding, the first tab, space or end of Line, including letters, digits, `:`, `-`, `_` and any other non-whitespace character.
3. WHEN a Line consists of a Key alone, THE Grammar SHALL assign the key Scope Name to the Key and no other Scope Name to any character of the Line.
4. THE Grammar SHALL assign a key Scope Name that is not equal to the Scope Name of any value category in Requirements 4 to 8.
5. THE Grammar SHALL accept Indentation of zero or more tabs, spaces or a mix of both, of any width, and SHALL assign no Scope Name to any Indentation character.
6. WHEN a Line is empty or contains only tabs and spaces, THE Grammar SHALL assign no Scope Name to any character of the Line.
7. WHEN a Key is followed by a tab or space and further text, THE Grammar SHALL end the key Scope Name at the last Key character and SHALL assign no key Scope Name to the separator or to the text after it.

### Requirement 4: Quoted strings

**User Story:** As a mod developer, I want quoted text colored as a string, so that names, paths and localized text stand out from numbers.

#### Acceptance Criteria

1. WHEN a Value begins with `"` and a further `"` follows on the same Line, THE Grammar SHALL assign a string Scope Name to the text from the opening `"` through the first following `"`, quotes included, and to no other text of the Line.
2. THE Grammar SHALL treat every character between the opening `"` and the first following `"`, including `'`, `\`, `=`, `[`, `]`, `,` and tab or space characters, as part of the String Value, and SHALL NOT interpret `\` as an escape character, so that `"a\"` ends at the `"` that follows the `\`.
3. WHEN a String Value is empty (`""`), THE Grammar SHALL assign the string Scope Name to both quotes.
4. IF a String Value has no closing `"` on its Line, THEN THE Grammar SHALL assign the string Scope Name from the opening `"` to the last character of the Line, and SHALL NOT assign the string Scope Name to any character of the next Line because of that opening `"`.
5. THE Grammar SHALL NOT treat `'` as a string delimiter, so that a `'` outside a String Value receives no string Scope Name.
6. THE Grammar SHALL assign the string Scope Name only to text of a String Value, and SHALL NOT assign it to an unquoted token, to a Key that contains `"`, or to a `"` that does not begin a Value.
7. WHERE a Line has non-whitespace text after the closing `"` of a String Value, THE Grammar SHALL assign the string Scope Name to the String Value and SHALL assign no value Scope Name to the text after the closing `"`, as decided in Decision 3.
8. WHEN a Line is in the Equals Form, THE Grammar SHALL treat the text after the `=` and its following whitespace as the Value and SHALL apply criteria 1 to 7 to that Value.

### Requirement 5: Numbers

**User Story:** As a mod developer, I want numeric values colored, so that counts, costs and coordinates stand out.

#### Acceptance Criteria

1. WHEN a Value is a Number Value, THE Grammar SHALL assign a number Scope Name to the whole Value, from its first character to its last character.
2. WHEN a Number Value is an integer (`193`), a signed integer (`-5`), a decimal with a fractional part (`0.000000`, `-1.500000`), a decimal with a leading decimal point (`.5`), a decimal with a trailing decimal point (`5.`) or a value with an exponent (`1e3`, `2.5E-4`), THE Grammar SHALL assign the number Scope Name to that Value.
3. WHEN a token is made only of decimal digits, including a token of eight digits such as `00000000`, THE Grammar SHALL assign the number Scope Name to that token, because such a token is a Number Value and not a Hex Value.
4. IF a token that follows a Key is not a Number Value, a Hex Value, a Bool Value, a String Value or a List Value (for example `1.2.3`, `12abc` or `0x10`), THEN THE Grammar SHALL assign no value Scope Name to any character of that token.
5. IF a Number Value is followed on the same Line by one or more non-whitespace characters, THEN THE Grammar SHALL assign no value Scope Name to any character of the Value.
6. IF a Number Value is followed on the same Line only by whitespace, THEN THE Grammar SHALL assign the number Scope Name to the Value and no Scope Name to the trailing whitespace.

### Requirement 6: Hexadecimal color tokens

**User Story:** As a mod developer, I want color codes colored apart from ordinary numbers, so that I can find colors in particle and entity files.

#### Acceptance Criteria

1. WHEN a Value is a Hex Value, THE Grammar SHALL assign a hex Scope Name to the whole Value, from its first character to its last character.
2. THE Grammar SHALL assign the hex Scope Name to a Hex Value written in lowercase (`ffffffff`), uppercase (`FFFF891D`) or mixed case (`ffFF891D`), of any length of 1 or more characters.
3. WHEN a token matches both the Number Value shape and the Hex Value shape, THE Grammar SHALL assign the number Scope Name, so that `1e5` receives the number Scope Name.
4. WHEN a token matches the Hex Value shape and does not match the Number Value shape, THE Grammar SHALL assign the hex Scope Name, so that `ab12` receives the hex Scope Name.
5. THE Grammar SHALL assign a hex Scope Name that is not equal to the number Scope Name.
6. IF a token contains a character outside `0-9`, `a-f` and `A-F` (for example `0xffffffff`, `#ffffff` or `ffg`), THEN THE Grammar SHALL assign no hex Scope Name to any part of that token.
7. THE Grammar SHALL assign the hex Scope Name to a Hex Value of any length and with any channel values, and SHALL NOT report a length or channel value as an error.

### Requirement 7: Booleans

**User Story:** As a mod developer, I want boolean words colored as booleans in any capitalization, so that flags are easy to find.

#### Acceptance Criteria

1. WHEN a Value is a whole token equal to `true` or `false` in any capitalization (`TRUE`, `true`, `True`, `tRuE`, `FALSE`, `false`, `False`), THE Grammar SHALL assign the boolean Scope Name to the whole Value (Decision 5).
2. IF a Value contains `true` or `false` in any capitalization together with any additional character (for example `TRUEX`, `falsey`, `FALSE1`, `XTRUE`), THEN THE Grammar SHALL assign the boolean Scope Name to no part of that Value.
3. THE Grammar SHALL match Bool Values by shape only and SHALL NOT judge whether the capitalization is accepted by the Engine, so that `true` receives the boolean Scope Name although the Engine accepts only uppercase `TRUE` and `FALSE`.
4. WHEN a Value is the quoted text `"TRUE"`, `"true"` or `"FALSE"`, THE Grammar SHALL treat it as a String Value, assign the string Scope Name to the whole quoted token including both quotes, and assign the boolean Scope Name to no part of it.
5. THE Grammar SHALL use a boolean Scope Name that is different from each of the key, string, number and hex Scope Names.

### Requirement 8: Lists and keyless rows

**User Story:** As a mod developer, I want coordinates and orientation rows colored, so that bracket lists are as readable as scalar values.

#### Acceptance Criteria

1. WHEN a Value or a Keyless Row is a List Value, THE Grammar SHALL assign the number Scope Name to each Number Value item and the punctuation Scope Name to `[`, `]` and each `,`.
2. WHEN a List Value separates its items with commas (`[ 234 , 219 ]`, `[9, 99, 999, 99]`) or with whitespace only (`[ 0.000000 0.100000 0.000000 ]`), THE Grammar SHALL assign the Scope Names from criterion 1 to every item and delimiter in the list.
3. WHEN a Line is a Keyless Row, THE Grammar SHALL assign no key Scope Name to any character of the Line.
4. WHEN a `]` occurs on a Line that has an open list, THE Grammar SHALL end the list at the first such `]` and SHALL assign no list Scope Name to any character on the next Line because of that list.
5. IF a Line ends before the closing `]` of an open list, THEN THE Grammar SHALL end the list at the end of that Line, SHALL keep the Scope Names already assigned to the items and delimiters on that Line, and SHALL NOT continue the list on the next Line.
6. IF an item inside brackets is not a Number Value (for example `x` in `[ 1 , x ]`), THEN THE Grammar SHALL assign the number Scope Name to each Number Value item, the punctuation Scope Name to `[`, `]` and each `,`, and no Scope Name to the non-number item.
7. WHERE a Line has text after the first `]` of a List Value or Keyless Row, THE Grammar SHALL assign no Scope Name to any character of that text, as decided in Decision 10.

### Requirement 9: The equals form

**User Story:** As a mod developer editing constants, I want `key = "value"` lines colored like other lines, so that the file reads consistently.

#### Acceptance Criteria

1. WHEN a Line is an Equals Form (a Key, one or more tab or space characters, `=`, one or more tab or space characters, then a String Value, terminated or not), THE Grammar SHALL assign the key Scope Name to the Key, an operator Scope Name to the `=` character, and the string Scope Name to the String Value as defined in Requirement 4, so that for `k = "v` the string Scope Name covers the text from the opening `"` to the end of the Line (Decision 9).
2. THE Grammar SHALL assign the operator Scope Name only to an `=` that is a whole whitespace-delimited token of an Equals Form, and SHALL assign a Scope Name to that operator that differs from the key Scope Name and from the Scope Name of every value category in Requirements 4 to 8.
3. IF a Line has `=` attached to the Key with no whitespace between them (`key= "v"`, `a=b "v"`), THEN THE Grammar SHALL include the `=` in the Key, assign the key Scope Name to the whole Key including the `=`, assign no operator Scope Name to any character of the Line, and assign the string Scope Name to the following String Value.
4. IF a Line has a standalone `=` token after the Key and the text after that `=` is not whitespace followed by a String Value (`k = 5`, `k ="v"`, `k =`), THEN THE Grammar SHALL assign the key Scope Name to the Key, assign no operator Scope Name to the `=`, and assign no value Scope Name to the Value that begins with `=`.
5. WHEN a Line is an Equals Form with Indentation of any width of tabs, spaces or a mix, THE Grammar SHALL assign no Scope Name to the Indentation or to the whitespace around the `=`.

### Requirement 10: Comments and the header

**User Story:** As a mod developer, I want the Grammar to match how the game reads files, so that coloring does not suggest syntax the game does not have.

#### Acceptance Criteria

1. THE Grammar SHALL NOT define any rule that assigns a comment Scope Name to any text in a SoaSE File, because neither the game data, the Engine parser nor the plugin defines a comment syntax (Decision 1).
2. WHEN a Line has `//`, `#` or `;` as its first non-whitespace characters, THE Grammar SHALL color that Line by the same rules as any other Line, so that its first run of non-whitespace characters, including the leading `//`, `#` or `;`, is a Key and the remaining text is colored as the Value rules dictate.
3. WHEN the first Line of a SoaSE File holds only `TXT` or `TXT2`, THE Grammar SHALL give that Line the key Scope Name, as decided in Decision 2.
4. WHEN a Line other than the first Line holds only `TXT` or `TXT2`, THE Grammar SHALL color that Line like any other Line, as a Key alone.

### Requirement 11: Automated test

**User Story:** As a maintainer, I want one small test, so that a change to the Grammar that breaks a token kind is caught.

#### Acceptance Criteria

1. THE Grammar Test SHALL verify that the `grammars` contribution in the Extension manifest has the Language Identifier `soase`, the scope name `source.soase`, and a path that resolves, relative to `vscode-extension/`, to an existing file.
2. THE Grammar Test SHALL tokenize each synthetic snippet with the Grammar and SHALL verify, for the Key and for the Value, that the Scope Name equals the Scope Name required by Requirements 3 to 9 (or that no Scope Name is assigned where those requirements say so), for each of: a quoted string, an empty string, a string containing `'` and `\`, an unterminated string, an integer, a signed decimal, a lowercase Hex Value, an uppercase Hex Value, a digits-only token, `TRUE`, `FALSE`, a lowercase boolean (`true`), a mixed-case boolean (`True`), a comma separated list, a whitespace separated list, a Keyless Row, an Equals Form and an unterminated Equals Form (`k = "v`), for which the `=` receives the operator Scope Name and the text from the opening `"` to the end of the Line receives the string Scope Name.
3. THE Grammar Test SHALL verify that each of the following rejected shapes receives no value Scope Name, with at least one shape for each of Requirements 4 to 9: `'text'` (Requirement 4), `1.2.3` (Requirement 5), `0x10` and `ffg` (Requirement 6), `TRUEX` and `truex` (Requirement 7), `[ 1 , x ]` with the non-numeric item `x` receiving no Scope Name (Requirement 8), and `key= "v"` with the `=` included in the Key and no operator Scope Name (Requirement 9).
4. THE Grammar Test SHALL verify that a Line beginning with `//` receives the key Scope Name on its first run of non-whitespace characters and the Scope Name required by Requirements 4 to 8 on its Value, as stated in Requirement 10.2.
5. THE Grammar Test SHALL build every snippet from synthetic text defined in the test source, SHALL NOT read a Reference Root or any game file, and SHALL NOT contain game file content.
6. WHEN `npm run test` runs in `vscode-extension/`, THE Grammar Test SHALL run and pass with exit code 0, without starting the Server, without importing the `vscode` module and without network access.
7. THE Grammar Test SHALL be a unit test under `vscode-extension/test/unit/` that `mocha` runs after `tsc` compiles it, following the Extension test layout.
8. IF a Grammar Test assertion fails, THEN THE Grammar Test SHALL fail the `npm run test` run with a non-zero exit code and SHALL report the snippet text, the expected Scope Name and the actual Scope Name.

### Requirement 12: Version, packaging and documentation

**User Story:** As a maintainer, I want the change released under a new Extension version, so that the installed Extension can be told apart from the one that has no coloring.

#### Acceptance Criteria

1. WHEN the Grammar is added, THE Extension SHALL increase `version` in `vscode-extension/package.json` from `0.1.0` to `0.2.0` and SHALL make the matching change to the `version` entries for the root package in `vscode-extension/package-lock.json`, because a contribution is added to the manifest while the major version is 0.
2. WHEN `npm run package` runs after the version is increased, THE `npm run package` command SHALL produce `dist/soase-validator-0.2.0.vsix` and SHALL leave the bytes of the existing `dist/soase-validator-0.1.0.vsix` unchanged.
3. WHEN `npm run package` produces the VSIX, THE VSIX SHALL contain exactly one grammar file, at the path named by the `grammars` contribution in `package.json`.
4. WHEN `npm run package` runs, THE contents check SHALL accept the grammar file and SHALL keep rejecting every other first-party data file (Decision 6), exiting with a non-zero code and naming the rejected file when one is present.
5. WHEN `npm run compile`, `npm run lint`, `npm run test` and `npm run package` each run in `vscode-extension/`, THE commands SHALL each finish with exit code 0.
6. THE project `README.md` SHALL list syntax coloring as available and SHALL NOT list syntax coloring among the planned items.
7. THE Extension `README.md` SHALL list each coloring category, SHALL state that coloring follows token shape only, SHALL state that Definition-aware coloring is not provided, and SHALL state that coloring works without the Server.
8. THE `.kiro/steering/structure.md` file SHALL list the grammar directory in the `vscode-extension/` tree.
9. THE Grammar, the Grammar Test, the manifest and the documentation SHALL contain no survey counts, no Reference Root file names and no machine-specific absolute paths; examples SHALL use placeholders such as `~/path/to/sins-rebellion-reference`.


## Decisions

Each decision records a question raised while drafting, the answer given by the user, and the criteria it affects. No question remains open.

1. **Comments.** Question: should the Grammar define a comment rule? Answer: no. The game does not support comments, and neither the game data, the Engine parser nor the plugin defines a comment syntax. A Line starting with `//`, `#` or `;` is colored like any other Line. Affects: Requirement 10.1, 10.2, 11.4.
2. **Header Line.** Question: should the header get its own Scope Name? Answer: no. The Header Line is colored as a key. Affects: Requirement 10.3, 10.4.
3. **Text after a closing quote.** Question: how should text after the closing quote of a String Value be colored? Answer: left uncolored, because static coloring never judges validity. Affects: Requirement 4.7.
4. **Hex as its own category.** Question: should hexadecimal color tokens form a fifth category? Answer: yes. A digits-only token is a Number Value by shape; only tokens that are not Number Values are Hex Values. Affects: Requirement 5.3, Requirement 6.
5. **Plugin behaviours and boolean case.** Question: which plugin behaviours should the Grammar copy? Answer: none of single-quoted strings, the prefix match of `TRUE` and `FALSE`, or blanking of every `=`; the Grammar follows the game data and the Engine parser for strings (double quotes only) and for the narrow `=` form. Exception, an explicit user decision: boolean tokens are matched case-insensitively, so every capitalization of `true` and `false` (`TRUE`, `true`, `True`, `tRuE`, and so on) receives the boolean Scope Name, as a whole-token match only. The game data and the Engine parser use only uppercase `TRUE` and `FALSE`, so the Grammar deliberately colors more shapes than the Engine accepts. Coloring never judges validity, and the Server still reports what the Engine rejects. Affects: Requirement 4.5, Requirement 7, Requirement 9.2, Requirement 11.2, 11.3.
6. **JSON in the VSIX.** Question: how should the grammar file pass the VSIX contents check? Answer: add one explicit allow-list entry for the grammar path in `scripts/check-vsix-contents.mjs`; every other first-party data file stays rejected. Affects: Requirement 12.3, 12.4.
7. **Test tooling.** Question: may the Grammar Test use a TextMate engine? Answer: yes. `vscode-textmate` and `vscode-oniguruma` are added as development dependencies, with version ranges recorded in the design. Affects: Requirement 11.2, 11.6.
8. **Theme colors.** Question: should the Extension contribute default token colors? Answer: no. Colors are left to the active theme and the Extension contributes no `configurationDefaults` token color customizations. The exact Scope Names are chosen in the design. Affects: Requirement 3.4, 7.5, 2.3.
9. **Unterminated string after `=`.** Question: is `k = "v` an Equals Form? Answer: yes, following the Engine. The parser accepts `=` followed by whitespace and a `"`, and yields an unterminated String Value; `k = "oops` parses with the unterminated string and only the unterminated-string diagnostic. The Grammar assigns the key Scope Name to the Key, the operator Scope Name to `=` and the string Scope Name from the opening `"` to the end of the Line. `k = 5`, `k ="v"` and `k =` stay without an operator. Affects: Requirement 4.8, 9.1, 9.4, 11.2.
10. **Text after a closing bracket.** Question: how should text after the first `]` be colored? Answer: left uncolored, in line with Decision 3. Hex-only items inside brackets stay uncolored because a List Value holds Number Value items only, as the Engine list rule does; character classes stay ASCII-only. Affects: Requirement 8.7.
