/**
 * Maps the `trace.server` setting to the language client's `Trace` values.
 */

import type { Trace } from 'vscode-languageclient/node';

import type { TraceLevel } from '../settings/extension-settings';

/**
 * The library's `Trace` enum object.
 *
 * It is passed in because only `client-factory.ts` loads the library, and it
 * does so lazily on the first start.
 */
export type TraceValues = typeof Trace;

/**
 * Maps a trace setting to the library trace value.
 *
 * `messages` logs method names and request ids; `verbose` adds parameters.
 *
 * @param level The normalised `trace.server` setting.
 * @param values The library's `Trace` enum object.
 * @returns The matching library value.
 */
export function toLibraryTrace(level: TraceLevel, values: TraceValues): Trace {
  switch (level) {
    case 'messages':
      return values.Messages;
    case 'verbose':
      return values.Verbose;
    case 'off':
      return values.Off;
  }
}
