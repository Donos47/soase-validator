# Requirements Document

## Introduction

The `soase-validator` package ships a Language Server Protocol server (entry point `soase-validator-lsp`) that provides diagnostics, completion, hover help, go-to-definition and a manifest quick fix for Sins of a Solar Empire (Sins 1) mod files. The package is distributed from GitHub and run with `uvx --from git+https://github.com/Donos47/soase-validator soase-validator-lsp`, with no PyPI publication. VS Code has no generic way to start such a server, so users currently need a third-party LSP client extension and hand-written configuration.

This feature adds a VS Code extension that is a thin wrapper: it registers the SoaSE file types, locates `uv`, starts the existing LSP server over stdio, forwards editor settings, and offers restart and status commands. All validation, completion and configuration logic stays in the Engine behind the LSP server (specification `soase-validator`, Requirements 5 to 8 and 14). The extension only translates VS Code settings and events into LSP client behaviour.

### Scope

In scope: the VS Code extension (activation, language registration, server launch, settings forwarding, commands, output channel, error handling, packaging as `.vsix`, repository integration, tests). The Extension lives in the subdirectory `vscode-extension/` of this repository.

Out of scope: any change to the validation rules or to the server's settings model; the MCP server and CLI; Sins of a Solar Empire II; publication to the Visual Studio Marketplace or Open VSX (intended later, not covered here, and this specification does not require a GitHub release asset); syntax coloring (listed as a future improvement in the project README); formatting and refactoring; bundling or redistributing the Python package, `uv` or any game file; one Server per workspace folder; association of `*.manifest` files by the Extension (deferred); registration of the further file extensions the Engine supports (`.randomeventdefs`, `.starscapedata`, `.skyboxbackdropdata`, `.asteroidDef`, `.groups`, `.planetItemTypeCount`), which are a possible later addition.

## Glossary

- **Extension**: The VS Code extension defined by this specification.
- **Server**: The `soase-validator-lsp` process from the `soase-validator` package, speaking LSP over stdio.
- **Launcher**: The Extension component that resolves the command line for the Server and starts it.
- **uv**: The `uv` package manager executable, which provides `uvx`.
- **Server Command**: The executable and arguments the Launcher starts. By default it is `uvx` with the arguments `--from git+https://github.com/Donos47/soase-validator soase-validator-lsp`.
- **SoaSE File**: A file with one of the extensions `.entity`, `.galaxy`, `.brushes`, `.sounddata`, `.str`, `.constants`, `.galaxyScenarioDef`, `.particle` or `.explosiondata`. A file with the extension `.manifest` is not a SoaSE File.
- **Language Identifier**: The VS Code language identifier `soase` contributed by the Extension.
- **Extension Directory**: The directory `vscode-extension/` in the repository root that holds the Extension sources.
- **Server Settings**: The settings the Server accepts from an editor, using the `soase.json` key names, either directly or under a `soase-validator` section (specification `soase-validator`, Requirement 8.14 and design section Configuration).
- **Output Channel**: The VS Code output channel named `SoaSE Validator` that shows Server log lines and Extension messages.
- **Status Item**: The VS Code status bar entry that shows the Server state.
- **VSIX**: The packaged Extension file installed with `code --install-extension`.
- **Reference Root, Layer, Chain, Mod Root, Game Version**: As defined in the specification `soase-validator`.

## Requirements

### Requirement 1: Language registration

**User Story:** As a mod developer, I want SoaSE files recognised by VS Code, so that the Server is applied to them and they are distinguishable from other files.

#### Acceptance Criteria

1. THE Extension SHALL contribute exactly one VS Code language identifier, `soase`, whose registered file extensions are exactly `.entity`, `.galaxy`, `.brushes`, `.sounddata`, `.str`, `.constants`, `.galaxyScenarioDef`, `.particle` and `.explosiondata`.
2. WHEN a file whose name ends in a SoaSE File extension is opened in the editor, THE Extension SHALL set the language mode of that file to the Language Identifier.
3. WHEN a SoaSE File is opened, changed or closed in the editor, THE Extension SHALL send the matching LSP `textDocument/didOpen`, `textDocument/didChange` or `textDocument/didClose` notification to the Server through the document synchronisation of the language client.
4. IF a file is opened whose name does not end in a SoaSE File extension, THEN THE Extension SHALL NOT send any LSP notification for that file to the Server.
5. IF the Server is not running, THEN THE Extension SHALL keep SoaSE Files open and editable and SHALL keep their language mode unchanged.
6. THE Extension SHALL NOT register the extension `.manifest` or any file extension other than those in criterion 1 under the Language Identifier, SHALL NOT associate `*.manifest` files with the Server, and SHALL NOT send `*.manifest` documents to the Server. The Server still handles `*.manifest` files if another LSP client sends them; manifest support through the Extension is deferred.

