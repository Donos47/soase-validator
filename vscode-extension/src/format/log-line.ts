/** Severity levels of an Extension message in the Output Channel. */
export type LogLevel = 'error' | 'warn' | 'info' | 'debug';

/**
 * Formats one Extension message as `<ISO-8601 timestamp> [<level>] <message>`.
 *
 * The timestamp comes from the caller so the function stays pure. The
 * message is copied unchanged.
 *
 * @param level Severity of the message.
 * @param message Message text.
 * @param at Moment of the message, as a Date or epoch milliseconds.
 * @returns The formatted line without a trailing line end.
 * @throws RangeError When `at` is not a valid time value.
 */
export function formatLogLine(level: LogLevel, message: string, at: Date | number): string {
  const instant = typeof at === 'number' ? new Date(at) : at;
  return `${instant.toISOString()} [${level}] ${message}`;
}
