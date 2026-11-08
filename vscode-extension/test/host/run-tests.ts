/**
 * Launches the host mocha suite in VS Code through `@vscode/test-electron`.
 *
 * VS Code is downloaded by `@vscode/test-electron` and started directly instead of through
 * its `runTests` helper, because that helper always passes `--disable-workspace-trust` and
 * the host tests exercise trust behaviour. The fixture workspace is opened in a clean
 * profile with workspace trust left enabled, so the tests decide when trust is granted.
 *
 * Environment variables:
 * - `SOASE_HOST_VSCODE_VERSION`: run only this VS Code version (`1.141.0`, `stable`, ...).
 *   By default the `engines.vscode` floor and `stable` run one after the other.
 * - `SOASE_HOST_TEST_DIR`: directory searched for `*.test.js`; defaults to `out/test/host`.
 *
 * Exit codes: 0 when every selected run passes or no host test files exist, 1 otherwise.
 */

import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { pathToFileURL } from 'node:url';

import { downloadAndUnzipVSCode } from '@vscode/test-electron';

import {
  findTestFiles,
  HOST_NODE_REPORT_ENV,
  HOST_TEST_DIR_ENV,
  hostTestDir,
} from './suite/index';

/** Environment variable that selects a single VS Code version. */
const VERSION_ENV = 'SOASE_HOST_VSCODE_VERSION';

/** Version alias for the latest stable VS Code release. */
const STABLE = 'stable';

/** Upper bound for one VS Code run, in milliseconds. */
const RUN_TIMEOUT_MS = 10 * 60 * 1000;

/** Root of the extension project (`out/test/host` is three levels below it). */
const EXTENSION_ROOT = path.resolve(__dirname, '..', '..', '..');

const FIXTURE_WORKSPACE = path.join(EXTENSION_ROOT, 'test', 'fixtures', 'mod');

/**
 * Returns the directory searched for host test files.
 *
 * @returns The `SOASE_HOST_TEST_DIR` override, or the compiled host test directory.
 */
function testDir(): string {
  return hostTestDir(__dirname);
}

/** Outcome of one VS Code run. */
interface RunResult {
  readonly version: string;
  readonly passed: boolean;
}

/**
 * Reads the pinned VS Code version from `engines.vscode`.
 *
 * @returns The version without its range prefix.
 * @throws Error when `engines.vscode` is missing.
 */
function pinnedVersion(): string {
  const manifest = JSON.parse(
    readFileSync(path.join(EXTENSION_ROOT, 'package.json'), 'utf8'),
  ) as { engines?: { vscode?: string } };
  const range = manifest.engines?.vscode;
  if (range === undefined) {
    throw new Error('package.json has no engines.vscode.');
  }
  return range.replace(/^[^\d]*/, '');
}

/**
 * Loads `MIN_EMBEDDED_NODE` from the ESM script that the lint configuration also uses.
 *
 * The script lives outside `rootDir`, so it is imported at runtime instead of compiled
 * or copied, which keeps one definition of the constant.
 *
 * @returns The minimum embedded Node.js version, for example `24.21.0`.
 */
async function loadMinEmbeddedNode(): Promise<string> {
  const url = pathToFileURL(path.join(EXTENSION_ROOT, 'scripts', 'min-embedded-node.mjs')).href;
  const loaded = (await import(url)) as { MIN_EMBEDDED_NODE: string };
  return loaded.MIN_EMBEDDED_NODE;
}

/**
 * Keeps the major and minor parts of a Node.js version.
 *
 * @param version Version such as `24.21.0`.
 * @returns The `major.minor` prefix.
 */
function majorMinor(version: string): string {
  return version.split('.').slice(0, 2).join('.');
}

/**
 * Starts VS Code with the host suite and waits for it to exit.
 *
 * @param executable Path of the VS Code executable.
 * @param args Command line arguments.
 * @param env Environment of the VS Code process.
 * @returns The exit code, or null when the process was killed.
 */
