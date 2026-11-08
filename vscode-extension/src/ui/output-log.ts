/**
 * Owner of the single `SoaSE Validator` Output Channel.
 */

import * as vscode from 'vscode';

import { formatLogLine } from '../format/log-line';
import type { LogLevel } from '../format/log-line';

/** Name of the one Output Channel the Extension creates. */
export const OUTPUT_CHANNEL_NAME = 'SoaSE Validator';

/** Owner of the single Output Channel. */
export interface OutputLog {
  /** The channel, shared with the language client. */
  readonly channel: vscode.OutputChannel;
  /** Writes one Extension line through `formatLogLine`. */
  log(level: LogLevel, message: string): void;
  /** Writes a `warn` line once per distinct key and value pair. */
  warnOnce(key: string, value: unknown, message: string): void;
  /** Reveals the channel without taking focus. */
  show(): void;
  /** Disposes the channel; later lines go to `console.error`. */
  dispose(): void;
}

/**
 * Serializes a setting value so equal values produce equal keys.
 *
 * @param value Any value read from a setting.
 * @returns A stable text form; never throws.
 */
function serializeValue(value: unknown): string {
  try {
    return JSON.stringify(value) ?? 'undefined';
  } catch {
    return String(value);
  }
}

/**
 * Creates the Output Channel and its logging helpers.
 *
 * @param now Clock in epoch milliseconds; defaults to `Date.now`.
 * @returns The log owner. Call it once per window.
 */
export function createOutputLog(now: () => number = Date.now): OutputLog {
  const channel = vscode.window.createOutputChannel(OUTPUT_CHANNEL_NAME);
  const warned = new Set<string>();
  let disposed = false;

  function log(level: LogLevel, message: string): void {
    const line = formatLogLine(level, message, now());
    if (disposed) {
      // The channel is gone and the Extension may not write to stdout or
      // stderr directly, so this is the one place a console write is allowed.
      // eslint-disable-next-line no-console -- fallback after the channel is disposed
      console.error(line);
      return;
    }
    channel.appendLine(line);
  }

  return {
    channel,
    log,
    warnOnce(key: string, value: unknown, message: string): void {
      const id = `${key}\u0000${serializeValue(value)}`;
      if (warned.has(id)) {
        return;
      }
      warned.add(id);
      log('warn', message);
    },
    show(): void {
      if (!disposed) {
        channel.show(true);
      }
    },
    dispose(): void {
      if (disposed) {
        return;
      }
      disposed = true;
      channel.dispose();
    },
  };
}
