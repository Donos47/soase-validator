# Implementation Plan: vscode-extension

## Overview

The extension is a thin TypeScript wrapper around `soase-validator-lsp`, built bottom-up in `vscode-extension/`. The plan first updates the steering rules so they allow the extension's Node and TypeScript tooling, then scaffolds the toolchain, builds the pure core modules (no `vscode` import) with their property tests, then the controller, then the VS Code adapters, then wires `extension.ts`, the manifest contributions, the stub server and host tests, packaging, and repository integration.

Conventions for every task:

- Language is TypeScript on Node 24. Style: 2-space indent, single quotes, semicolons, trailing commas, kebab-case file names, JSDoc on every exported symbol.
- Comments say why, never what. No change history, task numbers, chat history or survey counts in code or comments.
- No machine-specific absolute paths in source, tests, fixtures, manifest or docs. Use placeholders such as `~/path/to/sins-rebellion-reference`.
- Check current dependency versions on npm before adding a dependency, use the ranges in the design, and run `npm audit` after adding or updating dependencies. Report high and critical findings.
- The extension contains no validation, completion, hover or reference logic. All of that stays in the Python Engine.
- Task statuses in this file are changed only by the orchestrator.

## Tasks

- [ ] 1. Update the steering rules and repository ignore files
  - [ ] 1.1 Update the steering rules for the extension tooling
    - Update `.kiro/steering/structure.md` to describe the `vscode-extension/` tree (sources, tests, scripts, `out/` and `dist/` build output) and its tooling: Node 24, npm, TypeScript, mocha and fast-check
    - Update `.kiro/steering/tech.md` to state that Node.js 24 and npm are used for the VS Code extension in `vscode-extension/` only, and that the Engine, LSP server, MCP server and CLI stay Python; record the extension's TypeScript style (2-space indent, single quotes, semicolons, trailing commas, kebab-case file names) and the Node 24 decision
    - Reconcile every existing Python-only statement so that none contradicts the extension: scope the "Language and tooling" section (Python 3.14+, `uv`, `src/` layout, no global installs) and the "Code style (Python)", "Comments and docstrings" and "Testing" sections explicitly to the `soase_validator` package, `tests/` and `tools/`, and add the extension's own build, lint and test commands (`npm run compile`, `npm run lint`, `npm run test`) next to the Python commands; keep the "Run `ruff check`, `ruff format --check` and `pytest` before finishing a task" rule for Python work and add the npm equivalent for extension work
    - In `structure.md`, keep the rule that the Engine imports nothing from front ends and state that `vscode-extension/` neither imports from nor ships with the Python package
    - Check the other steering files in `.kiro/steering/` for Python-only or "no Node" wording that would conflict, and reconcile it the same way
    - _Requirements: 16.3, 16.4_

  - [ ] 1.2 Update ignore files and Python tool exclusions
    - Add `node_modules/`, `vscode-extension/out/`, `vscode-extension/dist/`, `vscode-extension/.vscode-test/` and `*.vsix` to the repository `.gitignore`
    - Add `vscode-extension` to `[tool.ruff] extend-exclude` in `pyproject.toml` and confirm `uv run ruff check`, `uv run ruff format --check` and `uv run pytest` are unaffected; the Python package neither imports nor ships anything from `vscode-extension/`
    - _Requirements: 16.2, 16.5, 16.6_

