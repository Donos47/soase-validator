import { builtinModules } from 'node:module';

import nodePlugin from 'eslint-plugin-n';
import tseslint from 'typescript-eslint';

import { MIN_EMBEDDED_NODE } from './scripts/min-embedded-node.mjs';

/** Node built-ins that code in `src/` may import. */
const ALLOWED_NODE_MODULES = ['child_process', 'fs', 'path', 'os', 'process'];

/** Network modules, named explicitly so the message is specific. */
const NETWORK_MODULES = ['http', 'https', 'net', 'tls', 'dgram'];

const NETWORK_MESSAGE = 'The extension makes no network connections.';

const NODE_MODULE_MESSAGE =
  'Only child_process, fs, path, os and process may be imported from Node.';

const CHILD_PROCESS_MESSAGE =
  'child_process is imported only by src/client/spawn-server.ts and the exec adapter in '
  + 'src/launcher/uv-version.ts.';

const VSCODE_MESSAGE =
  'This module is part of the pure core and must not import vscode.';

const STD_STREAM_MESSAGE =
  'stdout and stderr belong to the protocol and the host; log through the output channel.';

/** Version range of the Node embedded in the minimum supported VS Code. */
const EMBEDDED_NODE_RANGE = `>=${MIN_EMBEDDED_NODE}`;

/** Escapes a module name for use inside a regular expression. */
function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
}

const allowedAlternation = ALLOWED_NODE_MODULES.map(escapeRegex).join('|');

const forbiddenBareBuiltins = builtinModules
  .filter((name) => !ALLOWED_NODE_MODULES.includes(name))
  .map(escapeRegex)
  .join('|');

/**
 * Lists the module specifiers a group of files in `src/` may not import.
 *
 * @param {{ childProcess: boolean, vscode: boolean }} flags Which extra
 *   restrictions apply to the group.
 * @returns {{ regex: string, message: string }[]} Specifier patterns.
 */
function forbiddenSpecifiers({ childProcess, vscode }) {
  const specifiers = [
    {
      regex: `^(?:node:)?(?:${NETWORK_MODULES.join('|')})(?:/.*)?$`,
      message: NETWORK_MESSAGE,
    },
    {
      regex: `^node:(?!(?:${allowedAlternation})$)`,
      message: NODE_MODULE_MESSAGE,
    },
    {
      regex: `^(?:${forbiddenBareBuiltins})$`,
      message: NODE_MODULE_MESSAGE,
    },
  ];
  if (childProcess) {
    specifiers.push({
      regex: '^(?:node:)?child_process$',
      message: CHILD_PROCESS_MESSAGE,
    });
  }
  if (vscode) {
    specifiers.push({ regex: '^vscode$', message: VSCODE_MESSAGE });
  }
  return specifiers;
}

/**
 * Builds the `no-restricted-imports` options for one group of files in `src/`.
 *
 * @param {{ childProcess: boolean, vscode: boolean }} flags Restriction flags.
 * @returns {object} Options object for `no-restricted-imports`.
 */
function restrictedImports(flags) {
  return {
    paths: [
      { name: 'process', importNames: ['stdout', 'stderr'], message: STD_STREAM_MESSAGE },
      { name: 'node:process', importNames: ['stdout', 'stderr'], message: STD_STREAM_MESSAGE },
    ],
    patterns: forbiddenSpecifiers(flags),
  };
}

/**
 * Builds the `no-restricted-syntax` entries for one group of files in `src/`.
 *
 * `no-restricted-imports` does not inspect `import()` expressions, so the same
 * specifier patterns are applied to literal `import()` sources here. The
 * esquery regex syntax cannot contain `/`, so a slash is matched by `.`.
 *
 * @param {{ childProcess: boolean, vscode: boolean }} flags Restriction flags.
 * @returns {object[]} Entries for `no-restricted-syntax`.
 */
function restrictedSyntax(flags) {
  const dynamicImports = forbiddenSpecifiers(flags).map(({ regex, message }) => ({
    selector:
      'ImportExpression > Literal.source'
      + `[value=/${regex.replaceAll('\\/', '.').replaceAll('/', '.')}/]`,
    message,
  }));
  return [
    {
      selector:
        'MemberExpression[object.type="MemberExpression"][object.property.name="process"]'
        + '[property.name=/^(?:stdout|stderr)$/]',
      message: STD_STREAM_MESSAGE,
    },
    ...dynamicImports,
  ];
}

/**
 * Builds a flat config object that sets the import restrictions for files.
 *
 * @param {string[]} files Glob patterns of the files the object covers.
 * @param {{ childProcess: boolean, vscode: boolean }} flags Restriction flags.
 * @returns {object} Flat config object.
 */
function importRestrictionsFor(files, flags) {
  return {
    files,
    rules: {
      'no-restricted-imports': ['error', restrictedImports(flags)],
      'no-restricted-syntax': ['error', ...restrictedSyntax(flags)],
    },
  };
}

export default tseslint.config(
  { ignores: ['out/**', 'dist/**', 'node_modules/**', '.vscode-test/**'] },
  ...tseslint.configs.recommendedTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
  {
    files: ['**/*.mjs'],
    extends: [tseslint.configs.disableTypeChecked],
  },
  {
    files: ['src/**/*.ts'],
    plugins: { n: nodePlugin },
    rules: {
      '@typescript-eslint/no-require-imports': 'error',
      'no-console': 'error',
      'no-restricted-properties': [
        'error',
        { object: 'process', property: 'stdout', message: STD_STREAM_MESSAGE },
        { object: 'process', property: 'stderr', message: STD_STREAM_MESSAGE },
      ],
      'n/no-unsupported-features/node-builtins': ['error', { version: EMBEDDED_NODE_RANGE }],
      'n/no-unsupported-features/es-builtins': ['error', { version: EMBEDDED_NODE_RANGE }],
      'n/no-unsupported-features/es-syntax': ['error', { version: EMBEDDED_NODE_RANGE }],
    },
  },
  importRestrictionsFor(['src/**/*.ts'], { childProcess: true, vscode: false }),
  importRestrictionsFor(
    [
      'src/launcher/**/*.ts',
      'src/settings/**/*.ts',
      'src/lifecycle/**/*.ts',
      'src/format/**/*.ts',
    ],
    { childProcess: true, vscode: true },
  ),
  importRestrictionsFor(['src/settings/vscode-config-reader.ts'], {
    childProcess: true,
    vscode: false,
  }),
  importRestrictionsFor(['src/client/spawn-server.ts'], {
    childProcess: false,
    vscode: false,
  }),
  importRestrictionsFor(['src/launcher/uv-version.ts'], {
    childProcess: false,
    vscode: true,
  }),
);
