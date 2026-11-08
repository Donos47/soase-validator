/**
 * Lowest Node.js version embedded in the supported hosts (VS Code at the `engines.vscode` floor, current VS Code and Kiro).
 *
 * The lint configuration derives its `eslint-plugin-n` version range from this
 * value, and the host tests compare it with `process.versions.node`.
 */
export const MIN_EMBEDDED_NODE = '24.18.0';
