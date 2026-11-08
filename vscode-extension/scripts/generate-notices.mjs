/**
 * Generates `THIRD_PARTY_NOTICES.txt` from the installed production dependencies.
 *
 * The file is build output (git-ignored) and is included in the `.vsix`
 * because the licenses of the bundled dependencies require their notices to
 * travel with the code. Texts are read from `node_modules`.
 *
 * Usage: `node scripts/generate-notices.mjs`
 */
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { listProductionDependencies } from './production-dependencies.mjs';

/** File name of the generated notices, relative to the project root. */
export const NOTICES_FILE = 'THIRD_PARTY_NOTICES.txt';

const RULE = '='.repeat(72);

/**
 * Builds the notices text.
 *
 * @param {string} root Absolute project root.
 * @returns {string} Notices text with one section per production dependency.
 * @throws {Error} When a production dependency ships no license file.
 */
export function buildNotices(root) {
  const header = [
    'Third-party notices for the SoaSE Validator extension',
    '',
    'The extension bundles the following packages. Each section gives the package',
    'name, version and the license text shipped with that package.',
    '',
  ].join('\n');
  const sections = listProductionDependencies(root).map((dependency) => {
    if (dependency.licenseFiles.length === 0) {
      throw new Error(`${dependency.name}@${dependency.version} ships no license file.`);
    }
    const texts = dependency.licenseFiles.map((file) => {
      const text = readFileSync(path.join(dependency.dir, file), 'utf8').trim();
      return `--- ${file} ---\n${text}`;
    });
    return [RULE, `${dependency.name} ${dependency.version}`, RULE, texts.join('\n\n')].join(
      '\n',
    );
  });
  return `${header}\n${sections.join('\n\n')}\n`;
}

/**
 * Writes the notices file into the project root.
 *
 * @param {string} root Absolute project root.
 * @returns {string} Absolute path of the written file.
 * @throws {Error} When a production dependency ships no license file.
 */
export function writeNotices(root) {
  const target = path.join(root, NOTICES_FILE);
  writeFileSync(target, buildNotices(root).replaceAll('\r\n', '\n'), 'utf8');
  return target;
}

if (process.argv[1] !== undefined && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
    console.log(`wrote ${path.relative(root, writeNotices(root))}`);
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