### Requirement 2: Activation

**User Story:** As a mod developer, I want the Extension to start only when I work on mod files, so that VS Code startup is not slowed and unrelated projects are unaffected.

#### Acceptance Criteria

1. WHEN a SoaSE File is opened in the editor, THE Extension SHALL activate.
2. WHEN a workspace folder is opened that contains a file named `soase.json` or a SoaSE File, THE Extension SHALL activate.
3. IF neither a SoaSE File has been opened nor an opened workspace folder contains a file named `soase.json` or a SoaSE File, THEN THE Extension SHALL remain inactive and SHALL NOT start the Server.
4. WHEN activation completes in a trusted workspace, THE Extension SHALL start exactly one Server per VS Code window, and a later activation trigger in the same window SHALL NOT start a second Server.
5. THE Extension SHALL declare support for untrusted workspaces as limited, because the Server Command and the Server Settings can name executables and file paths.
6. WHILE a workspace is untrusted, THE Extension SHALL NOT start the Server.
7. WHEN a workspace that was untrusted becomes trusted and the Extension is active, THE Extension SHALL start the Server once without requiring a window reload.
8. WHEN the Extension activates, THE Extension SHALL complete its activation function within 500 milliseconds without waiting for the Server to finish starting.
9. IF the Server process fails to start, THEN THE Extension SHALL show one error notification that states the Server failed to start, SHALL remain active, and SHALL NOT retry automatically except as stated in Requirement 11.3.

### Requirement 3: Locating uv

**User Story:** As a mod developer, I want the Extension to find `uv` on my machine, so that I do not have to configure a path.

#### Acceptance Criteria

1. WHEN the Launcher resolves `uvx` and the setting `soase-validator.uvPath` contains at least one non-whitespace character, THE Launcher SHALL use that value, after the expansion in criterion 5, as the `uvx` executable and SHALL NOT search the `PATH` or the default install location.
2. WHEN the Launcher resolves `uvx` and `soase-validator.uvPath` is empty or contains only whitespace, THE Launcher SHALL search for `uvx` on the `PATH` of the VS Code process.
3. WHEN `soase-validator.uvPath` is empty and `uvx` is not found on the `PATH`, THE Launcher SHALL search the following directories in this order and SHALL use the first one that contains the `uvx` executable: (1) the per-user bin directory of the `uv` standalone installer, which is `~/.local/bin` on macOS and Linux and `%USERPROFILE%\.local\bin` on Windows; (2) `$CARGO_HOME/bin`, where `CARGO_HOME` defaults to `~/.cargo` WHEN the environment variable is unset.
4. THE Launcher SHALL resolve the executable name `uvx` on macOS and Linux and `uvx.exe` on Windows.
5. THE Launcher SHALL expand a leading `~` and environment variable references in `soase-validator.uvPath` before use.
6. WHEN the Extension activates and the Launcher has resolved `uvx`, THE Launcher SHALL run `uvx` with its version argument and SHALL write the resolved executable path and the reported version to the Output Channel within 10 seconds of resolution.
7. IF `soase-validator.uvPath` is non-empty and does not name an existing executable file, THEN THE Launcher SHALL report `uvx` as not found, SHALL NOT fall back to the `PATH` or the default install location, and SHALL write the configured value and the failure to the Output Channel, so that Requirement 4 applies.
8. IF the version command in criterion 6 fails to run, exits with a non-zero code, or does not finish within 10 seconds, THEN THE Launcher SHALL write the resolved path and a message indicating the version is unavailable to the Output Channel, and SHALL still treat `uvx` as resolved.

### Requirement 4: Missing uv

**User Story:** As a mod developer without `uv`, I want a clear message and a way forward, so that I can install it and continue.

#### Acceptance Criteria

