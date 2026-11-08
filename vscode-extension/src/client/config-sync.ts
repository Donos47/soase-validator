/**
 * Debounces Server Setting changes into one configuration notification per burst.
 *
 * This module is pure and has no dependency on `vscode`.
 */

import type { TimerHandle } from '../lifecycle/ports';
import { SERVER_SETTINGS } from '../settings/server-settings-schema';
import type { ServerSettingDef } from '../settings/server-settings-schema';

/** Default quiet period of the debouncer. */
export const DEFAULT_QUIET_MS = 250;

/** Default maximum wait of the debouncer. */
export const DEFAULT_MAX_WAIT_MS = 500;

/** Prefix of every setting id of the Extension. */
const SECTION = 'soase-validator';

/** Dependencies of ConfigSync. */
export interface ConfigSyncDeps {
  /** Epoch milliseconds. */
  readonly now: () => number;
  /** Starts a one-shot timer (TimerHandle is defined in lifecycle/ports.ts). */
  readonly setTimer: (ms: number, fn: () => void) => TimerHandle;
  /** Sends the notification; in production `controller.sendConfiguration`. */
  readonly send: () => void;
  /** Quiet period in milliseconds; defaults to DEFAULT_QUIET_MS. */
  readonly quietMs?: number;
  /** Longest wait since the first change of a burst; defaults to DEFAULT_MAX_WAIT_MS. */
  readonly maxWaitMs?: number;
}

/**
 * Tells whether a configuration change touches a Server Setting.
 *
 * @param affects Predicate over full setting ids, in production
 *   `(id) => event.affectsConfiguration(id)`.
 * @param settings The Server Settings to test; defaults to `SERVER_SETTINGS`.
 * @returns True when `affects('soase-validator.<key>')` holds for at least one key.
 */
export function affectsServerSetting(
  affects: (settingId: string) => boolean,
  settings: readonly ServerSettingDef[] = SERVER_SETTINGS,
): boolean {
  return settings.some((def) => affects(`${SECTION}.${def.key}`));
}

/** Debounces change events and calls `send` once per burst. */
export class ConfigSync {
  private readonly quietMs: number;
  private readonly maxWaitMs: number;
  private timer: TimerHandle | undefined;
  private burstStart = 0;

  /**
   * Creates a debouncer.
   *
   * @param deps Clock, timer and send callback.
   */
  constructor(private readonly deps: ConfigSyncDeps) {
    this.quietMs = deps.quietMs ?? DEFAULT_QUIET_MS;
    this.maxWaitMs = deps.maxWaitMs ?? DEFAULT_MAX_WAIT_MS;
  }

  /** Records a Server Setting change. */
  notifyChange(): void {
    const now = this.deps.now();
    if (this.timer === undefined) {
      this.burstStart = now;
    } else {
      this.timer.cancel();
    }
    const remaining = this.burstStart + this.maxWaitMs - now;
    const delay = Math.max(0, Math.min(this.quietMs, remaining));
    this.timer = this.deps.setTimer(delay, () => this.fire());
  }

  /** Cancels any pending send. */
  dispose(): void {
    this.timer?.cancel();
    this.timer = undefined;
  }

  private fire(): void {
    // Cleared first so a change raised by `send` starts a new burst.
    this.timer = undefined;
    this.deps.send();
  }
}