- [ ] 2. Scaffold the extension project
  - [ ] 2.1 Create the npm project and base configuration
    - Create `vscode-extension/package.json` with name, version, `engines` (`vscode` `^1.141.0`, `node` `>=24`), `main` `./out/extension.js`, MIT license, and the scripts `compile`, `lint`, `test:unit`, `test:host`, `test`, `audit` and `package` from the design
    - Add dev dependencies with the ranges in the design (`typescript` `~6.0.3`, `@types/vscode` `~1.140.0`, `@types/node` `^24.19.2`, `eslint`, `typescript-eslint`, `eslint-plugin-n`, `mocha`, `@types/mocha`, `fast-check`, `@vscode/vsce`, `@vscode/test-electron`, `vscode-languageserver`) and the runtime dependency `vscode-languageclient` `^11.0.0`. Re-check each version on npm first and record any deviation from the design table
    - Create `tsconfig.json` (`module` and `moduleResolution` `node16`, `target` `ES2022`, `strict`, `noUncheckedIndexedAccess`, `outDir` `out`, `rootDir` `.`, source maps, `lib` `ES2022`), `.node-version` containing `24`, `.mocharc.json` (specs under `out/test/unit` and `out/test/properties`), and `.vscodeignore` as listed in the design
    - Run `npm install` to create `package-lock.json`, then `npm audit`, and report findings of high or critical severity
    - _Requirements: 13.4, 13.7, 13.10, 13.11, 13.12, 16.1_

  - [ ] 2.2 Configure ESLint and the embedded-Node guard
    - Create `eslint.config.mjs` (flat config, `typescript-eslint` recommended type-checked rules) covering `src`, `test` and `scripts`
    - In `src/`: forbid `no-console`, `process.stdout` and `process.stderr` writes, network modules (`http`, `https`, `net`, `tls`, `dgram` and their `node:` forms), every `node:` module except `child_process`, `fs`, `path`, `os` and `process`, `child_process` outside `src/client/spawn-server.ts` and the injected exec adapter, and the `vscode` module inside `src/launcher`, `src/settings` (except `vscode-config-reader.ts`), `src/lifecycle` and `src/format`
    - Enable `eslint-plugin-n` rules `n/no-unsupported-features/node-builtins`, `es-builtins` and `es-syntax` for `src/` using the version constant from `scripts/min-embedded-node.mjs` (`MIN_EMBEDDED_NODE = '24.21.0'`, expressed as `>=24.21.0`)
    - Verify the config loads with a lint run, and leave no temporary files behind
    - _Requirements: 10.1, 10.2, 10.3, 15.10, 15.11, 16.1_

