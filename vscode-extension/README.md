# SoaSE Validator for VS Code

A VS Code extension for Sins of a Solar Empire (Sins 1) mod files. It starts the
[soase-validator](../README.md) language server and connects it to the editor,
so you get diagnostics, completion, hover help, go-to-definition and a quick fix
that adds a file missing from its manifest.

The extension is a thin wrapper. All validation, completion and configuration
logic lives in the `soase-validator` Engine behind the language server. The
extension registers the file types, finds `uvx`, starts the server over stdio,
forwards editor settings and offers commands to restart and inspect it.

This is an unofficial community tool. It is not affiliated with or endorsed by
Stardock Entertainment, Ironclad Games, zombiesrus5 or GoaFan77. See
[Credits](#credits).

The extension is installed from a `.vsix` file, downloaded from a GitHub release or
built from source. It is not published on the
Visual Studio Marketplace or Open VSX.

## Supported files

The extension registers the language `soase` for these file extensions:
`.entity`, `.galaxy`, `.brushes`, `.sounddata`, `.str`, `.constants`,
`.galaxyScenarioDef`, `.particle` and `.explosiondata`.

`*.manifest` files are not associated with the extension, and no `*.manifest`
document is sent to the server. Manifest support through the extension is
deferred. Use `soase-validator manifest check` and `soase-validator manifest
sync` from the command line meanwhile.

The extension activates when you open one of these files, or open a folder that
contains a `soase.json` or one of these files. In an untrusted workspace the
server is not started, because the server command and the settings name
executables and file paths. It starts once you trust the workspace, without a
window reload.

## Syntax coloring

The extension colors the supported files with a TextMate grammar for the
language `soase`. The grammar assigns these categories and leaves the actual
colors to the active theme:

- key
- string
- number
- hex color
- boolean
- list punctuation (the `[` and `]` delimiters)
- the `=` operator

Coloring follows token shape only. The grammar looks at one line at a time and
does not know which key a value belongs to, so it never judges whether a value
is valid for its key. Definition-aware coloring is not provided; what the
Definitions accept is reported as diagnostics by the server.

Coloring works without the server. It is available in an untrusted workspace,
before the server has started and when `uvx` is not found.

Booleans are matched in any capitalization, so `TRUE`, `true` and `True` are all
colored as booleans. The server reports lowercase booleans, so a colored
boolean is not necessarily a valid one.

## Installing uv

The extension runs the server with `uvx`, which is part of
[uv](https://docs.astral.sh/uv/). Install `uv` by following the
[uv installation instructions](https://docs.astral.sh/uv/getting-started/installation/).
The extension never downloads or installs `uv` itself.

Requirements on the `uv` side:

- `uv` must be able to provide Python 3.14 or later. `uvx` downloads a managed
  Python when none is available.
- Managed Python downloads must stay enabled in the `uv` configuration.
- No minimum `uv` version is required.

The extension looks for `uvx` (`uvx.exe` on Windows) in this order:

1. The setting `soase-validator.uvPath`, when it is not empty. If it does not
   name an existing executable file, `uvx` is reported as not found and no other
   location is searched.
2. The `PATH` of the VS Code process.
3. The per-user bin directory of the `uv` standalone installer: `~/.local/bin`
   on macOS and Linux, `%USERPROFILE%\.local\bin` on Windows.
4. The `bin` directory under `CARGO_HOME`, which defaults to `~/.cargo`.

`soase-validator.uvPath` must name `uvx` or `uvx.exe` itself, not `uv` and not
the directory that holds it, for example `~/path/to/uvx`. A leading `~` and
environment variable references are expanded.

If `uvx` is not found, the extension shows one error notification with the
actions "Open install instructions" and "Set uvPath", sets the status to
`error`, and writes every searched location to the output channel. After you
install `uv` or change the setting, run **SoaSE Validator: Restart Server**.

## Installing the .vsix

VS Code and Kiro both install extensions from a `.vsix` file. The
recommended way is to download a released `.vsix`. If you want an unreleased
change, or no release suits you, build one from source instead.

1. Download `soase-validator-<version>.vsix` from the latest
   [GitHub release](https://github.com/Donos47/soase-validator/releases). Use the
   newest release unless you need an older one.
   To build the file yourself, follow [Building from source](#building-from-source)
   and use the file it writes to `vscode-extension/dist/`.
2. Open the Extensions view.
3. Choose the `...` menu at the top of the view and select **Install from
   VSIX...**.
4. Pick the `.vsix` file. Reload the window if the editor asks you to.

In VS Code you can also install from a terminal:

```
code --install-extension <file>.vsix
```

The extension needs VS Code 1.131.0 or later and runs on Windows, macOS and
Linux. Kiro is a VS Code fork that reports VS Code 1.131.0 as its VS Code-compatible
version (Kiro 1.4.121), which meets this minimum, so the same `.vsix` installs in
Kiro through the Extensions view. The extension also needs [uv](#installing-uv)
to run the server; coloring works without it.

To update, install the newer `.vsix` the same way. A released version is never
rebuilt under the same number.

## Settings

Every setting id below starts with `soase-validator.`. For what each Server
Setting means, see the
[configuration section of the main README](../README.md#configuration). This
page does not repeat those meanings.

### Precedence

The nearest project `soase.json` takes precedence over the editor settings, and
so do the server's environment variables. The full order is in
[Where settings come from](../README.md#where-settings-come-from). The
extension sends only the settings you have set, under a `soase-validator`
section, and leaves paths unchanged. It does not read `soase.json` or the
user-level file, and does not interpret values. A setting whose value has the
wrong type is left out and reported once in the output channel.

Changing a Server Setting sends the new values to the running server without a
restart. Editing `soase.json` or the user-level file needs no action either,
because the server watches those files.

### Server Settings

These are forwarded to the server, using the `soase.json` key names:

- `soase-validator.gameVersion`
- `soase-validator.referenceRoots`
- `soase-validator.modRoots`
- `soase-validator.layers`
- `soase-validator.language`
- `soase-validator.disabledCodes`
- `soase-validator.numeric.integerStrict`
- `soase-validator.numeric.decimalAllowInteger`
- `soase-validator.manifest.unreferencedSeverity`
- `soase-validator.manifest.exemptUnlisted`
- `soase-validator.manifest.exemptUnreferenced`
- `soase-validator.reportOverrides`
- `soase-validator.suppressLimitedReferenceNotice`

Layer aliases (`aliases`) are not an editor setting. The server reads them only
from the user-level `config.json`, which `soase-validator config show` locates.
The `soase-validator config` command has no subcommand that writes aliases, so
add the `aliases` object to that file yourself.

### Extension Settings

These control the extension and are never sent to the server:

- `soase-validator.uvPath`: path to `uvx` or `uvx.exe` itself. Default: empty.
- `soase-validator.serverSource`: package source passed to `uvx --from`.
  Default: empty, which means the default source (see
  [Network access](#network-access-and-offline-use)).
- `soase-validator.startupTimeoutSeconds`: seconds to wait for the server to
  answer `initialize`. Default 180, minimum 10. The first start can take long
  while `uvx` downloads packages.
- `soase-validator.trace.server`: `off`, `messages` or `verbose`. Default
  `off`. `messages` logs the method name and request id of each protocol
  message. `verbose` also logs parameters, which can include mod file content.

### Example

```json
{
  "soase-validator.gameVersion": "rebellion-1.98",
  "soase-validator.referenceRoots": {
    "rebellion-1.98": "~/path/to/sins-rebellion-reference"
  },
  "soase-validator.modRoots": ["~/path/to/my-mod"]
}
```

## Commands

All commands are available from the command palette.

- **SoaSE Validator: Restart Server** stops the server, finds `uvx` again,
  starts a new server and sends the settings again. It also starts a server
  that you stopped with **Stop Server**, and clears the automatic restart
  count.
- **SoaSE Validator: Stop Server** stops the server and sets the status to
  `stopped`. The server is not started again on document events until you run
  **Restart Server**.
- **SoaSE Validator: Show Output** reveals the `SoaSE Validator` output
  channel.
- **SoaSE Validator: Show Status** shows the state, the resolved `uvx` path, the
  server command and the server version. Missing values show as `not
  available`; a running server that reports no version shows `unknown`.

## States

The status bar item reads `SoaSE: <state>` and is visible while a SoaSE file is
the active editor. Select it to run **Show Status**.

- `stopped`: no server is running. This is the state before the first start and
  after **Stop Server**.
- `starting`: the server process was launched and has not yet answered
  `initialize`.
- `running`: the server answered `initialize`.
- `error`: the server could not be started or has failed. The cause is in the
  output channel.

If the server exits unexpectedly while running, the extension restarts it
automatically, up to three times within five minutes. After a fourth exit in
that window it stops and sets the state to `error`; run **Restart Server** to
try again.

## Network access and offline use

The extension makes no network requests of its own, has no telemetry and never
sends mod content, file paths or settings anywhere. The only network access is
the `uvx` fetch of the server package when `uvx` runs the server command:

```
uvx --from <source> soase-validator-lsp
```

`<source>` defaults to `git+https://github.com/Donos47/soase-validator`, which
follows the default branch of the repository. No tag or commit is pinned.

To avoid the fetch, point `soase-validator.serverSource` at a local checkout of
the repository, for example `~/path/to/soase-validator`. `uvx` then builds the
server from that directory and needs no network beyond what that source
requires. A source that `uvx` already has available also starts without a
connection. If `uvx` cannot fetch the package, the extension reports a start
failure and does not retry on its own.

## Troubleshooting

- Open the `SoaSE Validator` output channel with **SoaSE Validator: Show
  Output**. It holds the extension's timestamped messages and the server's
  standard error, including the exit code and the last 20 lines after an
  unexpected exit.
- Run **SoaSE Validator: Show Status** to see the state, the `uvx` path that was
  found and the exact server command.
- A slow first start is normal while `uvx` downloads and builds the package.
  Raise `soase-validator.startupTimeoutSeconds` if it times out.
- If `uvx` exits before the server answers, the notification shows the first 20
  lines of its output and the output channel has all of it. The extension does
  not retry; fix the cause and run **Restart Server**.
- Set `soase-validator.trace.server` to `messages` to see the protocol traffic.

## Building from source

Use this when you want a build of the current source. You need Node.js 24 or newer,
npm and a clone of this repository. From the `vscode-extension/` directory:

```
npm ci
npm run package
```

`npm run package` compiles, lints, checks the package contents and writes
`dist/soase-validator-<version>.vsix`. It exits with a non-zero code and leaves
no partial file when a step fails. Install the file as described in
[Installing the .vsix](#installing-the-vsix).

The individual steps, which you can also run on their own:

```
npm run compile
npm run lint
npm run test
```

- `npm run compile` builds the TypeScript sources into `out/`.
- `npm run lint` runs ESLint.
- `npm run test` compiles, then runs the unit and property tests and the VS Code
  host tests.

## Credits

This extension builds on the work of others.

- zombiesrus5 wrote the Eclipse SoaSE plugin. Its Definitions and validation
  behaviour are what the `soase-validator` Engine reproduces.
- GoaFan77 wrote the Sins manifest updater script, whose behaviour is
  incorporated in the Engine's manifest sync.
- Stardock Entertainment and Ironclad Games created Sins of a Solar Empire.
  The file formats, names and rules the tool checks belong to the game. No game
  content is included here.

This is an unofficial community tool. It is not affiliated with or endorsed by
Stardock Entertainment, Ironclad Games, zombiesrus5 or GoaFan77.

## License

Released under the MIT License (see `LICENSE`). That license does not cover the
third-party works credited above. See the
[main README](../README.md#license) for details.
