/**
 * Pure normalisers for the Extension-only settings (`uvPath`, `serverSource`,
 * `startupTimeoutSeconds`, `trace.server`). They never log; callers write any
 * returned warning to the Output Channel.
 */

/** Startup timeout in seconds used when the configured value is not a finite number. */
export const DEFAULT_STARTUP_TIMEOUT_SECONDS = 180;

/** Smallest startup timeout in seconds the Extension accepts. */
export const MIN_STARTUP_TIMEOUT_SECONDS = 10;

/** Trace level of the language client. */
export type TraceLevel = 'off' | 'messages' | 'verbose';

/** Result of {@link normaliseTimeout}. */
export interface NormalisedTimeout {
  /** The startup timeout to use, in seconds. */
  readonly seconds: number;
  /** Text for the Output Channel when the configured value was replaced. */
  readonly warning?: string;
}

const TRACE_LEVELS: readonly string[] = ['off', 'messages', 'verbose'];

/**
 * Normalise the configured startup timeout.
 *
 * A finite number of at least the minimum (including exactly 10) is used as
 * is. A finite number below the minimum becomes the minimum with a warning.
 * Anything else, including `NaN`, `Infinity` and non-numbers, becomes the
 * default with a warning, because an infinite timeout would disable the
 * startup check.
 *
 * @param raw - The value read from the configuration.
 * @returns The timeout in seconds and an optional warning.
 */
export function normaliseTimeout(raw: unknown): NormalisedTimeout {
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    if (raw >= MIN_STARTUP_TIMEOUT_SECONDS) {
      return { seconds: raw };
    }
    return {
      seconds: MIN_STARTUP_TIMEOUT_SECONDS,
      warning:
        `soase-validator.startupTimeoutSeconds is ${raw}, below the minimum; ` +
        `using ${MIN_STARTUP_TIMEOUT_SECONDS} seconds.`,
    };
  }
  return {
    seconds: DEFAULT_STARTUP_TIMEOUT_SECONDS,
    warning:
      'soase-validator.startupTimeoutSeconds is not a finite number; ' +
      `using ${DEFAULT_STARTUP_TIMEOUT_SECONDS} seconds.`,
  };
}

/**
 * Normalise the configured server trace level.
 *
 * @param raw - The value read from the configuration.
 * @returns `off`, `messages` or `verbose`; `off` for any other value.
 */
export function normaliseTrace(raw: unknown): TraceLevel {
  if (typeof raw === 'string' && TRACE_LEVELS.includes(raw)) {
    return raw as TraceLevel;
  }
  return 'off';
}

/**
 * Read a string setting.
 *
 * @param raw - The value read from the configuration.
 * @returns The value when it is a string, otherwise an empty string.
 */
export function readString(raw: unknown): string {
  return typeof raw === 'string' ? raw : '';
}