- [ ] 3. Implement the pure core modules
  - [ ] 3.1 Implement path expansion and the `uvx` resolver
    - Create `src/launcher/expand-path.ts`: expand a leading `~` and environment variable references (`%VAR%` on Windows, `$VAR` and `${VAR}` elsewhere); a string with neither is returned unchanged
    - Create `src/launcher/resolve-uvx.ts` with `Platform`, `ResolverPorts`, `UvxResolution` and `resolveUvx` exactly as in the design: `uvPath` only when non-blank (no fallback on failure), else `PATH` entries in order, then the installer bin directory, then `$CARGO_HOME/bin` (default `<home>/.cargo/bin`); executable name `uvx.exe` on `win32`, otherwise `uvx`; `searched` lists probed candidates in probe order
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.7, 4.2_

  - [ ] 3.3 Implement the Server Command builder
    - Create `src/launcher/server-command.ts` with `DEFAULT_SERVER_SOURCE`, `ServerCommand` and `buildServerCommand`: arguments `['--from', source, 'soase-validator-lsp']`, source is the trimmed `serverSource` when non-blank and the default otherwise and is passed unchanged, `cwd` is the first workspace folder or the home directory
    - _Requirements: 5.2, 5.3, 5.4, 5.12_

  - [ ] 3.5 Implement the `uvx` version probe
    - Create `src/launcher/uv-version.ts` with `probeUvVersion(uvxPath, exec, timeoutMs = 10_000)` over an injected `exec` port; return `{ available: true, text }` or `{ available: false, reason }` for spawn failure, non-zero exit or timeout; run `uvx --version`
    - _Requirements: 3.6, 3.8_

  - [ ] 3.6 Implement the Server Settings schema and payload builder
    - Create `src/settings/server-settings-schema.ts` with `SettingType`, `ServerSettingDef` and the `SERVER_SETTINGS` list of Requirement 6.2 (types as in the design)
    - Create `src/settings/payload.ts` with `ScopedValue`, `ConfigReader`, `PayloadResult` and `buildPayload`: most specific scope wins without merging, unset keys omitted, empty values count as set, shallow type check only (never judges meaning), wrong-typed keys omitted and listed in `invalid`, dotted keys nested, strings copied character for character
    - _Requirements: 6.1, 6.2, 6.3, 6.5, 6.6, 6.8, 11.5_

  - [ ] 3.8 Implement Extension setting normalisers
    - Create `src/settings/extension-settings.ts` with `normaliseTimeout` (finite number of at least 10 as is; below 10 gives 10 with a warning; anything else gives 180 with a warning), `normaliseTrace` (default `off`) and `readString` (non-strings give an empty string)
    - _Requirements: 5.8, 8.9, 11.8_

  - [ ] 3.10 Implement the restart policy and lifecycle reducer
    - Create `src/lifecycle/restart-policy.ts` with `RestartPolicy`, `DEFAULT_RESTART_POLICY` (3 restarts per 300000 ms) and `decideRestart` returning `restart` and the pruned exit list
    - Create `src/lifecycle/lifecycle.ts` with `ServerState`, `Lifecycle`, `LifecycleEvent`, `LifecycleEffect` and the pure `step` reducer: auto-start only in `stopped` with `userStopped` false and a trusted workspace, no auto-start from `error`, `Spawn` only when not `live`, `Kill` on every transition into `error` or `stopped` while `live`, unexpected exit after `running` consults the policy, exits before `running` go to `error` without restart, requested exits never count toward the crash window, `RestartRequested` clears `userStopped` and the crash history, at most one error `Notify` per failure event
    - _Requirements: 2.3, 2.4, 2.6, 2.7, 2.9, 5.9, 5.13, 7.4, 7.9, 7.10, 11.2, 11.3, 11.4_

  - [ ] 3.13 Implement the formatters
    - Create `src/format/log-line.ts` (`<ISO-8601 timestamp> [<level>] <message>`, levels `error`, `warn`, `info`, `debug`), `src/format/line-splitter.ts` (chunk to lines across arbitrary and multi-byte boundaries, plus a tail buffer holding the last 20 lines) and `src/format/status-text.ts` (`StatusSnapshot`, `formatStatus`, status item labels, `extractServerVersion`)
    - `formatStatus` renders `not available` for missing `uvxPath` and `command`; the Server version renders as given, `unknown` when running without `serverInfo.version`, and `not available` when the Server is not running
    - _Requirements: 5.5, 5.9, 7.6, 7.7, 8.2, 8.8, 12.3, 12.4_

  - [ ]* 3.2 Write tests for the resolver and path expansion
    - **Property 2: Uvx resolution order**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.7, 4.2, 15.2**
    - File `test/properties/p02-uvx-resolution-order.test.ts`, first line `// Feature: vscode-extension, Property 2: Uvx resolution order`, `numRuns` of at least 200
    - Add unit tests in `test/unit/resolve-uvx.test.ts` with an in-memory file system: for `win32`, `darwin` and `linux` one found and one not-found case each, the search order `PATH`, installer bin, `CARGO_HOME` with and without the variable, an invalid `uvPath` with no fallback
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.7, 15.2_

  - [ ]* 3.4 Write property test for the launch plan
    - **Property 3: Launch plan**
    - **Validates: Requirements 5.2, 5.3, 5.4, 5.12**
    - File `test/properties/p03-launch-plan.test.ts`, at least 100 runs
    - _Requirements: 5.2, 5.3, 5.4, 5.12_

  - [ ]* 3.7 Write tests for the payload builder
    - **Property 1: Payload exactness**
    - **Validates: Requirements 6.3, 6.5, 6.6, 6.8, 11.5, 15.4**
    - File `test/properties/p01-payload-exactness.test.ts` with arbitraries in `test/properties/arbitraries/`, `numRuns` of at least 200, values including empty lists, empty objects, empty strings, `~`, `%VAR%`, `$VAR`, backslashes and non-ASCII text
    - Add unit tests in `test/unit/payload.test.ts` for unset omission, wrong-type omission, the single `soase-validator` section and dotted-key nesting
    - _Requirements: 6.3, 6.5, 6.6, 6.8, 11.5, 15.3, 15.4_

  - [ ]* 3.9 Write property test for timeout normalisation
    - **Property 6: Timeout normalisation**
    - **Validates: Requirements 5.8, 11.8**
    - File `test/properties/p06-timeout-normalisation.test.ts`, covering `NaN`, infinities, negatives, strings and `undefined`
    - _Requirements: 5.8, 11.8_

  - [ ]* 3.11 Write property test for the crash-loop policy
    - **Property 4: Crash-loop policy**
    - **Validates: Requirements 11.3, 11.4**
    - File `test/properties/p04-crash-loop-policy.test.ts`, at least 100 runs, including exits spaced at least one window apart
    - _Requirements: 11.3, 11.4_

  - [ ]* 3.12 Write property test for lifecycle invariants
    - **Property 5: Lifecycle invariants**
    - **Validates: Requirements 2.3, 2.4, 2.6, 2.7, 2.9, 5.13, 7.4, 7.9, 7.10, 11.2**
    - File `test/properties/p05-lifecycle-invariants.test.ts`, event sequences with random trust values, `numRuns` of at least 200
    - _Requirements: 2.3, 2.4, 2.6, 2.7, 2.9, 5.13, 7.4, 7.9, 7.10, 11.2_

  - [ ]* 3.14 Write property tests for formatters
    - **Property 7: Stderr line handling**
    - **Validates: Requirements 5.5, 5.9**
    - **Property 9: Status text and server version**
    - **Validates: Requirements 7.6, 7.7, 12.3, 12.4**
    - **Property 10: Log line format**
    - **Validates: Requirements 8.8**
    - One file each: `p07-stderr-line-handling.test.ts`, `p09-status-text.test.ts`, `p10-log-line-format.test.ts` under `test/properties/`, at least 100 runs each
    - _Requirements: 5.5, 5.9, 7.6, 7.7, 8.8, 12.3, 12.4_