1. IF `uvx` cannot be found at the path in `soase-validator.uvPath` (when set) or in any directory on the `PATH`, THEN THE Extension SHALL show exactly one error notification per activation attempt that states that `uv` is required and offers exactly two actions: "Open install instructions" and "Set uvPath".
2. IF `uvx` cannot be found, THEN THE Extension SHALL set the Status Item to an error state and SHALL write each searched location, one per line, to the Output Channel.
3. IF `uvx` cannot be found, THEN THE Extension SHALL NOT start the Server and SHALL leave open documents without Diagnostics from the Server.
4. WHEN the user selects "Open install instructions", THE Extension SHALL open the `uv` installation documentation page in the default browser.
5. WHEN the user selects "Set uvPath", THE Extension SHALL open the VS Code settings editor filtered to `soase-validator.uvPath`.
6. WHEN the user dismisses the notification without selecting an action, THE Extension SHALL keep the Status Item in the error state and SHALL NOT show another notification until the next activation attempt.
7. THE Extension SHALL NOT download, install or run an installer for `uv` on its own.
8. WHEN `soase-validator.uvPath` or the `PATH` changes the outcome of the search so that `uvx` is found, THE Extension SHALL start the Server on the next restart command or window reload without requiring any other step.

### Requirement 5: Starting the Server

**User Story:** As a mod developer, I want the Server started for me over stdio, so that diagnostics, completion and hover work without manual setup.

#### Acceptance Criteria

1. WHEN the Launcher has resolved `uvx`, THE Extension SHALL start the Server Command as a child process and connect to it as a language client over its standard input and output.
2. THE Server Command SHALL be `uvx --from <source> soase-validator-lsp`, where `<source>` defaults to `git+https://github.com/Donos47/soase-validator`.
3. WHERE the setting `soase-validator.serverSource` is non-empty, THE Launcher SHALL use its value as `<source>` (for example a local checkout path or a Git reference). WHILE the setting is empty, THE default `<source>` SHALL track the default branch of the repository, and THE Extension SHALL NOT pin a tag or commit.
4. THE Launcher SHALL pass the arguments to the child process as an argument array and SHALL NOT build the command through a shell string.
5. THE Extension SHALL write every line the Server writes to its standard error stream to the Output Channel.
6. THE Extension SHALL NOT write anything to the Server's standard input other than LSP messages.
7. WHEN the Extension starts the Server Command, THE Status Item SHALL show the starting state from process launch until the LSP `initialize` response is received, and SHALL then show the running state.
8. IF the LSP `initialize` response is not received within the time set by `soase-validator.startupTimeoutSeconds` (default 180 seconds, minimum 10 seconds), THEN THE Extension SHALL apply Requirement 11.1 and SHALL show one error notification with a "Show output" action and a "Restart server" action.
9. IF the Server process exits unexpectedly, THEN THE Extension SHALL set the Status Item to an error state, SHALL write the exit code and the last 20 stderr lines to the Output Channel, and SHALL apply the automatic restart rules of Requirements 11.3 and 11.4; WHEN no further automatic restart takes place, THE Extension SHALL show one error notification with a "Show output" action and a "Restart server" action.
10. IF the Server process cannot be spawned, THEN THE Extension SHALL set the Status Item to an error state, SHALL write the spawn failure reason to the Output Channel, and SHALL show one error notification with a "Show output" action and a "Restart server" action.
11. WHEN the user selects the "Restart server" action, THE Extension SHALL terminate any remaining Server process and start a new Server process using the Server Command, with the Status Item showing the starting state.
12. THE Extension SHALL start the Server with the working directory set to the first workspace folder, or to the user's home directory WHEN no workspace folder is open.
13. THE Extension SHALL run at most one Server process at any time per VS Code window.
14. WHILE a multi-root workspace is open, THE Extension SHALL serve all workspace folders with the single Server of the window and SHALL NOT start one Server per workspace folder.

### Requirement 6: Forwarding editor settings

**User Story:** As a mod developer, I want to set Reference Roots, Game Version and Layers in VS Code, so that I do not need a `soase.json` for simple setups.

#### Acceptance Criteria

