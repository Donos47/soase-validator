/**
 * Fixed values shared by the stub LSP server and the host tests.
 *
 * The module holds plain data only, so host tests can import it without
 * starting the stub or loading `vscode-languageserver`.
 */

/** Server name reported in `serverInfo`. */
export const STUB_SERVER_NAME = 'soase-validator';

/** Server version reported in `serverInfo`. */
export const STUB_SERVER_VERSION = '0.0.0-stub';

/** Line the stub writes to stderr when it starts. */
export const STUB_STDERR_LINE = 'soase-validator stub server started';

/** Code of the Diagnostic published on `didOpen`; it also triggers the quick fix. */
export const STUB_DIAGNOSTIC_CODE = 'SOASE-M010';

/** Message of the published Diagnostic. */
export const STUB_DIAGNOSTIC_MESSAGE = 'Stub: file is not listed in the manifest';

/** Source of the published Diagnostic. */
export const STUB_DIAGNOSTIC_SOURCE = 'soase-validator';

/** LSP `DiagnosticSeverity.Warning`. */
export const STUB_DIAGNOSTIC_SEVERITY = 2;

/** Zero-based range of the published Diagnostic. */
export const STUB_DIAGNOSTIC_RANGE = {
  start: { line: 0, character: 0 },
  end: { line: 0, character: 5 },
} as const;

/** Title of the quick fix returned for a Diagnostic with `STUB_DIAGNOSTIC_CODE`. */
export const STUB_QUICK_FIX_TITLE = 'Add stub-file.entity to stub.manifest';

/** Label of the single completion item returned when requests do not fail. */
export const STUB_COMPLETION_LABEL = 'stub-completion';

/** Message of the error returned for failing requests. */
export const STUB_FAILURE_MESSAGE = 'Stub: request failed on purpose';

/** Registration id of the file watchers, the same id the real Server uses. */
export const STUB_WATCH_REGISTRATION_ID = 'soase-validator-file-watchers';

/** Glob patterns of the dynamically registered file watchers. */
export const STUB_WATCH_GLOBS: readonly string[] = [
  '**/*.{entity,galaxy,brushes,sounddata,str,constants,galaxyScenarioDef,particle,explosiondata}',
  '**/*.manifest',
  '**/soase.json',
];

/** Custom notification that makes the stub exit with `{ code }` (default 1). */
export const STUB_EXIT_NOTIFICATION = 'soase-validator-stub/exit';

/** Custom notification that makes the stub unregister its file watchers. */
export const STUB_UNREGISTER_WATCHERS_NOTIFICATION = 'soase-validator-stub/unregisterWatchers';

/** Command-line flags of the stub server. */
export const STUB_FLAGS = {
  /** `--log <file>`: append every received message to the file as a JSON line. */
  log: '--log',
  /** `--no-server-info`: leave `serverInfo` out of the `initialize` result. */
  noServerInfo: '--no-server-info',
  /**
   * `--capabilities <list>`: comma-separated subset of `STUB_CAPABILITIES` to
   * advertise; `none` advertises none. All are advertised without the flag.
   */
  capabilities: '--capabilities',
  /** `--fail-requests`: answer completion, hover, definition and code action with an error. */
  failRequests: '--fail-requests',
  /**
   * `--initialize-delay <ms>`: wait before answering `initialize`; a negative
   * value never answers.
   */
  initializeDelay: '--initialize-delay',
} as const;

/** Capability names accepted by `--capabilities`. */
export const STUB_CAPABILITIES = ['completion', 'hover', 'definition', 'codeAction'] as const;

/** Capability name accepted by `--capabilities`. */
export type StubCapability = (typeof STUB_CAPABILITIES)[number];