- [ ] 4. Checkpoint - Core modules
  - Run `npm run compile`, `npm run lint` and `npm run test:unit` in `vscode-extension/`. Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Implement the server controller
  - [ ] 5.1 Implement the controller interpreter
    - Create `src/lifecycle/server-controller.ts` with `ControllerPorts`, `UiPort` and the controller: feed events through `step`, run effects through ports, tag processes, timers and clients with `generation` and drop late events from old generations
    - Start sequence: resolve `uvx`; on failure log each searched location, set `error`, show one notification with "Open install instructions" and "Set uvPath", do not spawn; on success log the path, run the version probe in the background without delaying the start, build the command, arm the startup timer, call `startClient`, set `running` after `initialize`
    - Timeout, spawn failure, early exit and unexpected exit paths log and notify as in the design (stderr tail of 20 lines in the log, first 20 lines in the notification, "Show output" and "Restart server" actions); restart and stop use graceful stop with a 5 second forced kill and log the forced termination
    - Expose `dispatch`, a status snapshot (state, `uvxPath`, command, server version) and `dispose` that stops the process within 5 seconds
    - _Requirements: 2.4, 2.9, 3.6, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 5.7, 5.8, 5.9, 5.10, 5.11, 5.13, 7.2, 7.3, 7.4, 7.8, 7.9, 7.10, 10.6, 11.1, 11.2, 11.3, 11.4, 11.7, 12.2, 12.5_

  - [ ]* 5.2 Write unit tests for the controller with fake ports
    - File `test/unit/server-controller.test.ts` with a fake clock, fake timers, fake `startClient` and fake UI
    - Missing `uv` shows exactly one notification with exactly two actions, sets `error`, never calls `startClient`, writes each searched location, shows nothing more after dismissal, and calls the install-docs and settings ports from the two actions
    - Cover timeout, spawn failure, exit before `initialize` (no retry, 20-line notification), three automatic restarts then stop on the fourth, manual restart clearing the crash window, forced kill after 5 seconds, late events from an old generation ignored, `stopServer` blocking auto-start until `restartServer`, and the restart order (stop, re-resolve, start, settings re-sent)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.8, 5.9, 5.10, 7.2, 7.3, 7.9, 7.10, 10.6, 11.1, 11.2, 11.3, 11.4, 12.2, 15.6_

