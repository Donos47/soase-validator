import { SERVER_SETTINGS, type SettingType } from './server-settings-schema';

/** Values of one setting at each VS Code scope; `undefined` means not set there. */
export interface ScopedValue {
  /** Value in the user settings. */
  readonly globalValue?: unknown;
  /** Value in the workspace settings. */
  readonly workspaceValue?: unknown;
  /** Value in the workspace folder settings. */
  readonly workspaceFolderValue?: unknown;
}

/** Reads the scoped values of one setting key. */
export type ConfigReader = (key: string) => ScopedValue;

/** Result of building the payload. */
export interface PayloadResult {
  /** Always exactly one top-level member, `soase-validator`. */
  readonly payload: { readonly 'soase-validator': Readonly<Record<string, unknown>> };
  /** One entry per key whose set value has the wrong type. */
  readonly invalid: readonly { readonly key: string; readonly value: unknown }[];
}

const SECTION = 'soase-validator';

// Own-property assignment keeps these names from reaching the prototype chain.
function setOwn(target: Record<string, unknown>, name: string, value: unknown): void {
  Object.defineProperty(target, name, {
    value,
    enumerable: true,
    writable: true,
    configurable: true,
  });
}

function pickScope(scoped: ScopedValue): unknown {
  if (scoped.workspaceFolderValue !== undefined) {
    return scoped.workspaceFolderValue;
  }
  if (scoped.workspaceValue !== undefined) {
    return scoped.workspaceValue;
  }
  return scoped.globalValue;
}

function matchesType(value: unknown, type: SettingType): boolean {
  switch (type) {
    case 'string':
      return typeof value === 'string';
    case 'boolean':
      return typeof value === 'boolean';
    case 'string[]':
      return Array.isArray(value) && value.every((item) => typeof item === 'string');
    case 'object<string,string>':
      return (
        typeof value === 'object' &&
        value !== null &&
        !Array.isArray(value) &&
        Object.values(value).every((item) => typeof item === 'string')
      );
  }
}

function writeNested(root: Record<string, unknown>, dotted: string, value: unknown): void {
  const parts = dotted.split('.');
  let node = root;
  for (const part of parts.slice(0, -1)) {
    const existing: unknown = Object.hasOwn(node, part) ? node[part] : undefined;
    if (typeof existing === 'object' && existing !== null && !Array.isArray(existing)) {
      node = existing as Record<string, unknown>;
    } else {
      const child: Record<string, unknown> = {};
      setOwn(node, part, child);
      node = child;
    }
  }
  setOwn(node, parts[parts.length - 1] ?? dotted, value);
}

/**
 * Builds the settings payload for initializationOptions and didChangeConfiguration.
 *
 * The most specific scope that is set supplies each value; scopes are never
 * merged. Only the shape of a value is checked, never its meaning.
 *
 * @param read Injected configuration reader.
 * @returns The payload under the `soase-validator` section and the keys whose
 *   set values had the wrong type.
 */
export function buildPayload(read: ConfigReader): PayloadResult {
  const section: Record<string, unknown> = {};
  const invalid: { key: string; value: unknown }[] = [];

  for (const def of SERVER_SETTINGS) {
    const value = pickScope(read(def.key));
    if (value === undefined) {
      continue;
    }
    if (!matchesType(value, def.type)) {
      invalid.push({ key: def.key, value });
      continue;
    }
    writeNested(section, def.key, value);
  }

  const payload: Record<string, unknown> = {};
  setOwn(payload, SECTION, section);
  return {
    payload: payload as unknown as PayloadResult['payload'],
    invalid,
  };
}
