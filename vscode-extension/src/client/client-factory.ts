/**
 * Creates and starts the language client. This is the only module that
 * imports `vscode-languageclient/node`, and it loads the library with a
 * dynamic `import()` on the first start so activation stays fast.
 */

import * as vscode from 'vscode';
import type * as LanguageClientLibrary from 'vscode-languageclient/node';

import type { ServerCommand } from '../launcher/server-command';
import { LineSplitter } from '../format/line-splitter';
import { formatLogLine } from '../format/log-line';
import type { LogLevel } from '../format/log-line';
import { extractServerVersion } from '../format/status-text';
import type { ClientHooks, StartedClient } from '../lifecycle/ports';
import type { TraceLevel } from '../settings/extension-settings';
import { buildPayload } from '../settings/payload';
import type { ConfigReader } from '../settings/payload';
import { spawnServer } from './spawn-server';
import type { ServerProcess, TestOverride } from './spawn-server';
import { toLibraryTrace } from './trace';

type Library = typeof LanguageClientLibrary;

/** Name and id of the language client; the id is also the setting section the library reads. */
const CLIENT_ID = 'soase-validator';
const CLIENT_NAME = 'SoaSE Validator';

/** Dependencies of the client factory. */
export interface ClientFactoryDeps {
  /** The shared Output Channel; receives stderr and trace output. */
  readonly outputChannel: vscode.OutputChannel;
  /** Reader behind the `initializationOptions` function and `sendConfiguration`. */
  readonly readConfig: ConfigReader;
  /** Called at each start; undefined outside Test mode or when no override is set. */
  readonly getTestOverride: () => TestOverride | undefined;
  /** Current trace level, applied when the client is created. */
  readonly getTrace: () => TraceLevel;
  /** Called with each wrong-typed Server Setting found when a payload is built. */
  readonly onInvalidSetting: (key: string, value: unknown) => void;
  /** Environment for the Server process. */
  readonly env: NodeJS.ProcessEnv;
}

/** The channel handed to the language client, plus the trace switch. */
interface ClientChannel extends vscode.LogOutputChannel {
  /** Sets the level the library reads to decide whether tracing is wanted. */
  setTraceLevel(level: TraceLevel): void;
}

let libraryPromise: Promise<Library> | undefined;

/**
 * Loads the language client library once.
 *
 * @returns The library module.
 * @throws When the library cannot be loaded; a later call tries again.
 */
function loadLibrary(): Promise<Library> {
  libraryPromise ??= import('vscode-languageclient/node').catch((error: unknown) => {
    libraryPromise = undefined;
    throw error;
  });
  return libraryPromise;
}

/**
 * Chooses the log level that makes the library derive the wanted trace.
 *
 * The library traces only while the trace channel reports `Trace`, and then
 * reads `soase-validator.trace.server`; a level other than `Trace` turns
 * tracing off whatever the setting says.
 *
 * @param level The trace setting.
 * @returns The channel log level to report.
 */
function channelLevelFor(level: TraceLevel): vscode.LogLevel {
  return level === 'off' ? vscode.LogLevel.Info : vscode.LogLevel.Trace;
}

/**
 * Adapts the shared Output Channel to the `LogOutputChannel` the library needs.
 *
 * The library writes stderr and trace lines through `error` and `trace`
 * methods that a plain Output Channel lacks, and drops trace lines unless the
 * channel level is `Trace`. Every line is written in the Extension's log line
 * format, with trace lines at `debug` level.
 *
 * @param base The shared Output Channel.
 * @param initial The trace level at creation.
 * @returns The adapter. `dispose` releases only the adapter's own emitter.
 */
function createClientChannel(base: vscode.OutputChannel, initial: TraceLevel): ClientChannel {
  const emitter = new vscode.EventEmitter<vscode.LogLevel>();
  let current = channelLevelFor(initial);

  const writer = (level: LogLevel) => (message: string | Error): void => {
    const text = message instanceof Error ? (message.stack ?? message.message) : message;
    base.appendLine(formatLogLine(level, text, Date.now()));
  };

  return {
    get name(): string {
      return base.name;
    },
    get logLevel(): vscode.LogLevel {
      return current;
    },
    onDidChangeLogLevel: emitter.event,
    trace: writer('debug'),
    debug: writer('debug'),
    info: writer('info'),
    warn: writer('warn'),
    error: writer('error'),
    append: (value: string): void => {
      base.append(value);
    },
    appendLine: (value: string): void => {
      base.appendLine(value);
    },
    replace: (value: string): void => {
      base.replace(value);
    },
    clear: (): void => {
      base.clear();
    },
    show: (columnOrPreserveFocus?: vscode.ViewColumn | boolean, preserveFocus?: boolean): void => {
      base.show(typeof columnOrPreserveFocus === 'boolean' ? columnOrPreserveFocus : preserveFocus);
    },
    hide: (): void => {
      base.hide();
    },
    dispose: (): void => {
      emitter.dispose();
    },
    setTraceLevel: (level: TraceLevel): void => {
      const next = channelLevelFor(level);
      if (next !== current) {
        current = next;
        emitter.fire(next);
      }
    },
  };
}