- [ ] 6. Implement the VS Code adapters
  - [ ] 6.1 Implement the configuration reader
    - Create `src/settings/vscode-config-reader.ts`: a `ConfigReader` over `workspace.getConfiguration('soase-validator').inspect(key)` that passes only `globalValue`, `workspaceValue` and `workspaceFolderValue` and ignores `defaultValue`; plus readers for `uvPath`, `serverSource`, `startupTimeoutSeconds` and `trace.server` that use the normalisers
    - This is the only file in `src/settings` that imports `vscode`
    - _Requirements: 6.5, 6.6, 6.11, 11.8_

  - [ ] 6.2 Implement the output channel, status item and notifications
    - Create `src/ui/output-log.ts`: exactly one `SoaSE Validator` channel, Extension lines through `formatLogLine`, a de-duplicating warning helper keyed by setting key plus serialized value, `console.error` only if the channel is disposed
    - Create `src/ui/status-item.ts`: one left-aligned status bar item with command `soase-validator.showStatus`, labels per state, error background, visible only while the active editor's language is `soase`, shown as `stopped` until the first start, updated synchronously on state change
    - Create `src/ui/notifications.ts`: the error notifications and actions of the design; "Open install instructions" opens the `uv` installation documentation with `env.openExternal`, "Set uvPath" runs `workbench.action.openSettings` filtered to `soase-validator.uvPath`; the Extension never downloads or runs an installer
    - _Requirements: 4.1, 4.4, 4.5, 4.7, 5.9, 5.10, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 11.5, 15.11_

  - [ ] 6.3 Implement the server process spawner
    - Create `src/client/spawn-server.ts`, the only module importing `child_process` for the Server: spawn with `shell: false`, an argument array and piped stdio (`detached: true` on POSIX), expose `child`, `exited` and `kill()` (process tree via `taskkill /PID <pid> /T /F` on Windows, group signal on POSIX), attach the stderr listener that feeds the line splitter and the output channel, write nothing to stdin
    - _Requirements: 5.1, 5.4, 5.5, 5.6, 7.3, 10.5_

  - [ ] 6.4 Implement trace mapping and the language client factory
    - Create `src/client/trace.ts` mapping the setting to the library `Trace` values
    - Create `src/client/client-factory.ts`, the only module importing `vscode-languageclient/node` (loaded with dynamic `import()` on first start): `documentSelector` `[{ scheme: 'file', language: 'soase' }]`, the shared output channel for stderr and trace, `initializationOptions` as a function returning the current payload, an `errorHandler` that never restarts, `serverOptions` returning the spawned child, no `synchronize.configurationSection`, no middleware; apply the trace on start and expose `sendConfiguration`, `stop` and the `serverInfo.version` from the `initialize` result
    - _Requirements: 1.3, 1.4, 1.6, 5.1, 5.7, 6.3, 8.9, 8.10, 8.11, 8.12, 8.13, 8.14, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 12.3, 12.4_

  - [ ] 6.5 Implement configuration change synchronisation
    - Create `src/client/config-sync.ts` with `ConfigSync` (250 ms quiet timer, 500 ms maximum wait, payload rebuilt at send time, one `workspace/didChangeConfiguration` with `{ settings: payload }`, nothing sent while no Server runs, no restart)
    - Only changes affecting a key in `SERVER_SETTINGS` call `notifyChange`; `uvPath`, `serverSource`, `startupTimeoutSeconds` and `trace.server` do not; no watcher on `soase.json` or the user-level file
    - _Requirements: 6.3, 6.4, 6.9_

  - [ ]* 6.6 Write property test for configuration change debouncing
    - **Property 8: Configuration change debouncing**
    - **Validates: Requirements 6.4**
    - File `test/properties/p08-config-debounce.test.ts`, fake clock and timers, at least 100 runs
    - _Requirements: 6.4_

