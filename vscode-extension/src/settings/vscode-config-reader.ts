import * as vscode from 'vscode';

import {
  DEFAULT_STARTUP_TIMEOUT_SECONDS,
  normaliseTimeout,
  normaliseTrace,
  readString,
  type TraceLevel,
} from './extension-settings';
import type { ConfigReader, ScopedValue } from './payload';

const SECTION = 'soase-validator';

/** Extension-only settings after normalisation. */
export interface ExtensionSettings {
  /** Configured `uvPath`; empty when unset or not a string. */
  readonly uvPath: string;
  /** Configured `serverSource`; empty when unset or not a string. */
  readonly serverSource: string;
  /** Startup timeout in seconds, at least the minimum. */
  readonly timeoutSeconds: number;
  /** Trace level of the language client. */
  readonly trace: TraceLevel;
  /** Warnings from normalisation, for the caller to log once each. */
  readonly warnings: readonly string[];
}

/**
 * Create a ConfigReader over `workspace.getConfiguration('soase-validator').inspect(key)`.
 *
 * Only the three scope members are passed on. `defaultValue` is dropped so a
 * key nobody set stays unset. The configuration is read on every call because
 * settings change while the Extension runs.
 *
 * @returns A reader for the scoped values of one setting key.
 */
export function createConfigReader(): ConfigReader {
  return (key: string): ScopedValue => {
    const inspected = vscode.workspace.getConfiguration(SECTION).inspect(key);
    if (inspected === undefined) {
      return {};
    }
    return {
      globalValue: inspected.globalValue,
      workspaceValue: inspected.workspaceValue,
      workspaceFolderValue: inspected.workspaceFolderValue,
    };
  };
}

/**
 * Read and normalise `uvPath`, `serverSource`, `startupTimeoutSeconds` and `trace.server`.
 *
 * The effective value is used, so the defaults contributed by the manifest
 * apply. An unset timeout is the default and raises no warning.
 *
 * @returns The normalised settings and any warnings.
 */
export function readExtensionSettings(): ExtensionSettings {
  const config = vscode.workspace.getConfiguration(SECTION);
  const rawTimeout: unknown = config.get('startupTimeoutSeconds');
  const timeout = normaliseTimeout(
    rawTimeout === undefined ? DEFAULT_STARTUP_TIMEOUT_SECONDS : rawTimeout,
  );
  return {
    uvPath: readString(config.get('uvPath')),
    serverSource: readString(config.get('serverSource')),
    timeoutSeconds: timeout.seconds,
    trace: normaliseTrace(config.get('trace.server')),
    warnings: timeout.warning === undefined ? [] : [timeout.warning],
  };
}