1. THE Extension SHALL contribute one VS Code setting for each Server Settings key listed in criterion 2, each named `soase-validator.<key>` with `<key>` equal to the matching `soase.json` key. For nested keys, `<key>` is the dotted path (for example `soase-validator.numeric.integerStrict`).
2. THE Extension SHALL contribute the following Server Settings keys, which are the keys documented for `soase.json` in the specification `soase-validator`: `gameVersion`, `referenceRoots`, `modRoots`, `layers`, `aliases`, `language`, `disabledCodes`, `numeric` (`integerStrict`, `decimalAllowInteger`), `manifest` (`unreferencedSeverity`, `exemptUnlisted`, `exemptUnreferenced`), `reportOverrides` and `suppressLimitedReferenceNotice`.
3. WHEN the language client initialises, THE Extension SHALL send the set Server Settings as the LSP initialization options, using the `soase.json` key names, under a `soase-validator` section. The Server reads only that section when it is present, for both the initialization options and the `workspace/didChangeConfiguration` settings.
4. WHEN a Server Setting changes in VS Code, THE Extension SHALL send exactly one `workspace/didChangeConfiguration` notification within 1000 ms of the change event, carrying the full set of Server Settings under the same `soase-validator` section, and THE Extension SHALL NOT restart the Server.
5. THE Extension SHALL omit from the payload every Server Setting that the user has not set at any VS Code scope (user, workspace or workspace folder), so that the Server's own defaults and lower-precedence sources apply. A setting explicitly set to an empty value (empty list, empty object or empty string) counts as set and is sent as that empty value.
6. THE Extension SHALL NOT interpret, validate the meaning of, merge or resolve precedence among Server Settings, and SHALL NOT read `soase.json`, the user-level configuration file or the Server's environment variables itself. Precedence stays in the Engine (project `soase.json`, then environment, then editor settings, then user file, then defaults). The only check the Extension makes is the type check of Requirement 11.5.
7. THE Extension SHALL state in the description of each contributed setting that a project `soase.json` and the Server's environment variables take precedence over the editor value.
8. THE Extension SHALL pass paths in Server Settings to the Server unchanged, character for character, leaving `~`, environment variable expansion and relative-path resolution to the Server.
9. WHEN the user changes `soase.json` or the user-level file, THE Extension SHALL send no `workspace/didChangeConfiguration` notification and SHALL NOT restart the Server, because the Server watches those files itself.
10. THE Extension SHALL NOT include any machine-specific absolute path in a default value, a setting description or an example, and SHALL use placeholders such as `~/path/to/sins-rebellion-reference` instead.
11. THE Extension SHALL contribute the following Extension settings, which are not Server Settings and are never sent to the Server: `soase-validator.uvPath` (string, default empty), `soase-validator.serverSource` (string, default empty), `soase-validator.startupTimeoutSeconds` (number, default 180, minimum 10) and `soase-validator.trace.server` (Requirement 8.9).

### Requirement 7: Commands

**User Story:** As a mod developer, I want commands to restart the Server and see its state, so that I can recover from problems and confirm that it is running.

#### Acceptance Criteria

1. THE Extension SHALL contribute the command `SoaSE Validator: Restart Server` (`soase-validator.restartServer`).
2. WHEN `soase-validator.restartServer` runs, THE Extension SHALL stop the Server process, re-resolve the Server Command, start a new Server process, and re-send the Server Settings.
3. IF the Server process has not exited within 5 seconds of the stop request during `soase-validator.restartServer`, THEN THE Extension SHALL terminate the process, continue with the restart, and write the forced termination to the Output Channel.
4. IF the Server Command cannot be resolved or the new Server process fails to start during `soase-validator.restartServer`, THEN THE Extension SHALL show an error notification that names the failure, write the failure details to the Output Channel, set the Status Item to an error state, and leave no Server process running.
5. THE Extension SHALL contribute the command `SoaSE Validator: Show Output` (`soase-validator.showOutput`) that reveals the Output Channel.
6. THE Extension SHALL contribute the command `SoaSE Validator: Show Status` (`soase-validator.showStatus`) that shows the Server state (one of starting, running, stopped or error), the resolved `uvx` path, the Server Command and the Server version reported in the LSP `initialize` result.
7. IF the `uvx` path is unresolved, the Server is not running, or the `initialize` result reports no Server version, THEN `soase-validator.showStatus` SHALL show the text "not available" in place of each missing value.
8. THE Extension SHALL contribute the command `SoaSE Validator: Stop Server` (`soase-validator.stopServer`) that stops the Server and sets the Status Item to a stopped state.
9. WHILE the Server is stopped by `soase-validator.stopServer`, THE Extension SHALL NOT restart it automatically on document events.
10. WHEN `soase-validator.restartServer` runs while the Server was stopped by `soase-validator.stopServer`, THE Extension SHALL start a new Server process and resume automatic starts on document events.
11. THE Extension SHALL make every command available from the command palette.

