/** Environment map as the launcher sees it. */
export type EnvMap = Readonly<Record<string, string | undefined>>;

/**
 * Looks up an environment variable.
 *
 * Windows variable names are case-insensitive, and a copied environment object
 * keeps whatever case the host reported, so the match must ignore case there.
 *
 * @param env Environment map.
 * @param name Variable name.
 * @param caseInsensitive True on Windows.
 * @returns The value, or undefined when the variable is not set.
 */
export function lookupEnv(
  env: EnvMap,
  name: string,
  caseInsensitive: boolean,
): string | undefined {
  if (!caseInsensitive) {
    return env[name];
  }
  const wanted = name.toLowerCase();
  for (const key of Object.keys(env)) {
    if (key.toLowerCase() === wanted) {
      return env[key];
    }
  }
  return undefined;
}

const WINDOWS_REFERENCE = /%([^%]+)%/g;
const POSIX_REFERENCE = /\$(?:\{([^}]+)\}|([A-Za-z_][A-Za-z0-9_]*))/g;

/**
 * Expands a leading `~` and environment variable references.
 *
 * A reference to a variable that is not set stays in the text unchanged, so a
 * wrong path is reported as the user wrote it. Expansion runs once; values
 * that themselves contain references are not expanded again. A string with
 * neither a leading `~` nor a reference is returned unchanged.
 *
 * @param input Path text, for example the `uvPath` setting.
 * @param env Environment map.
 * @param homeDir Home directory that replaces a leading `~`.
 * @param isWindows True to expand `%VAR%`; false to expand `$VAR` and `${VAR}`.
 * @returns The expanded text.
 */
export function expandPath(
  input: string,
  env: EnvMap,
  homeDir: string,
  isWindows: boolean,
): string {
  let text = input;
  if (text === '~' || text.startsWith('~/') || (isWindows && text.startsWith('~\\'))) {
    text = homeDir + text.slice(1);
  }
  if (isWindows) {
    return text.replace(WINDOWS_REFERENCE, (match: string, name: string) => {
      return lookupEnv(env, name, true) ?? match;
    });
  }
  return text.replace(
    POSIX_REFERENCE,
    (match: string, braced: string | undefined, bare: string | undefined) => {
      return lookupEnv(env, braced ?? bare ?? '', false) ?? match;
    },
  );
}
