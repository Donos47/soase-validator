/**
 * Production dependency discovery for the packaging scripts.
 *
 * The tree is resolved the way Node resolves `require`: a dependency is looked
 * up in `node_modules` next to the requiring package, then in each parent
 * directory up to the project root. Only `dependencies` are followed, so
 * development dependencies never appear.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';

/** Matches file names that carry a license or third-party notice text. */
export const LICENSE_FILE_PATTERN = /^(?:licen[cs]e|copying|notice|thirdpartynotices)/i;

/**
 * Reads and parses a JSON file.
 *
 * @param {string} file Absolute path of the file.
 * @returns {Record<string, any>} Parsed content.
 */
function readJson(file) {
  return JSON.parse(readFileSync(file, 'utf8'));
}

/**
 * Finds the directory that `require(name)` would use from a package directory.
 *
 * @param {string} name Dependency name.
 * @param {string} fromDir Directory of the requiring package.
 * @param {string} root Project root, the last directory searched.
 * @returns {string | null} Absolute directory of the dependency, or null.
 */
function locate(name, fromDir, root) {
  let dir = fromDir;
  for (;;) {
    const candidate = path.join(dir, 'node_modules', name);
    if (existsSync(path.join(candidate, 'package.json'))) {
      return candidate;
    }
    if (path.resolve(dir) === path.resolve(root)) {
      return null;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      return null;
    }
    dir = parent;
  }
}

/**
 * Lists the license and notice files directly inside a package directory.
 *
 * @param {string} dir Absolute package directory.
 * @returns {string[]} File names, sorted.
 */
function licenseFilesIn(dir) {
  return readdirSync(dir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && LICENSE_FILE_PATTERN.test(entry.name))
    .map((entry) => entry.name)
    .sort();
}

/**
 * Resolves the production dependency tree of the project.
 *
 * @param {string} root Absolute project root containing `package.json`.
 * @returns {{ name: string, version: string, dir: string, relativeDir: string,
 *   licenseFiles: string[] }[]} One entry per installed package, sorted by
 *   directory.
 * @throws {Error} When a declared production dependency is not installed.
 */
export function listProductionDependencies(root) {
  const found = new Map();
  const pending = [{ manifest: readJson(path.join(root, 'package.json')), dir: root }];
  while (pending.length > 0) {
    const { manifest, dir } = pending.pop();
    const names = Object.keys({
      ...manifest.dependencies,
      ...manifest.optionalDependencies,
    });
    for (const name of names) {
      const located = locate(name, dir, root);
      if (located === null) {
        if (manifest.optionalDependencies?.[name] !== undefined) {
          continue;
        }
        throw new Error(`Production dependency ${name} is not installed. Run npm ci.`);
      }
      if (found.has(located)) {
        continue;
      }
      const dependencyManifest = readJson(path.join(located, 'package.json'));
      found.set(located, {
        name: dependencyManifest.name ?? name,
        version: dependencyManifest.version ?? 'unknown',
        dir: located,
        relativeDir: path.relative(root, located).split(path.sep).join('/'),
        licenseFiles: licenseFilesIn(located),
      });
      pending.push({ manifest: dependencyManifest, dir: located });
    }
  }
  return [...found.values()].sort((a, b) => a.relativeDir.localeCompare(b.relativeDir));
}