### Requirement 8: Status Item and Output Channel

**User Story:** As a mod developer, I want visible feedback on the Server state, so that I can tell whether validation is active.

#### Acceptance Criteria

1. THE Extension SHALL create exactly one Output Channel named `SoaSE Validator` per VS Code window.
2. THE Status Item SHALL show exactly one of the states stopped, starting, running or error, and SHALL show the text label of the current state.
3. WHEN the Server state changes, THE Extension SHALL update the Status Item to the new state within 1 second.
4. WHILE the Server has not been started in the current window, THE Status Item SHALL show the stopped state.
5. WHILE a SoaSE File is the active editor, THE Status Item SHALL be visible.
6. WHILE the active editor is not a SoaSE File, THE Status Item SHALL be hidden.
7. WHEN the user selects the Status Item, THE Extension SHALL run `soase-validator.showStatus`.
8. THE Extension SHALL prefix every Extension message in the Output Channel with an ISO 8601 timestamp and one of the levels `error`, `warn`, `info` or `debug`.
9. THE Extension SHALL provide the setting `soase-validator.trace.server` with the values `off`, `messages` and `verbose`, defaulting to `off`.
10. WHERE `soase-validator.trace.server` is `off`, THE Extension SHALL write no LSP protocol message traces to the Output Channel.
11. WHERE `soase-validator.trace.server` is `messages`, THE Extension SHALL write the method name and request identifier of each LSP message to the Output Channel without message parameters.
12. WHERE `soase-validator.trace.server` is `verbose`, THE Extension SHALL write the method name, request identifier and parameters of each LSP message to the Output Channel.
13. WHEN the value of `soase-validator.trace.server` changes, THE Extension SHALL apply the new value to subsequent LSP messages without restarting the Server.
14. IF `soase-validator.trace.server` is not `verbose`, THEN THE Extension SHALL NOT write mod file content to the Output Channel.

### Requirement 9: Diagnostics and server features in VS Code

**User Story:** As a mod developer, I want the Server's features available in the usual VS Code places, so that the Extension replaces the Eclipse plugin experience.

#### Acceptance Criteria

1. WHEN the Server returns its `initialize` result, THE Extension SHALL register the language client for each of the diagnostics, completion, hover, go-to-definition, code action and watched-file features that the result advertises, and SHALL NOT register a feature that the result does not advertise.
2. WHEN the Server publishes Diagnostics for a document, THE Extension SHALL show each Diagnostic in the VS Code Problems panel with the code, severity, message and range exactly as the Server supplies them.
3. WHEN the Server publishes an empty Diagnostics list for a document, THE Extension SHALL remove all previously shown Diagnostics for that document from the Problems panel.
4. THE Extension SHALL leave all Diagnostic content, severity and codes unchanged from what the Server publishes, and SHALL NOT add, drop, merge or re-rank Diagnostics.
5. WHEN the Server sends a dynamic registration request for `workspace/didChangeWatchedFiles`, THE Extension SHALL accept the registration and SHALL send a `workspace/didChangeWatchedFiles` notification to the Server for each matching file create, change or delete event.
6. WHEN the Server sends a dynamic unregistration request for `workspace/didChangeWatchedFiles`, THE Extension SHALL stop sending file-change notifications for that registration.
7. WHEN the Server returns a code action for a `SOASE-M010` Diagnostic, THE Extension SHALL show it as a VS Code quick fix on that Diagnostic's range, with the title the Server supplies.
8. IF the Server returns an error or no result for a completion, hover, go-to-definition or code action request, THEN THE Extension SHALL show no result for that request, SHALL keep the existing Diagnostics unchanged, and SHALL NOT show an Extension-generated substitute result.
9. THE Extension SHALL contain no validation, completion, hover or reference-resolution logic of its own.

### Requirement 10: Offline operation and privacy

**User Story:** As a mod developer, I want my mod content to stay on my machine, so that I can use the Extension on unreleased work.

#### Acceptance Criteria

