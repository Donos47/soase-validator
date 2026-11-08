/** Value types a Server Setting can declare. */
export type SettingType =
  | 'string'
  | 'boolean'
  | 'string[]'
  | 'object<string,string>';

/** One Server Setting. */
export interface ServerSettingDef {
  /** The `soase.json` key, dotted for nested keys, for example `numeric.integerStrict`. */
  readonly key: string;
  /** The value type the setting declares. */
  readonly type: SettingType;
}

/** The Server Settings keys, shared by the payload builder and the manifest. */
export const SERVER_SETTINGS: readonly ServerSettingDef[] = [
  { key: 'gameVersion', type: 'string' },
  { key: 'referenceRoots', type: 'object<string,string>' },
  { key: 'modRoots', type: 'string[]' },
  { key: 'layers', type: 'string[]' },
  { key: 'language', type: 'string' },
  { key: 'disabledCodes', type: 'string[]' },
  { key: 'numeric.integerStrict', type: 'boolean' },
  { key: 'numeric.decimalAllowInteger', type: 'boolean' },
  { key: 'manifest.unreferencedSeverity', type: 'string' },
  { key: 'manifest.exemptUnlisted', type: 'string[]' },
  { key: 'manifest.exemptUnreferenced', type: 'string[]' },
  { key: 'reportOverrides', type: 'boolean' },
  { key: 'suppressLimitedReferenceNotice', type: 'boolean' },
];
