/**
 * Spawns the Server process. This is the only module that starts the Server
 * with `child_process`, so the controller works with a vscode-free handle.
 */

import { spawn } from 'node:child_process';
import type { ChildProcess } from 'node:child_process';

import { LineSplitter } from '../format/line-splitter';
import type { ServerCommand } from '../launcher/server-command';
import type { ServerExit, ServerProcessHandle } from '../lifecycle/ports';

/** A spawned Server process; extends the vscode-free handle the controller sees. */
export interface ServerProcess extends ServerProcessHandle {
  /** The child whose stdin and stdout the language client connects to. */
  readonly child: ChildProcess;
}

/** Replaces both uvx resolution and process spawn; honoured only in Test mode. */
export interface TestOverride {
  /** Path reported as the resolved uvx, for example `stub`. */
  readonly uvxPath: string;
  /** Spawns the stub Server instead of the real Server Command. */
  readonly spawn: (command: ServerCommand, env: NodeJS.ProcessEnv) => ServerProcess;
}

/**
 * Spawns the Server Command with shell disabled and all three stdio streams piped.
 *
 * `exited` resolves once when the process ends. `stderrLines` receives each
 * complete stderr line (through a LineSplitter, flushed at exit). `spawned`
 * resolves on the child's `spawn` event and rejects with the operating system
 * error when the child cannot be spawned; in that case `exited` never resolves.
 *
 * Nothing is written to stdin, and stderr is not written to the Output
 * Channel here because the language client already does that.
 *
 * @param command Executable, arguments and working directory.
 * @param env Environment for the child.
 * @param stderrLines Receives each complete stderr line.
 * @returns The process handle plus a promise for the `spawn` event.
 */
export function spawnServer(
  command: ServerCommand,
  env: NodeJS.ProcessEnv,
  stderrLines: (line: string) => void,
): ServerProcess & { readonly spawned: Promise<void> } {
  const isWindows = process.platform === 'win32';
  const child = spawn(command.executable, [...command.args], {
    cwd: command.cwd,
    env,
    shell: false,
    stdio: ['pipe', 'pipe', 'pipe'],
    // A new process group lets kill() signal uvx and the interpreter it starts.
    detached: !isWindows,
    windowsHide: true,
  });

  let hasSpawned = false;
  let hasEnded = false;
  let resolveSpawned!: () => void;
  let rejectSpawned!: (error: Error) => void;
  const spawned = new Promise<void>((resolve, reject) => {
    resolveSpawned = resolve;
    rejectSpawned = reject;
  });
  // The caller may never await `spawned` when the child starts fine.
  spawned.catch(() => undefined);

  let resolveExited!: (exit: ServerExit) => void;
  const exited = new Promise<ServerExit>((resolve) => {
    resolveExited = resolve;
  });

  const splitter = new LineSplitter();
  child.stderr?.on('data', (chunk: Buffer) => {
    for (const line of splitter.push(chunk)) {
      stderrLines(line);
    }
  });

  child.once('spawn', () => {
    hasSpawned = true;
    resolveSpawned();
  });

  child.on('error', (error) => {
    if (!hasSpawned) {
      hasEnded = true;
      rejectSpawned(error);
    }
  });

  // `close` fires after the stdio streams end, so the last stderr lines are
  // delivered before `exited` resolves.
  child.once('close', (code, signal) => {
    if (!hasSpawned) {
      return;
    }
    hasEnded = true;
    for (const line of splitter.end()) {
      stderrLines(line);
    }
    resolveExited({ code, signal });
  });

  let killRequested = false;
  const kill = (): void => {
    const pid = child.pid;
    if (killRequested || hasEnded || pid === undefined) {
      return;
    }
    killRequested = true;
    if (isWindows) {
      const killer = spawn('taskkill', ['/PID', String(pid), '/T', '/F'], {
        shell: false,
        stdio: 'ignore',
        windowsHide: true,
      });
      killer.on('error', () => {
        child.kill();
      });
      return;
    }
    try {
      process.kill(-pid, 'SIGTERM');
    } catch {
      child.kill('SIGTERM');
    }
  };

  return {
    child,
    get pid(): number | undefined {
      return child.pid;
    },
    exited,
    kill,
    spawned,
  };
}