1. THE Extension SHALL NOT transmit mod file contents, file paths or settings values over the network, to any destination, at any time.
2. THE Extension SHALL NOT include telemetry, meaning code that collects or sends usage, error, crash or environment data to any remote endpoint.
3. THE Extension SHALL make zero network requests from its own code. The only network access SHALL be the `uvx` fetch of the Server package when `uvx` runs the Server Command, which the Extension SHALL document in its README.
4. WHERE `soase-validator.serverSource` names a local directory or an already-fetched Git reference, THE Extension SHALL NOT require network access beyond what `uvx` does for that source.
5. THE Extension SHALL write zero bytes to the Server's standard input other than LSP messages and SHALL leave the Server's standard output reserved for LSP messages.
6. IF `uvx` cannot fetch the Server package because the network is unavailable, THEN THE Extension SHALL show an error message stating that the Server could not be started because the package could not be fetched, SHALL leave open editor documents unmodified, and SHALL NOT retry the fetch on its own.
7. WHERE the Server package is already available to `uvx` without a fetch, THE Extension SHALL start the Server and provide LSP features with no network connectivity.

### Requirement 11: Error handling and resilience

**User Story:** As a mod developer, I want failures explained and recoverable, so that a broken start does not leave VS Code unusable.

#### Acceptance Criteria

1. IF the Server does not complete the LSP `initialize` exchange within the number of seconds set by `soase-validator.startupTimeoutSeconds` (default 180, minimum 10), THEN THE Extension SHALL stop the Server process, set the Status Item to an error state, and write one entry to the Output Channel stating that the startup timed out and giving the configured number of seconds.
2. IF the Server process cannot be spawned, THEN THE Extension SHALL write the operating system error text to the Output Channel, show exactly one error notification indicating that the Server failed to start, and set the Status Item to an error state.
3. IF the Server process exits unexpectedly after it reached the running state, THEN THE Extension SHALL restart it automatically, up to three restarts within any rolling five-minute window.
4. IF the Server process exits a fourth time within a rolling five-minute window, THEN THE Extension SHALL stop restarting it automatically, set the Status Item to an error state, and write one entry to the Output Channel stating that automatic restarts were stopped.
5. IF a setting has a value whose type does not match the type declared for that setting, THEN THE Extension SHALL omit that setting from the payload sent to the Server and SHALL write one warning to the Output Channel naming the setting, once per distinct invalid value.
6. IF activation of the Extension throws an error, THEN THE Extension SHALL write the error message to the Output Channel, show one error notification, and SHALL NOT throw out of the activation function, so that other VS Code extensions continue to activate and run.
7. WHEN the Extension deactivates, THE Extension SHALL stop the Server process within 5 seconds and dispose the Output Channel and the Status Item.
8. IF `soase-validator.startupTimeoutSeconds` is a number below 10, THEN THE Extension SHALL use 10 seconds and write one warning to the Output Channel; IF it is not a number, THEN THE Extension SHALL use 180 seconds and write one warning to the Output Channel.

### Requirement 12: Python and Server compatibility

**User Story:** As a mod developer, I want the Server to run on my machine without managing Python myself, so that installation is one step.

#### Acceptance Criteria

1. WHEN the Extension starts the Server, THE Extension SHALL launch it through `uvx`, which provides the Python 3.14 or later interpreter that the package requires by downloading a managed Python when none is available. THE Extension SHALL NOT require a minimum `uv` version.
2. IF `uvx` exits with a non-zero exit code before the LSP `initialize` request completes and its error output reports that no suitable Python interpreter can be provided, THEN THE Extension SHALL write the complete `uvx` error output to the Output Channel, SHALL show the first 20 lines of that output in the error notification of Requirement 5.10, and SHALL leave the Server in the stopped state.
3. WHEN the Server returns the LSP `initialize` result, THE Extension SHALL store the Server version from the `serverInfo.version` field, and SHALL display it in the output of `soase-validator.showStatus`.
4. IF the `initialize` result contains no `serverInfo.version` value, THEN THE Extension SHALL display the text "unknown" as the Server version in the output of `soase-validator.showStatus`.
5. WHERE the Server is started from the default source, THE Extension SHALL NOT compare the Server version against any minimum or maximum version and SHALL NOT refuse to start the Server because of its version.

### Requirement 13: Packaging and installation

**User Story:** As a member of the modding community, I want to install the Extension from a file, so that no marketplace is needed.

#### Acceptance Criteria