- [ ] 7. Wire the extension entry point
  - [ ] 7.1 Implement activation, commands and `extension.ts`
    - Create `src/activation.ts`: seed trust from `workspace.isTrusted`, dispatch `AutoStart` without awaiting, handle `onDidGrantWorkspaceTrust` (`TrustChanged` then `AutoStart`) and `onDidOpenTextDocument` for `soase` `file` documents, send `ConfigSync.notifyChange` from `onDidChangeConfiguration`, apply trace changes without restart
    - Create `src/commands.ts` registering `soase-validator.restartServer`, `soase-validator.stopServer`, `soase-validator.showOutput` and `soase-validator.showStatus` (`formatStatus` in an information message)
    - Create `src/extension.ts` with `activate` and `deactivate`: whole of `activate` in a try/catch that logs, shows one error notification and returns normally; completes without waiting for the Server; returns an `ExtensionApi` with a spawn override only when `context.extensionMode === vscode.ExtensionMode.Test`; `deactivate` stops the Server within 5 seconds and disposes the channel and status item
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 2.7, 2.8, 7.1, 7.2, 7.5, 7.6, 7.8, 7.9, 7.10, 7.11, 11.6, 11.7, 15.11_

- [ ] 8. Contribute the extension manifest
  - [ ] 8.1 Complete `package.json` contributions
    - Add `displayName`, a placeholder `publisher`, `activationEvents` (`onLanguage:soase`, `workspaceContains:**/soase.json`, `workspaceContains:**/*.{entity,galaxy,brushes,sounddata,str,constants,galaxyScenarioDef,particle,explosiondata}`) and `capabilities.untrustedWorkspaces` with `supported` `limited` and `restrictedConfigurations` listing `soase-validator.uvPath` and `soase-validator.serverSource`
    - Contribute the language `soase` with exactly the nine extensions `.entity`, `.galaxy`, `.brushes`, `.sounddata`, `.str`, `.constants`, `.galaxyScenarioDef`, `.particle`, `.explosiondata` and no `.manifest`
    - Contribute one setting per `SERVER_SETTINGS` key with `scope` `window`, the declared JSON type, no `default`, no `enum`, and a description that ends with the precedence sentence and names accepted values using placeholder paths only; contribute `uvPath`, `serverSource`, `startupTimeoutSeconds` (default 180, minimum 10) and `trace.server` (`off`, `messages`, `verbose`, default `off`)
    - Contribute the four commands with the exact titles of Requirement 7 and no `commandPalette` hiding
    - _Requirements: 1.1, 1.2, 1.6, 2.1, 2.2, 2.5, 6.1, 6.2, 6.7, 6.10, 6.11, 7.1, 7.5, 7.8, 7.11, 8.9, 13.7, 13.8_

  - [ ]* 8.2 Write the manifest consistency test
    - **Property 11: Manifest consistency**
    - **Validates: Requirements 1.1, 1.6, 2.1, 2.2, 2.5, 6.1, 6.2, 6.7, 6.10, 6.11, 7.1, 7.5, 7.8, 7.11, 8.9, 13.7, 15.7**
    - File `test/unit/manifest.test.ts` (one example-based test of the manifest, tagged `// Feature: vscode-extension, Property 11: Manifest consistency`): language extensions equal the nine and exclude `.manifest`, contributed setting ids equal `SERVER_SETTINGS` plus the four Extension settings with none missing or extra, every Server Setting carries the precedence sentence and no default, command ids and titles, `engines.vscode`, `untrustedWorkspaces`, activation events, and no drive-letter or home-directory path in any default, description or example
    - _Requirements: 1.1, 1.6, 6.1, 6.2, 6.7, 6.10, 6.11, 7.1, 13.7, 15.7_

