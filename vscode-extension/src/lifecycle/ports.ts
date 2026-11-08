/**
 * Interfaces the server controller shares with the VS Code adapters. This
 * module imports types from the core only, so the controller and its tests
 * run in plain Node.
 */

import type { LogLevel } from '../format/log-line';
import type { UvxResolution } from '../launcher/resolve-uvx';
import type { ServerCommand } from '../launcher/server-command';
import type { UvVersionProbe } from '../launcher/uv-version';
import type { TraceLevel } from '../settings/extension-settings';
import type { NotifyKind, ServerState } from './lifecycle';

/** A timer that can be cancelled. */
export interface TimerHandle {
  /** Cancels the timer; harmless after it has fired. */
  cancel(): void;
}

/** How a Server process ended. */
export interface ServerExit {
  /** Exit code, or null when the process was ended by a signal. */
  readonly code: number | null;
  /** Signal name, or null when the process exited by itself. */
  readonly signal: string | null;
}

/** The part of a spawned Server process the controller uses. */
export interface ServerProcessHandle {
  /** Operating system process id, undefined until spawned. */
  readonly pid: number | undefined;
  /** Resolves once, with the exit, when the process has ended. */
  readonly exited: Promise<ServerExit>;
  /** Terminates the process tree immediately; used for the forced kill. */
  kill(): void;
}

/** Buttons an error notification can offer. */
export type NotifyAction =
  | 'open-install-docs'
  | 'set-uv-path'
  | 'show-output'
  | 'restart-server';

/** Text shown by an error notification. */
export interface NotifyDetails {
  /** First line of the notification. */
  readonly message: string;
  /** Extra lines, for example the first 20 stderr lines; empty when none. */
  readonly lines: readonly string[];
}

/** Everything the controller needs from the user interface. */
export interface UiPort {
  /** Updates the Status Item synchronously. */
  setState(state: ServerState): void;
  /** Writes one Extension line to the Output Channel. */
  log(level: LogLevel, message: string): void;
  /**
   * Shows one error notification with the given buttons.
   *
   * @returns The chosen action, or undefined when the user dismisses it.
   */
  notifyError(
    kind: NotifyKind,
    details: NotifyDetails,
    actions: readonly NotifyAction[],
  ): Promise<NotifyAction | undefined>;
  /** Opens the uv installation documentation in the default browser. */
  openInstallDocs(): Promise<void>;
  /** Opens the settings editor filtered to `soase-validator.uvPath`. */
  openUvPathSetting(): Promise<void>;
  /** Reveals the Output Channel. */
  showOutput(): void;
}

/** Callbacks the client factory invokes for one start. All are bound to one generation by the controller. */
export interface ClientHooks {
  /** Called once with the process as soon as it has been spawned, before `initialize` completes. */
  onSpawned(process: ServerProcessHandle): void;
  /** Called for each complete line the process writes to standard error. */
  onStderrLine(line: string): void;
  /** Called once when the process has ended, for any reason. */
  onExit(exit: ServerExit): void;
}

/** A language client whose `initialize` request has completed. */
export interface StartedClient {
  /** The process the client talks to. */
  readonly process: ServerProcessHandle;
  /** `serverInfo.version` from the `initialize` result; undefined when absent. */
  readonly serverVersion: string | undefined;
  /** Sends LSP `shutdown` and `exit`; resolves when the client has stopped. Never kills the process. */
  stop(): Promise<void>;
  /** Sends one `workspace/didChangeConfiguration` with the payload built at call time. */
  sendConfiguration(): void;
  /** Applies a trace level without restarting. */
  setTrace(level: TraceLevel): void;
}

/** Extension-only settings the controller reads at each start. */
export interface ControllerSettings {
  readonly serverSource: string;
  readonly timeoutSeconds: number;
  readonly trace: TraceLevel;
}

/** Workspace information for the Server Command. */
export interface FolderInfo {
  readonly paths: readonly string[];
  readonly home: string;
}

/** Everything the controller needs from the outside. */
export interface ControllerPorts {
  /** Epoch milliseconds. */
  readonly now: () => number;
  /** Starts a one-shot timer. */
  readonly setTimer: (ms: number, fn: () => void) => TimerHandle;
  /** Resolves uvx from the current `uvPath` setting and environment. */
  readonly resolve: () => UvxResolution;
  /** Runs `uvx --version` for the resolved path. */
  readonly probeVersion: (uvxPath: string) => Promise<UvVersionProbe>;
  /** Reads the current Extension-only settings. */
  readonly settings: () => ControllerSettings;
  /** Reads the current workspace folders and home directory. */
  readonly folders: () => FolderInfo;
  /**
   * Spawns the Server, starts the language client and resolves after the
   * `initialize` response. Rejects when the process cannot be spawned or the
   * client fails to initialise.
   */
  readonly startClient: (command: ServerCommand, hooks: ClientHooks) => Promise<StartedClient>;
  /** The user interface. */
  readonly ui: UiPort;
}