function launch(executable: string, args: string[], env: NodeJS.ProcessEnv): Promise<number | null> {
  return new Promise<number | null>((resolve, reject) => {
    const child = spawn(executable, args, { env, stdio: 'inherit' });
    const timer = setTimeout(() => {
      console.error(`VS Code did not exit within ${RUN_TIMEOUT_MS / 1000} seconds; killing it.`);
      child.kill();
    }, RUN_TIMEOUT_MS);
    child.on('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve(code);
    });
  });
}

/**
 * Runs the host suite once on a VS Code version with a throwaway profile.
 *
 * @param version VS Code version or `stable`.
 * @param pinned The `engines.vscode` floor, whose embedded Node version is known.
 * @param minNode Expected embedded Node.js version of the pinned VS Code.
 * @returns Whether the run passed.
 */
async function runOnVersion(version: string, pinned: string, minNode: string): Promise<RunResult> {
  console.log(`\n=== Host tests on VS Code ${version} ===`);
  const scratch = mkdtempSync(path.join(tmpdir(), 'soase-host-'));
  const reportFile = path.join(scratch, 'node-report.json');
  try {
    const executable = await downloadAndUnzipVSCode({
      version,
      cachePath: path.join(EXTENSION_ROOT, '.vscode-test'),
    });
    const args = [
      FIXTURE_WORKSPACE,
      '--no-sandbox',
      '--disable-gpu-sandbox',
      '--disable-updates',
      '--skip-welcome',
      '--skip-release-notes',
      '--no-cached-data',
      '--disable-extensions',
      `--user-data-dir=${path.join(scratch, 'user-data')}`,
      `--extensions-dir=${path.join(scratch, 'extensions')}`,
      `--extensionDevelopmentPath=${EXTENSION_ROOT}`,
      `--extensionTestsPath=${path.join(EXTENSION_ROOT, 'out', 'test', 'host', 'suite', 'index.js')}`,
    ];
    // A parent shell started from VS Code can leak this variable, which turns Electron into plain Node.
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      [HOST_NODE_REPORT_ENV]: reportFile,
      [HOST_TEST_DIR_ENV]: testDir(),
    };
    delete env['ELECTRON_RUN_AS_NODE'];

    const code = await launch(executable, args, env);
    if (code !== 0) {
      console.error(`Host tests failed on VS Code ${version} (exit code ${String(code)}).`);
      return { version, passed: false };
    }

    const observed = (JSON.parse(readFileSync(reportFile, 'utf8')) as { node: string }).node;
    if (version !== pinned) {
      console.log(`VS Code ${version} embeds Node.js ${observed}.`);
      return { version, passed: true };
    }
    if (majorMinor(observed) !== majorMinor(minNode)) {
      console.error(
        `VS Code ${version} embeds Node.js ${observed}, expected ${majorMinor(minNode)}.x. `
        + 'Update MIN_EMBEDDED_NODE in scripts/min-embedded-node.mjs.',
      );
      return { version, passed: false };
    }
    console.log(`VS Code ${version} embeds Node.js ${observed}, as expected (${minNode}).`);
    return { version, passed: true };
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
}

/**
 * Entry point: selects versions, runs them in order and sets the exit code.
 *
 * @returns A promise that resolves when all runs are done.
 */
async function main(): Promise<void> {
  if (findTestFiles(testDir()).length === 0) {
    console.log('No host test files found; skipping the extension host run.');
    return;
  }
  const pinned = pinnedVersion();
  const minNode = await loadMinEmbeddedNode();
  const selected = process.env[VERSION_ENV];
  const versions = selected !== undefined && selected !== '' ? [selected] : [pinned, STABLE];

  const results: RunResult[] = [];
  for (const version of versions) {
    results.push(await runOnVersion(version, pinned, minNode));
  }
  const failed = results.filter((result) => !result.passed);
  if (failed.length > 0) {
    console.error(`Host tests failed on: ${failed.map((result) => result.version).join(', ')}.`);
    process.exitCode = 1;
  } else {
    console.log(`Host tests passed on: ${results.map((result) => result.version).join(', ')}.`);
  }
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
