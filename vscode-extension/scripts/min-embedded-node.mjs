/**
 * Lowest Node.js version embedded in the minimum supported VS Code.
 *
 * The lint configuration derives its `eslint-plugin-n` version range from this
 * value, and the host tests compare it with `process.versions.node`.
 */
export const MIN_EMBEDDED_NODE = '24.21.0';
