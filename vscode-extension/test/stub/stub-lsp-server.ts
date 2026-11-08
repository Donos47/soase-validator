/**
 * Stub LSP server for host tests.
 *
 * Runs as a standalone Node program that speaks LSP over stdio. Command-line
 * flags (see `STUB_FLAGS`) select the scenario. The protocol owns stdout, so
 * every other message goes to stderr.
 */
import { appendFileSync } from 'node:fs';

import {
  CodeAction,
  CodeActionKind,
  createConnection,
  Diagnostic,
  DidChangeWatchedFilesNotification,
  ErrorCodes,
  InitializeResult,
  RegistrationRequest,
  ResponseError,
  StreamMessageReader,
  StreamMessageWriter,
  TextDocumentSyncKind,
  UnregistrationRequest,
} from 'vscode-languageserver/node';
import type { Message, ServerCapabilities } from 'vscode-languageserver/node';

import {
  STUB_CAPABILITIES,
  STUB_COMPLETION_LABEL,
  STUB_DIAGNOSTIC_CODE,
  STUB_DIAGNOSTIC_MESSAGE,
  STUB_DIAGNOSTIC_RANGE,
  STUB_DIAGNOSTIC_SEVERITY,
  STUB_DIAGNOSTIC_SOURCE,
  STUB_EXIT_NOTIFICATION,
  STUB_FAILURE_MESSAGE,
  STUB_FLAGS,
  STUB_QUICK_FIX_TITLE,
  STUB_SERVER_NAME,
  STUB_SERVER_VERSION,
  STUB_STDERR_LINE,
  STUB_UNREGISTER_WATCHERS_NOTIFICATION,
  STUB_WATCH_GLOBS,
  STUB_WATCH_REGISTRATION_ID,
} from './stub-constants';
import type { StubCapability } from './stub-constants';

/** Options parsed from the command line. */
interface StubOptions {
  readonly logFile: string | undefined;
  readonly serverInfo: boolean;
  readonly capabilities: ReadonlySet<StubCapability>;
  readonly failRequests: boolean;
  readonly initializeDelayMs: number;
}

/**
 * Parses the command-line flags.
 *
 * @param argv Arguments after the script name.
 * @returns The parsed options.
 * @throws Error When a flag is unknown or lacks its value.
 */
function parseOptions(argv: readonly string[]): StubOptions {
  let logFile: string | undefined;
  let serverInfo = true;
  let capabilities: ReadonlySet<StubCapability> = new Set(STUB_CAPABILITIES);
  let failRequests = false;
  let initializeDelayMs = 0;

  const valueOf = (index: number, flag: string): string => {
    const value = argv[index];
    if (value === undefined) {
      throw new Error(`${flag} needs a value`);
    }
    return value;
  };

  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    switch (flag) {
      case STUB_FLAGS.log:
        index += 1;
        logFile = valueOf(index, flag);
        break;
      case STUB_FLAGS.noServerInfo:
        serverInfo = false;
        break;
      case STUB_FLAGS.capabilities: {
        index += 1;
        const names = valueOf(index, flag)
          .split(',')
          .map((name) => name.trim())
          .filter((name) => name !== '' && name !== 'none');
        const known = new Set<StubCapability>();
        for (const name of names) {
          const match = STUB_CAPABILITIES.find((capability) => capability === name);
          if (match === undefined) {
            throw new Error(`unknown capability: ${name}`);
          }
          known.add(match);
        }
        capabilities = known;
        break;
      }
      case STUB_FLAGS.failRequests:
        failRequests = true;
        break;
      case STUB_FLAGS.initializeDelay: {
        index += 1;
        const delay = Number(valueOf(index, flag));
        if (!Number.isFinite(delay)) {
          throw new Error(`${flag} needs a number of milliseconds`);
        }
        initializeDelayMs = delay;
        break;
      }
      default:
        throw new Error(`unknown flag: ${String(flag)}`);
    }
  }
  return { logFile, serverInfo, capabilities, failRequests, initializeDelayMs };
}

/**
 * Reads messages from stdin and records each one before the connection sees it.
 *
 * Logging in the reader covers every message, including those the connection
 * answers itself (`shutdown`, `exit`) and those no handler is registered for.
 */
class RecordingReader extends StreamMessageReader {
  public constructor(
    stream: NodeJS.ReadableStream,
    private readonly record: (message: Message) => void,
  ) {
    super(stream);
  }

  public override listen(
    callback: (message: Message) => void,
  ): ReturnType<StreamMessageReader['listen']> {
    return super.listen((message) => {
      this.record(message);
      callback(message);
    });
  }
}

/**
 * Starts the stub server.
 *
 * @param options Parsed command-line options.
 */