- [ ] 9. Implement the stub server and host tests
  - [ ] 9.1 Implement the stub LSP server
    - Create `test/stub/stub-lsp-server.ts` on `vscode-languageserver` 11, speaking LSP over stdio and driven by flags: `--log <file>` records every received message as JSON lines, `--no-server-info`, `--capabilities`, `--fail-requests`, `--initialize-delay <ms>`, exit-on-command with a chosen code, a stderr line at start
    - Behaviour: `serverInfo` `{ name: 'soase-validator', version: '0.0.0-stub' }`, publish a fixed Diagnostic on `didOpen` and an empty list on `didClose`, dynamically register and unregister `workspace/didChangeWatchedFiles`, return a quick fix for a `SOASE-M010` Diagnostic, write only protocol frames to stdout
    - _Requirements: 9.1, 9.2, 9.3, 9.5, 9.6, 9.7, 9.8, 15.5_

  - [ ] 9.2 Implement the host test runner
    - Create `test/host/run-tests.ts` using `@vscode/test-electron` to run the host mocha suite on VS Code `1.141.0` and on `stable`, with a clean profile; log `process.versions.node` from inside the host and compare it with the value expected for the pinned VS Code
    - Add synthetic fixtures under `test/fixtures/` (a synthetic mod folder with a SoaSE File, a `.manifest` file and a `.txt` file) containing no game content
    - _Requirements: 13.6, 15.1, 15.5_

  - [ ]* 9.3 Write host tests for launch, settings and lifecycle
    - File `test/host/lifecycle.test.ts` against the stub through the test-mode spawn override
    - Verify in order the `initialize` request, the `initializationOptions` payload, one `didChangeConfiguration` within 1000 ms of a setting change carrying the full payload, and the restart sequence (first stub receives `shutdown` and `exit` and ends, a second stub process receives a new `initialize`)
    - Verify activation returns within 500 ms while `initialize` is delayed, the startup timeout error path, the crash-loop stop after the fourth exit, `stopServer` then no auto-start, `restartServer` resuming, no notification when `soase.json` changes, status item labels and visibility, `showStatus` text with and without `serverInfo.version`
    - _Requirements: 2.8, 5.7, 5.8, 5.9, 6.3, 6.4, 6.9, 7.2, 7.6, 7.7, 7.8, 7.9, 7.10, 8.3, 8.5, 8.6, 11.1, 11.3, 11.4, 12.3, 12.4, 15.5_

  - [ ]* 9.4 Write host tests for language features and tracing
    - File `test/host/features.test.ts`: language mode `soase` for each of the nine extensions (including `.galaxyScenarioDef`); document sync for a SoaSE File and silence for `.manifest` and `.txt` files; advertised capability subset registers only the advertised features; Diagnostics shown, cleared and unchanged in code, severity, message and range; watcher registration, event delivery and unregistration; the quick fix title from the stub; a failing completion request leaves Diagnostics unchanged and returns no substitute result; no document text in the output channel at trace `off` and `messages`; zero bytes written to the Server's stdin other than LSP messages
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 8.10, 8.11, 8.13, 8.14, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 10.5_

  - [ ]* 9.5 Write the real Server integration test
    - File `test/host/integration.test.ts`: when the repository root (parent of `vscode-extension/`) or `SOASE_VALIDATOR_CHECKOUT` holds a `pyproject.toml`, start the real Server through the Launcher with `serverSource` set to that checkout and require at least one Diagnostic for a synthetic mod file within 30 seconds; record the real `serverInfo.version`
    - When no checkout is found, call `this.skip()` with a message stating that the soase-validator checkout is missing, never fail
    - _Requirements: 12.3, 15.8, 15.9_

- [ ] 10. Checkpoint - Extension complete
  - Run `npm run compile`, `npm run lint`, `npm run test:unit` and `npm run test:host` in `vscode-extension/`. Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Implement packaging
  - [ ] 11.1 Implement the packaging scripts
    - Create `scripts/package.mjs` running, without a shell, in order: clean `out/`, `tsc` (step `compile`), `eslint` (step `lint`), `vsce ls` plus the contents check (step `contents`), `vsce package` into `dist/.build/`, then move the `.vsix` into `dist/`; any failure prints `package failed at step: <name>`, removes `dist/.build/` and any `.vsix` it wrote, and exits non-zero
    - Create `scripts/check-vsix-contents.mjs` asserting from the `vsce ls` list that `package.json`, `README.md`, `LICENSE`, `out/extension.js` and each production dependency's license file are present, and that nothing from `src/soase_validator`, `reference/`, `tests/`, `.kiro/`, no `uv` binary, no Definition JSON and no game file is included
    - Add the `NOTICE`-style third-party license text needed for `vscode-languageclient` and its dependencies to the package contents
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 15.10_

  - [ ]* 11.2 Write the packaging smoke test
    - File `test/unit/package-script.test.ts`: `npm run package` exits 0 and produces exactly one `.vsix` in `dist/`; with an injected TypeScript error the script exits non-zero, names the `compile` step and leaves no `.vsix` or `dist/.build/`
    - _Requirements: 13.1, 13.5, 15.10_

