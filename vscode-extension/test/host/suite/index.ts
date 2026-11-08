/**
 * Mocha entry point that `@vscode/test-electron` loads inside the extension host.
 *
 * Environment variables:
 * - `SOASE_HOST_TEST_DIR`: directory searched for `*.test.js`; defaults to the compiled
 *   `out/test/host` directory.
 * - `SOASE_HOST_NODE_REPORT`: file that receives `process.versions.node` as JSON, so the
 *   runner process can compare it with the expected embedded Node version.
 */

import { readdirSync, writeFileSync } from 'node:fs';
import * as path from 'node:path';

import Mocha from 'mocha';

/** Environment variable that overrides the directory searched for host test files. */
export const HOST_TEST_DIR_ENV = 'SOASE_HOST_TEST_DIR';

/** Environment variable naming the file that receives the Node version seen in the host. */
export const HOST_NODE_REPORT_ENV = 'SOASE_HOST_NODE_REPORT';

/**
 * Returns the directory searched for host test files.
 *
 * @param defaultDir Compiled `out/test/host` directory, used without an override.
 * @param env Process environment.
 * @returns The override from the environment, or the default directory.
 */
export function hostTestDir(defaultDir: string, env: NodeJS.ProcessEnv = process.env): string {
  const override = env[HOST_TEST_DIR_ENV];
  return override !== undefined && override !== '' ? override : defaultDir;
}

/**
 * Lists every `*.test.js` file below a directory, sorted for a stable run order.
 *
 * @param dir Directory to search recursively; a missing directory yields an empty list.
 * @returns Absolute paths of the test files.
 */
export function findTestFiles(dir: string): string[] {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return [];
  }
  const found: string[] = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      found.push(...findTestFiles(full));
    } else if (entry.name.endsWith('.test.js')) {
      found.push(full);
    }
  }
  return found.sort();
}

/**
 * Runs every compiled host test in the extension host.
 *
 * @returns A promise that resolves when all tests pass.
 * @throws Error when a test fails.
 */
export function run(): Promise<void> {
  const nodeVersion = process.versions.node;
  console.log(`Extension host Node.js version: ${nodeVersion}`);
  const reportPath = process.env[HOST_NODE_REPORT_ENV];
  if (reportPath !== undefined && reportPath !== '') {
    writeFileSync(reportPath, JSON.stringify({ node: nodeVersion }));
  }

  const mocha = new Mocha({ ui: 'bdd', color: true, timeout: 30_000 });
  for (const file of findTestFiles(hostTestDir(path.resolve(__dirname, '..')))) {
    mocha.addFile(file);
  }

  return new Promise<void>((resolve, reject) => {
    mocha.run((failures) => {
      if (failures > 0) {
        reject(new Error(`${failures} host test(s) failed.`));
      } else {
        resolve();
      }
    });
  });
}