function run(options: StubOptions): void {
  const record = (message: Message): void => {
    if (options.logFile !== undefined) {
      // Synchronous so the line is on disk before an `exit` message ends the process.
      appendFileSync(options.logFile, `${JSON.stringify(message)}\n`);
    }
  };

  const connection = createConnection(
    new RecordingReader(process.stdin, record),
    new StreamMessageWriter(process.stdout),
  );

  let watchersRegistered = false;
  let clientDynamicWatchers = false;

  const failure = (): ResponseError<undefined> =>
    new ResponseError(ErrorCodes.InternalError, STUB_FAILURE_MESSAGE);

  const stubDiagnostic = (): Diagnostic => ({
    range: {
      start: { ...STUB_DIAGNOSTIC_RANGE.start },
      end: { ...STUB_DIAGNOSTIC_RANGE.end },
    },
    severity: STUB_DIAGNOSTIC_SEVERITY,
    code: STUB_DIAGNOSTIC_CODE,
    source: STUB_DIAGNOSTIC_SOURCE,
    message: STUB_DIAGNOSTIC_MESSAGE,
  });

  connection.onInitialize(async (params): Promise<InitializeResult> => {
    const delay = options.initializeDelayMs;
    if (delay < 0) {
      await new Promise<never>(() => undefined);
    } else if (delay > 0) {
      await new Promise<void>((resolve) => setTimeout(resolve, delay));
    }

    const capabilities: ServerCapabilities = {
      textDocumentSync: { openClose: true, change: TextDocumentSyncKind.Full, save: true },
    };
    if (options.capabilities.has('completion')) {
      capabilities.completionProvider = { triggerCharacters: [' ', '"'] };
    }
    if (options.capabilities.has('hover')) {
      capabilities.hoverProvider = true;
    }
    if (options.capabilities.has('definition')) {
      capabilities.definitionProvider = true;
    }
    if (options.capabilities.has('codeAction')) {
      capabilities.codeActionProvider = { codeActionKinds: [CodeActionKind.QuickFix] };
    }

    clientDynamicWatchers =
      params.capabilities.workspace?.didChangeWatchedFiles?.dynamicRegistration === true;

    const result: InitializeResult = { capabilities };
    if (options.serverInfo) {
      result.serverInfo = { name: STUB_SERVER_NAME, version: STUB_SERVER_VERSION };
    }
    return result;
  });

  connection.onInitialized(() => {
    if (clientDynamicWatchers) {
      void registerWatchers();
    }
  });

  const registerWatchers = async (): Promise<void> => {
    try {
      await connection.sendRequest(RegistrationRequest.type, {
        registrations: [
          {
            id: STUB_WATCH_REGISTRATION_ID,
            method: DidChangeWatchedFilesNotification.method,
            registerOptions: { watchers: STUB_WATCH_GLOBS.map((globPattern) => ({ globPattern })) },
          },
        ],
      });
      watchersRegistered = true;
    } catch (error) {
      process.stderr.write(`stub: could not register watchers: ${String(error)}\n`);
    }
  };

  const unregisterWatchers = async (): Promise<void> => {
    if (!watchersRegistered) {
      return;
    }
    watchersRegistered = false;
    try {
      await connection.sendRequest(UnregistrationRequest.type, {
        unregisterations: [
          {
            id: STUB_WATCH_REGISTRATION_ID,
            method: DidChangeWatchedFilesNotification.method,
          },
        ],
      });
    } catch (error) {
      process.stderr.write(`stub: could not unregister watchers: ${String(error)}\n`);
    }
  };

  connection.onNotification(STUB_UNREGISTER_WATCHERS_NOTIFICATION, () => {
    void unregisterWatchers();
  });

  connection.onNotification(STUB_EXIT_NOTIFICATION, (params: { code?: number } | undefined) => {
    process.exit(typeof params?.code === 'number' ? params.code : 1);
  });

  connection.onDidOpenTextDocument((params) => {
    void connection.sendDiagnostics({
      uri: params.textDocument.uri,
      diagnostics: [stubDiagnostic()],
    });
  });

  connection.onDidCloseTextDocument((params) => {
    void connection.sendDiagnostics({ uri: params.textDocument.uri, diagnostics: [] });
  });

  connection.onCompletion(() => {
    if (options.failRequests) {
      return failure();
    }
    return { isIncomplete: false, items: [{ label: STUB_COMPLETION_LABEL }] };
  });

  connection.onHover(() => (options.failRequests ? failure() : null));

  connection.onDefinition(() => (options.failRequests ? failure() : null));

  connection.onCodeAction((params) => {
    if (options.failRequests) {
      return failure();
    }
    const matching = params.context.diagnostics.filter(
      (diagnostic) => diagnostic.code === STUB_DIAGNOSTIC_CODE,
    );
    if (matching.length === 0) {
      return [];
    }
    const action: CodeAction = {
      title: STUB_QUICK_FIX_TITLE,
      kind: CodeActionKind.QuickFix,
      diagnostics: matching,
    };
    return [action];
  });

  // A closed stdin without `exit` means the client is gone.
  process.stdin.on('end', () => process.exit(1));

  process.stderr.write(`${STUB_STDERR_LINE}\n`);
  connection.listen();
}

try {
  run(parseOptions(process.argv.slice(2)));
} catch (error) {
  process.stderr.write(`stub: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(2);
}
