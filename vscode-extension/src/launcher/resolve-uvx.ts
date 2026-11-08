import { expandPath, lookupEnv } from './expand-path';

/** Platform values the resolver distinguishes. */
export type Platform = 'win32' | 'darwin' | 'linux';

/** Side-effect ports for the resolver. */
export interface ResolverPorts {
  readonly platform: Platform;
  readonly env: Readonly<Record<string, string | undefined>>;
  readonly homeDir: string;
  /** True when the path names an existing executable regular file. */
  isExecutableFile(path: string): boolean;
  joinPath(...parts: string[]): string;
}

/** Outcome of resolving uvx. */
export type UvxResolution =
  | {
    readonly found: true;
    readonly path: string;
    readonly source: 'uvPath' | 'path' | 'installer' | 'cargo';
  }
  | {
    readonly found: false;
    readonly searched: readonly string[];
    readonly reason: 'uvPath-invalid' | 'not-found';
  };

/**
 * Splits a `PATH` value into directories.
 *
 * Empty entries are dropped because they have no stable meaning across shells.
 * Windows allows a directory to be wrapped in quotes.
 *
 * @param value Raw `PATH` text.
 * @param isWindows True to split on `;` and strip quotes.
 * @returns Directory entries in order.
 */
function splitPath(value: string, isWindows: boolean): string[] {
  const parts = value.split(isWindows ? ';' : ':');
  const entries = isWindows
    ? parts.map((part) => part.trim().replace(/^"(.*)"$/, '$1'))
    : parts;
  return entries.filter((entry) => entry.length > 0);
}

/**
 * Resolves the uvx executable.
 *
 * @param uvPath Value of soase-validator.uvPath, possibly blank.
 * @param ports Injected environment.
 * @returns The first existing candidate, or the list of probed candidates.
 */
export function resolveUvx(uvPath: string, ports: ResolverPorts): UvxResolution {
  const isWindows = ports.platform === 'win32';
  const exeName = isWindows ? 'uvx.exe' : 'uvx';
  const searched: string[] = [];

  if (uvPath.trim().length > 0) {
    const expanded = expandPath(uvPath.trim(), ports.env, ports.homeDir, isWindows);
    if (ports.isExecutableFile(expanded)) {
      return { found: true, path: expanded, source: 'uvPath' };
    }
    return { found: false, searched: [expanded], reason: 'uvPath-invalid' };
  }

  const probe = (directory: string): string | undefined => {
    const candidate = ports.joinPath(directory, exeName);
    searched.push(candidate);
    return ports.isExecutableFile(candidate) ? candidate : undefined;
  };

  const pathValue = lookupEnv(ports.env, 'PATH', isWindows) ?? '';
  for (const directory of splitPath(pathValue, isWindows)) {
    const hit = probe(directory);
    if (hit !== undefined) {
      return { found: true, path: hit, source: 'path' };
    }
  }

  const installerHit = probe(ports.joinPath(ports.homeDir, '.local', 'bin'));
  if (installerHit !== undefined) {
    return { found: true, path: installerHit, source: 'installer' };
  }

  const cargoEnv = lookupEnv(ports.env, 'CARGO_HOME', isWindows);
  const cargoHome =
    cargoEnv !== undefined && cargoEnv.length > 0
      ? cargoEnv
      : ports.joinPath(ports.homeDir, '.cargo');
  const cargoHit = probe(ports.joinPath(cargoHome, 'bin'));
  if (cargoHit !== undefined) {
    return { found: true, path: cargoHit, source: 'cargo' };
  }

  return { found: false, searched, reason: 'not-found' };
}
