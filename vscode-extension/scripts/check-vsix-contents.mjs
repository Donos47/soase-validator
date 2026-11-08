/**
 * Checks the file list that `vsce ls` prints against the packaging rules.
 *
 * The list is read from standard input, one path per line, so the check runs
 * on any listing: `node node_modules/@vscode/vsce/vsce ls | node scripts/check-vsix-contents.mjs`.
 * `scripts/package.mjs` pipes the same output into it. Exit code 0 means the
 * listing is acceptable; exit code 1 prints one line per violation.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { NOTICES_FILE } from './generate-notices.mjs';
import { listProductionDependencies } from './production-dependencies.mjs';

/** The only first-party JSON data file the package may ship, matched by exact path. */
const GRAMMAR_FILE = 'syntaxes/soase.tmLanguage.json';

/** Files every package must contain. */
const REQUIRED_FILES = [
  'package.json',
  'README.md',
  'LICENSE',
  'out/src/extension.js',
  NOTICES_FILE,
  GRAMMAR_FILE,
];

/** Game file extensions, which the package never ships. */
const GAME_FILE_EXTENSIONS = new Set([
  '.entity',
  '.galaxy',
  '.brushes',
  '.sounddata',
  '.str',
  '.constants',
  '.galaxyscenariodef',
  '.particle',
  '.explosiondata',
  '.manifest',
  '.mesh',
  '.dds',
  '.ogg',
]);

/** Top-level paths that hold Python source, tests, evidence or specs. */
const FORBIDDEN_PREFIXES = [
  ['src/soase_validator/', 'Python package source'],
  ['reference/', 'reference material'],
  ['tests/', 'Python tests'],
  ['.kiro/', 'spec files'],
];

/** Executable names of the `uv` tool. */
const UV_BINARIES = new Set(['uv', 'uvx', 'uv.exe', 'uvx.exe', 'uvw.exe']);

/**
 * Normalises a listing path to forward slashes without a leading `./`.
 *
 * @param {string} line One line of `vsce ls` output.
 * @returns {string} Normalised path.
 */
function normalise(line) {
  return line.trim().replaceAll('\\', '/').replace(/^\.\//, '');
}

/**
 * Tells whether a path is a manifest of the extension or of an installed package.
 *
 * @param {string} file Normalised path.
 * @returns {boolean} True for `package.json` files that are not Definitions.
 */
function isPackageManifest(file) {
  return file === 'package.json' || file.endsWith('/package.json');
}

/**
 * Finds the reasons a listed path must not be packaged.
 *
 * @param {string} file Normalised path.
 * @returns {string[]} Violation messages, empty when the path is allowed.
 */
function forbiddenReasons(file) {
  const reasons = [];
  for (const [prefix, what] of FORBIDDEN_PREFIXES) {
    if (file.startsWith(prefix)) {
      reasons.push(`${what} must not be packaged: ${file}`);
    }
  }
  const base = file.slice(file.lastIndexOf('/') + 1);
  const extension = path.posix.extname(base).toLowerCase();
  if (UV_BINARIES.has(base.toLowerCase())) {
    reasons.push(`uv binary must not be packaged: ${file}`);
  }
  // Dependencies ship their own JSON (schemas, manifests); only first-party JSON can be a Definition.
  const firstParty = !file.startsWith('node_modules/');
  if (firstParty && extension === '.json' && !isPackageManifest(file) && file !== GRAMMAR_FILE) {
    reasons.push(`Definition or data JSON must not be packaged: ${file}`);
  }
  if (extension === '.py' || extension === '.pyc') {
    reasons.push(`Python source must not be packaged: ${file}`);
  }
  if (GAME_FILE_EXTENSIONS.has(extension)) {
    reasons.push(`game file must not be packaged: ${file}`);
  }
  if (firstParty && file.split('/').includes('definitions')) {
    reasons.push(`Definitions must not be packaged: ${file}`);
  }
  return reasons;
}

/**
 * Checks a package listing.
 *
 * @param {string[]} lines Lines of `vsce ls` output.
 * @param {string} root Absolute project root, used to find the production
 *   dependencies and their license files.
 * @returns {string[]} One message per violation, empty when the listing is valid.
 * @throws {Error} When a production dependency is not installed.
 */
export function checkContents(lines, root) {
  const files = lines.map(normalise).filter((line) => line.length > 0);
  const listed = new Set(files);
  const violations = [];

  for (const required of REQUIRED_FILES) {
    if (!listed.has(required)) {
      violations.push(`missing from package: ${required}`);
    }
  }

  for (const dependency of listProductionDependencies(root)) {
    if (dependency.licenseFiles.length === 0) {
      violations.push(`${dependency.name}@${dependency.version} ships no license file`);
    }
    for (const file of dependency.licenseFiles) {
      const expected = `${dependency.relativeDir}/${file}`;
      if (!listed.has(expected)) {
        violations.push(`missing from package: ${expected}`);
      }
    }
  }

  for (const file of files) {
    violations.push(...forbiddenReasons(file));
  }
  return violations;
}

if (process.argv[1] !== undefined && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  try {
    const input = readFileSync(0, 'utf8');
    const violations = checkContents(input.split(/\r?\n/), root);
    for (const violation of violations) {
      console.error(violation);
    }
    process.exitCode = violations.length === 0 ? 0 : 1;
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
