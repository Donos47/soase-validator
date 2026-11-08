import { execFile } from 'node:child_process';

/** Default time allowed for `uvx --version` before the probe gives up. */
export const DEFAULT_PROBE_TIMEOUT_MS = 10_000;

/** Outcome of a finished process: exit code and captured standard output. */
export interface ExecResult {
  readonly code: number;
  readonly stdout: string;
}

/**
 * Runs `file` with `args` and resolves once the process exits, whatever its
 * exit code. Rejects when the process cannot be spawned or exceeds `timeoutMs`.
 */
export type ExecPort = (
  file: string,
  args: readonly string[],
  timeoutMs: number,
) => Promise<ExecResult>;

/** Result of probing `uvx --version`. */
export type UvVersionProbe =
  | { readonly available: true; readonly text: string }
  | { readonly available: false; readonly reason: string };

/**
 * Production {@link ExecPort} backed by `child_process.execFile`.
 *
 * No shell is involved and the arguments are passed as an array. A non-zero
 * exit resolves with its code; a spawn failure or a timeout rejects.
 *
 * @param file - Executable to run.
 * @param args - Arguments passed verbatim.
 * @param timeoutMs - Time after which the child is killed and the promise rejects.
 * @returns The exit code and standard output.
 */
export const execFileAdapter: ExecPort = (file, args, timeoutMs) =>
  new Promise<ExecResult>((resolve, reject) => {
    execFile(
      file,
      [...args],
      { timeout: timeoutMs, windowsHide: true, encoding: 'utf8' },
      (error, stdout) => {
        if (error === null) {
          resolve({ code: 0, stdout });
          return;
        }
        if (error.killed === true) {
          reject(new Error(`timed out after ${timeoutMs} ms`));
          return;
        }
        // A numeric code is an exit status; a string code (ENOENT, EACCES) is a spawn failure.
        if (typeof error.code === 'number') {
          resolve({ code: error.code, stdout });
          return;
        }
        reject(new Error(error.message));
      },
    );
  });

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Runs `uvx --version` through the injected port.
 *
 * Never rejects: spawn failures, non-zero exits and timeouts all become
 * `available: false` with a reason.
 *
 * @param uvxPath - Resolved `uvx` executable.
 * @param exec - Process runner.
 * @param timeoutMs - Time allowed before the probe reports a timeout.
 * @returns The trimmed version text, or the reason `uvx` could not be run.
 */
export async function probeUvVersion(
  uvxPath: string,
  exec: ExecPort,
  timeoutMs: number = DEFAULT_PROBE_TIMEOUT_MS,
): Promise<UvVersionProbe> {
  let timer: NodeJS.Timeout | undefined;
  // The port is asked to time out too; this guard covers ports that never settle.
  const guard = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`timed out after ${timeoutMs} ms`)), timeoutMs);
  });
  try {
    const result = await Promise.race([exec(uvxPath, ['--version'], timeoutMs), guard]);
    if (result.code !== 0) {
      return { available: false, reason: `exited with code ${result.code}` };
    }
    return { available: true, text: result.stdout.trim() };
  } catch (error) {
    return { available: false, reason: describeError(error) };
  } finally {
    clearTimeout(timer);
  }
}