/**
 * Forwards each complete stderr line of a test-override process to the hooks.
 *
 * @param process The process whose stderr is read.
 * @param onLine Receives each complete line.
 */
function forwardStderr(process: ServerProcess, onLine: (line: string) => void): void {
  const splitter = new LineSplitter();
  process.child.stderr?.on('data', (chunk: Buffer) => {
    for (const line of splitter.push(chunk)) {
      onLine(line);
    }
  });
  void process.exited.then(() => {
    for (const line of splitter.end()) {
      onLine(line);
    }
  });
}

/**
 * Builds the `startClient` port of ControllerPorts.
 *
 * Each call spawns the Server (`spawnServer`, or the override's `spawn`),
 * reports the process through `hooks.onSpawned`, forwards stderr lines and the
 * exit through `hooks`, creates and starts a LanguageClient over the child,
 * and resolves after the `initialize` response. It rejects when the spawn
 * fails or the client fails to start.
 *
 * @param deps The collaborators of the factory.
 * @returns A function that starts one Server and its client.
 */
export function createStartClient(
  deps: ClientFactoryDeps,
): (command: ServerCommand, hooks: ClientHooks) => Promise<StartedClient> {
  const note = (level: LogLevel, message: string): void => {
    deps.outputChannel.appendLine(formatLogLine(level, message, Date.now()));
  };

  const currentPayload = (): ReturnType<typeof buildPayload>['payload'] => {
    const result = buildPayload(deps.readConfig);
    for (const entry of result.invalid) {
      deps.onInvalidSetting(entry.key, entry.value);
    }
    return result.payload;
  };

  return async (command: ServerCommand, hooks: ClientHooks): Promise<StartedClient> => {
    const library = await loadLibrary();

    const override = deps.getTestOverride();
    let serverProcess: ServerProcess;
    if (override !== undefined) {
      serverProcess = override.spawn(command, deps.env);
      forwardStderr(serverProcess, (line) => {
        hooks.onStderrLine(line);
      });
    } else {
      const spawned = spawnServer(command, deps.env, (line) => {
        hooks.onStderrLine(line);
      });
      // The library attaches its own stderr reader in the microtasks that
      // follow, before the first stderr data event can arrive, so each line
      // reaches the Output Channel once.
      await spawned.spawned;
      serverProcess = spawned;
    }
    void serverProcess.exited.then((exit) => {
      hooks.onExit(exit);
    });
    hooks.onSpawned(serverProcess);

    const channel = createClientChannel(deps.outputChannel, deps.getTrace());
    const options: LanguageClientLibrary.LanguageClientOptions = {
      documentSelector: [{ scheme: 'file', language: 'soase' }],
      outputChannel: channel,
      traceOutputChannel: channel,
      initializationOptions: currentPayload,
      // The controller shows the only user-visible failure notification, so the
      // library's own popups are switched off.
      revealOutputChannelOn: library.RevealOutputChannelOn.Never,
      initializationFailedHandler: () => false,
      errorHandler: {
        error: () => ({ action: library.ErrorAction.Continue, handled: true }),
        closed: () => ({ action: library.CloseAction.DoNotRestart, handled: true }),
      },
    };
    // `detached: true` keeps the library from killing the process after stop;
    // the controller owns the forced kill.
    const serverOptions: LanguageClientLibrary.ServerOptions = () =>
      Promise.resolve({ process: serverProcess.child, detached: true });
    const client = new library.LanguageClient(CLIENT_ID, CLIENT_NAME, serverOptions, options);

    try {
      await client.start();
    } catch (error) {
      channel.dispose();
      throw error;
    }

    const serverVersion = extractServerVersion(client.initializeResult);
    return {
      process: serverProcess,
      serverVersion,
      async stop(): Promise<void> {
        try {
          await client.stop();
        } finally {
          channel.dispose();
        }
      },
      sendConfiguration(): void {
        const params = { settings: currentPayload() };
        client
          .sendNotification(library.DidChangeConfigurationNotification.type, params)
          .catch((error: unknown) => {
            note('warn', `Sending the configuration failed: ${String(error)}`);
          });
      },
      setTrace(level: TraceLevel): void {
        channel.setTraceLevel(level);
        client.setTrace(toLibraryTrace(level, library.Trace)).catch((error: unknown) => {
          note('warn', `Applying the trace level failed: ${String(error)}`);
        });
      },
    };
  };
}