1. WHEN the documented build command is run, THE project SHALL package the Extension as a single `.vsix` file with the `vsce` tool and exit with code 0.
2. THE `.vsix` SHALL contain the Extension's compiled code, its manifest, its README, its LICENSE and the third-party notices required by its dependencies.
3. THE `.vsix` SHALL NOT contain game files, the `soase-validator` Python package source, `uv` or any Definition.
4. WHEN the documented build command is run on a clean checkout that has only Node.js and npm installed, THE project SHALL produce the `.vsix` without any manual step beyond the documented command.
5. IF the build command fails, THEN THE project SHALL exit with a non-zero code, print an error naming the failing step, and leave no partial `.vsix` file in the output location.
6. THE Extension SHALL activate without error on VS Code for Windows, macOS and Linux.
7. THE Extension manifest SHALL declare the minimum supported VS Code engine version `^1.141.0`.
8. IF the installed VS Code version is lower than the declared minimum engine version, THEN VS Code SHALL refuse to install the `.vsix` and THE Extension SHALL NOT activate.
9. THE Extension SHALL carry the same MIT license as the project's original code, and its README SHALL repeat the unofficial-community-tool statement and the Credits of the `soase-validator` README (zombiesrus5, GoaFan77, Stardock Entertainment and Ironclad Games).
10. THE Extension's dependencies SHALL be version-pinned by a lockfile, and WHEN dependencies are added or updated, THE project SHALL run `npm audit` and report every finding of high or critical severity.
11. THE Extension SHALL use the `vscode-languageclient` library as its language client, at the current stable release from the npm registry when the design is written.
12. THE Extension sources, its `package.json` and its npm lockfile SHALL reside in the Extension Directory.

### Requirement 14: Documentation

**User Story:** As a mod developer, I want installation instructions for the Extension, so that I can set it up from the README alone.

#### Acceptance Criteria

1. THE Extension README SHALL contain a separate section for each of the following: installing `uv`, installing the `.vsix`, the settings of Requirement 6, the commands of Requirement 7 and the states of Requirement 8.
2. THE Extension README SHALL list every setting of Requirement 6 by its exact setting identifier, every command of Requirement 7 by its exact command title, and every state of Requirement 8 by its exact name, with no entry omitted.
3. THE Extension README SHALL state that the nearest project `soase.json` takes precedence over the editor settings.
4. THE Extension README SHALL link to the configuration section of the `soase-validator` README for the meaning of each setting, and SHALL NOT restate those meanings.
5. THE Extension README SHALL document the network access in Requirement 10.3 and the steps to avoid it by setting a local `serverSource`.
6. WHEN the Extension is released, THE project README SHALL remove its statement that no VS Code extension is shipped and its generic LSP client instructions, and SHALL link to the Extension README in their place.
7. THE documentation SHALL use placeholders such as `~/path/to/sins-rebellion-reference` for paths, and SHALL contain zero machine-specific absolute paths (for example, drive-letter paths or user home directory paths).
8. THE Extension README SHALL state that `uv` must be able to provide Python 3.14 or later, that managed Python downloads must not be disabled in the `uv` configuration, and that no minimum `uv` version is required.
9. THE Extension README SHALL state that `*.manifest` files are not associated by the Extension and that manifest support through the Extension is deferred.

### Requirement 15: Quality and tests

**User Story:** As a maintainer, I want the Extension tested, so that launcher and settings changes are safe to ship.

#### Acceptance Criteria

