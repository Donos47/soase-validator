/**
 * Rolling-window restart policy for unexpected Server exits. Pure; the caller
 * supplies the timestamps.
 */

/** Rolling window policy: at most `maxRestarts` restarts within `windowMs`. */
export interface RestartPolicy {
  /** Largest number of automatic restarts allowed inside one window. */
  readonly maxRestarts: number;
  /** Length of the rolling window in milliseconds. */
  readonly windowMs: number;
}

/** Three restarts within any rolling five-minute window. */
export const DEFAULT_RESTART_POLICY: RestartPolicy = {
  maxRestarts: 3,
  windowMs: 300_000,
};

/** Outcome of {@link decideRestart}. */
export interface RestartDecision {
  /** True when the exit is followed by an automatic restart. */
  readonly restart: boolean;
  /** Exits still inside the window, with the current exit appended. */
  readonly exits: readonly number[];
}

/**
 * Decide whether an unexpected exit is followed by an automatic restart.
 *
 * An earlier exit lies inside the window when `now - t < windowMs`, so an exit
 * exactly one window ago no longer counts. The returned list drops older
 * exits, which keeps the reducer state bounded.
 *
 * @param previousExits - Timestamps (ms) of earlier unexpected exits.
 * @param now - Timestamp (ms) of the exit being decided.
 * @param policy - The restart policy.
 * @returns Whether to restart, and the pruned exit list including `now`.
 */
export function decideRestart(
  previousExits: readonly number[],
  now: number,
  policy: RestartPolicy,
): RestartDecision {
  const recent = previousExits.filter((t) => now - t < policy.windowMs);
  return {
    restart: recent.length < policy.maxRestarts,
    exits: [...recent, now],
  };
}
