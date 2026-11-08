/** Default source of the Server package. */
export const DEFAULT_SERVER_SOURCE = 'git+https://github.com/Donos47/soase-validator';

/** Command line for the Server. */
export interface ServerCommand {
  /** Path of the uvx executable. */
  readonly executable: string;
  /** Arguments passed to uvx, one array element each. */
  readonly args: readonly string[];
  /** Working directory of the Server process. */
  readonly cwd: string;
}

/**
 * Formats a command for display in the status text and the log.
 *
 * Elements containing whitespace are wrapped in double quotes so the
 * boundaries stay readable. The result is not meant to be run in a shell.
 *
 * @param command The Server Command.
 * @returns The executable and arguments joined by single spaces.
 */
export function formatCommand(command: ServerCommand): string {
  return [command.executable, ...command.args]
    .map((part) => (/\s/.test(part) ? `"${part}"` : part))
    .join(' ');
}

/**
 * Builds the Server Command.
 *
 * The source is passed as a single argument without expansion because uvx
 * interprets it and no shell is involved.
 *
 * @param uvxPath Resolved uvx path.
 * @param serverSource Value of soase-validator.serverSource, possibly blank.
 * @param workspaceFolders File system paths of the open workspace folders.
 * @param homeDir The user's home directory.
 * @returns The executable, arguments and working directory for the Server.
 */
export function buildServerCommand(
  uvxPath: string,
  serverSource: string,
  workspaceFolders: readonly string[],
  homeDir: string,
): ServerCommand {
  const trimmed = serverSource.trim();
  const source = trimmed.length > 0 ? trimmed : DEFAULT_SERVER_SOURCE;
  return {
    executable: uvxPath,
    args: ['--from', source, 'soase-validator-lsp'],
    cwd: workspaceFolders[0] ?? homeDir,
  };
}
