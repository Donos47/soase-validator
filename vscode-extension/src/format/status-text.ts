import type { ServerState } from '../lifecycle/lifecycle';

/** Placeholder for a value that does not exist. */
export const NOT_AVAILABLE = 'not available';

/** Placeholder for a running Server that reported no version. */
export const UNKNOWN_VERSION = 'unknown';

/** What the status command displays. */
export interface StatusSnapshot {
  readonly state: ServerState;
  /** Resolved uvx path. */
  readonly uvxPath?: string;
  /** Executable and arguments joined by spaces, for display only. */
  readonly command?: string;
  /** `serverInfo.version` from the `initialize` result. */
  readonly serverVersion?: string;
}

/** Status bar item text per state. */
export const STATUS_ITEM_LABELS: Readonly<Record<ServerState, string>> = {
  stopped: '$(circle-slash) SoaSE: stopped',
  starting: '$(sync~spin) SoaSE: starting',
  running: '$(check) SoaSE: running',
  error: '$(error) SoaSE: error',
};

/**
 * Returns the status bar item text for a state.
 *
 * @param state Current Server state.
 * @returns The label, including its codicon.
 */
export function statusItemLabel(state: ServerState): string {
  return STATUS_ITEM_LABELS[state];
}

/**
 * Renders the status command text, one `label: value` line per value.
 *
 * A missing path or command renders as `not available`. The Server
 * version renders as given; without one it renders `unknown` while the
 * Server is running and `not available` otherwise.
 *
 * @param snapshot Values to display.
 * @returns Multi-line text without a trailing line end.
 */
export function formatStatus(snapshot: StatusSnapshot): string {
  return [
    `State: ${snapshot.state}`,
    `uvx: ${present(snapshot.uvxPath) ?? NOT_AVAILABLE}`,
    `Command: ${present(snapshot.command) ?? NOT_AVAILABLE}`,
    `Server version: ${versionText(snapshot)}`,
  ].join('\n');
}

/**
 * Reads `serverInfo.version` from an `initialize` result.
 *
 * @param initializeResult The unvalidated result of the `initialize` request.
 * @returns The version, or undefined when it is absent, empty or not a string.
 */
export function extractServerVersion(initializeResult: unknown): string | undefined {
  if (typeof initializeResult !== 'object' || initializeResult === null) {
    return undefined;
  }
  const info: unknown = (initializeResult as Record<string, unknown>).serverInfo;
  if (typeof info !== 'object' || info === null) {
    return undefined;
  }
  const version: unknown = (info as Record<string, unknown>).version;
  return typeof version === 'string' && version.length > 0 ? version : undefined;
}

function present(value: string | undefined): string | undefined {
  return value === undefined || value.length === 0 ? undefined : value;
}

function versionText(snapshot: StatusSnapshot): string {
  const version = present(snapshot.serverVersion);
  if (version !== undefined) {
    return version;
  }
  return snapshot.state === 'running' ? UNKNOWN_VERSION : NOT_AVAILABLE;
}