- [ ] 12. Integrate with the repository and write documentation
  - [ ] 12.1 Write the extension README, LICENSE and notices
    - Create `vscode-extension/LICENSE` as a copy of the repository MIT license
    - Create `vscode-extension/README.md` with separate sections for installing `uv`, installing the `.vsix`, Settings, Commands, States and Building from source (Node.js 24 or newer and npm); list every setting by exact id, every command by exact title and the states `stopped`, `starting`, `running` and `error`
    - State: the nearest project `soase.json` takes precedence over editor settings; link to the configuration section of the main README instead of restating setting meanings; the only network access is the `uvx` fetch and how a local `serverSource` avoids it; `uv` must provide Python 3.14 or later, managed Python downloads must stay enabled, no minimum `uv` version; `uvPath` must name `uvx` or `uvx.exe` itself; `*.manifest` files are not associated and manifest support is deferred; the unofficial-community-tool statement and the credits (zombiesrus5, GoaFan77, Stardock Entertainment, Ironclad Games)
    - Use placeholder paths only
    - _Requirements: 10.3, 13.2, 13.9, 14.1, 14.2, 14.3, 14.4, 14.5, 14.7, 14.8, 14.9_

  - [ ] 12.2 Update the project README
    - In the root `README.md` remove the statement that no VS Code extension is shipped and the generic LSP client instructions, link to `vscode-extension/README.md` in their place, and remove the extension bullet from "Future improvements"
    - _Requirements: 14.6_

  - [ ]* 12.3 Write documentation and network consistency tests
    - File `test/unit/docs.test.ts`: the extension README lists every setting id and command title from the manifest and every state name, contains the required statements, and neither README nor manifest contains a drive-letter or user-home path
    - File `test/unit/no-network.test.ts`: `src/` contains no `fetch(`, `XMLHttpRequest` or network module import, and no `console.log` or `process.stdout` use
    - _Requirements: 6.10, 10.1, 10.2, 10.3, 14.1, 14.2, 14.7, 15.11_

- [ ] 13. Final checkpoint - Ensure all tests pass
  - Run in `vscode-extension/`: `npm ci`, `npm run package`, `npm run test` and `npm audit`; run `uv run ruff check`, `uv run ruff format --check` and `uv run pytest` in the repository root. Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; core implementation tasks are never optional
- Each task references specific requirements for traceability
- Property tests validate the universal correctness properties of the design (fast-check, at least 100 examples); unit and host tests validate specific examples and edge cases
- Property 11 is an example-based manifest check rather than a generated property
- Windows, macOS and Linux coverage of the host tests needs a CI matrix that is not part of this plan (Requirement 13.6)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["3.1", "3.3", "3.5", "3.6", "3.8", "3.10", "3.13"] },
    { "id": 4, "tasks": ["3.2", "3.4", "3.7", "3.9", "3.11", "3.12", "3.14", "5.1", "6.1", "6.2", "6.3", "6.5"] },
    { "id": 5, "tasks": ["5.2", "6.4", "6.6", "8.1"] },
    { "id": 6, "tasks": ["7.1", "8.2"] },
    { "id": 7, "tasks": ["9.1", "9.2"] },
    { "id": 8, "tasks": ["9.3", "9.4", "9.5", "11.1", "12.1", "12.2"] },
    { "id": 9, "tasks": ["11.2", "12.3"] }
  ]
}
```