1. THE project SHALL include an automated test suite for the Extension that runs to completion with a single command and exits with a non-zero status if any test fails.
2. THE test suite SHALL include unit tests for the Launcher's executable resolution on Windows, macOS and Linux, using an injected file system and environment, covering for each platform at least one case where the executable is found and one case where it is not found, and covering the search order of Requirement 3.3 (`PATH`, then the installer bin directory, then `$CARGO_HOME/bin` with its default).
3. THE test suite SHALL include unit tests for the settings payload builder, covering omission of unset settings, omission of wrong-type settings, and a payload whose top-level shape is a single `soase-validator` section containing only the set Server Settings.
4. FOR ALL sets of Server Settings, THE payload builder SHALL produce a payload that contains exactly the set keys, with their values unchanged, verified by a property test that runs at least 100 generated examples.
5. THE test suite SHALL include a test that starts the Extension against a stub LSP server process and verifies, in order: the `initialize` request, the initialization options, the `didChangeConfiguration` notification, and the restart sequence (stop of the running stub followed by a new `initialize` request to a new stub process).
6. THE test suite SHALL include a test that verifies the missing-`uv` behaviour of Requirement 4 (the user-visible error and the absence of a started Server process) without starting a Server.
7. THE test suite SHALL include a test that verifies the manifest: the Language Identifier `soase` registers exactly the file extensions listed in Requirement 1.1 and not `.manifest`, and the set of contributed settings equals the Server Settings keys listed in Requirement 6.2 plus the Extension settings listed in Requirement 6.11, with no extras and none missing.
8. WHERE a Python `soase-validator` checkout is available, THE test suite SHALL include an integration test that starts the real Server through the Launcher and receives at least one Diagnostic for a synthetic mod file within 30 seconds.
9. IF no Python `soase-validator` checkout is available, THEN THE test suite SHALL report the integration test of criterion 8 as skipped with a message stating that the checkout is missing, and SHALL NOT report a failure.
10. WHEN the packaging step runs, THE project SHALL run a TypeScript compile and a linter on the Extension code, and SHALL abort packaging with a non-zero exit status if either reports an error.
11. WHILE the Extension runs as a language client for the Server, THE Extension code SHALL write zero bytes to its own process standard output, and SHALL send any diagnostic logging to the Extension's output channel or standard error.

### Requirement 16: Repository integration

**User Story:** As a maintainer, I want the Extension to sit in the repository without disturbing the Python workflow, so that both toolchains stay maintainable.

#### Acceptance Criteria

1. THE project SHALL keep the Extension sources, `package.json` and npm lockfile in the Extension Directory and SHALL use Node.js, TypeScript and npm as the Extension tooling.
2. THE repository `.gitignore` SHALL list `node_modules`, the Extension build output directories (`out` and `dist` below the Extension Directory) and `*.vsix`.
3. THE repository `structure` steering rule SHALL describe the Extension Directory, its tooling and its build output.
4. THE repository `tech` steering rule SHALL state that Node.js and npm are used for the Extension only and that the Engine, LSP server, MCP server and CLI remain Python.
5. WHEN `uv run ruff check`, `uv run ruff format --check` and `uv run pytest` run, THE results SHALL be unaffected by the presence of the Extension Directory, so that no Python tool scans or collects files under it.
6. THE Python package SHALL NOT import from, depend on or ship any file from the Extension Directory.

## Decisions

1. **Language registration.** One shared language identifier `soase` covers the nine SoaSE File extensions; `.manifest` is excluded because it is generic and claiming it workspace-wide would affect unrelated files. Manifest support through the Extension is deferred, and the further Engine-supported extensions are a possible later addition.
2. **Python provisioning.** The Extension relies on `uvx`, which downloads a managed Python by default; no minimum `uv` version is required, and the README states that managed Python downloads must stay enabled.
3. **Fallback `uv` locations.** After the `PATH`, the Launcher searches the standalone installer's per-user bin directory and then `$CARGO_HOME/bin`, which are the locations `uv` installers use.
4. **Server source.** `soase-validator.serverSource` exists and the default tracks the repository's default branch, because no release tags exist and pinning would add maintenance without a defined release process.
5. **Startup timeout.** `soase-validator.startupTimeoutSeconds` defaults to 180 seconds with a minimum of 10, because the first start builds the package from GitHub.
6. **Dependencies and engine.** `vscode-languageclient` is accepted at its current stable release, and the minimum VS Code engine is `^1.141.0`; VS Code has no LTS channel to target instead.
7. **Settings payload.** The `soase-validator` section form is used for initialization options and `didChangeConfiguration`; the Server's `editor_settings_from` serves both and reads only that section when present.
8. **Multi-root workspaces.** One Server per VS Code window, because a single Engine resolves the nearest `soase.json` per file; per-folder Servers are out of scope.
9. **Publication.** Marketplace and Open VSX publication is intended later and is out of scope for this specification, which does not require a GitHub release asset.
10. **Server metadata.** The Server constructs its language server with the name `soase-validator` and version `0.1.0`, which pygls reports as `serverInfo`, so Requirements 7.6 and 12.3 rely on `serverInfo.version`.
11. **Location and tooling.** The Extension lives in `vscode-extension/` with npm and a lockfile, and the `structure` rule and `.gitignore` are updated while the Python workflow stays unchanged.
