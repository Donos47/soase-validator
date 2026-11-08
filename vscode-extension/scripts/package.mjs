/**
 * Builds the `.vsix` file.
 *
 * Steps, in order: clean `out/`, `compile`, `lint`, `contents`, `package`.
 * Child processes run through `process.execPath` with the tool's JavaScript
 * entry file and no shell, so the script behaves the same on Windows, macOS
 * and Linux. A failing step prints `package failed at step: <name>`, removes
 * `dist/.build/` and any `.vsix` this run wrote, and exits non-zero.
 *
 * Usage: `npm run package`
 */
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, renameSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { checkContents } from './check-vsix-contents.mjs';
import { writeNotices } from './generate-notices.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT_DIR = path.join(ROOT, 'out');
const DIST_DIR = path.join(ROOT, 'dist');
const BUILD_DIR = path.join(DIST_DIR, '.build');
const require = createRequire(import.meta.url);

/** Raised by a step to stop the build; carries the step name. */
class StepError extends Error {
  /**
   * @param {string} step Name printed in the failure line.
   * @param {string} detail Human-readable cause.
   */
  constructor(step, detail) {
    super(detail);
    this.step = step;
  }
}

/**
 * Runs one named step and reports any failure under that name.
 *
 * @param {string} name Step name printed in the failure line.
 * @param {() => void} action Step body.
 * @throws {StepError} When the body throws.
 */
function step(name, action) {
  try {
    action();
  } catch (error) {
    if (error instanceof StepError) {
      throw error;
    }
    throw new StepError(name, error instanceof Error ? error.message : String(error));
  }
}

/** Paths of `.vsix` files written by this run, removed on failure. */
const writtenFiles = [];

/**
 * Resolves the JavaScript entry file of a dependency's command line tool.
 *
 * @param {string} packageName Package that declares a `bin` entry.
 * @param {string} binName Key in the package's `bin` map.
 * @returns {string} Absolute path of the entry file.
 */
function binEntry(packageName, binName) {
  const manifestPath = require.resolve(`${packageName}/package.json`);
  const { bin } = JSON.parse(readFileSync(manifestPath, 'utf8'));
  const relative = typeof bin === 'string' ? bin : bin[binName];
  return path.resolve(path.dirname(manifestPath), relative);
}

/**
 * Runs a Node script without a shell.
 *
 * @param {string} step Step name used when the script fails.
 * @param {string} script Absolute path of the script.
 * @param {string[]} args Script arguments.
 * @param {{ capture?: boolean }} [options] Capture stdout instead of inheriting it.
 * @returns {string} Captured stdout, empty when not captured.
 * @throws {StepError} When the script cannot start or exits non-zero.
 */
function runNode(step, script, args, options = {}) {
  const result = spawnSync(process.execPath, [script, ...args], {
    cwd: ROOT,
    shell: false,
    encoding: 'utf8',
    stdio: options.capture ? ['ignore', 'pipe', 'inherit'] : 'inherit',
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) {
    throw new StepError(step, result.error.message);
  }
  if (result.status !== 0) {
    throw new StepError(step, `exit code ${String(result.status)}`);
  }
  return result.stdout ?? '';
}

/**
 * Removes the build directory and every `.vsix` this run wrote.
 */
function cleanupAfterFailure() {
  rmSync(BUILD_DIR, { recursive: true, force: true });
  for (const file of writtenFiles) {
    rmSync(file, { force: true });
  }
}

/**
 * Runs the packaging steps.
 *
 * @throws {StepError} When a step fails.
 */
function main() {
  const { name, version } = JSON.parse(readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
  const vsixName = `${name}-${version}.vsix`;
  const vsce = binEntry('@vscode/vsce', 'vsce');

  // Only generated output is cleaned; a stale build directory could otherwise leak into dist/.
  step('compile', () => {
    rmSync(OUT_DIR, { recursive: true, force: true });
    rmSync(BUILD_DIR, { recursive: true, force: true });
    runNode('compile', binEntry('typescript', 'tsc'), ['-p', './']);
  });
  step('lint', () => {
    runNode('lint', binEntry('eslint', 'eslint'), ['.']);
  });

  step('contents', () => {
    writeNotices(ROOT);
    const listing = runNode('contents', vsce, ['ls'], { capture: true });
    const violations = checkContents(listing.split(/\r?\n/), ROOT);
    for (const violation of violations) {
      console.error(violation);
    }
    if (violations.length > 0) {
      throw new Error(`${String(violations.length)} violation(s)`);
    }
  });

  step('package', () => {
    mkdirSync(BUILD_DIR, { recursive: true });
    const built = path.join(BUILD_DIR, vsixName);
    writtenFiles.push(built);
    runNode('package', vsce, ['package', '--out', built]);
    if (!existsSync(built)) {
      throw new Error(`${vsixName} was not created`);
    }
    const target = path.join(DIST_DIR, vsixName);
    writtenFiles.push(target);
    renameSync(built, target);
    rmSync(BUILD_DIR, { recursive: true, force: true });
    console.log(`created ${path.relative(ROOT, target)}`);
  });
}

try {
  main();
} catch (error) {
  cleanupAfterFailure();
  const failed = error instanceof StepError ? error : new StepError('package', String(error));
  console.error(`package failed at step: ${failed.step}`);
  console.error(failed.message);
  process.exitCode = 1;
}
