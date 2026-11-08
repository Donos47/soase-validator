/**
 * Pure lifecycle reducer for the Server process. The controller feeds events
 * in and executes the returned effects; nothing here touches the outside
 * world.
 */

import { decideRestart, type RestartPolicy } from './restart-policy';

/** Server states shown to the user. */
export type ServerState = 'stopped' | 'starting' | 'running' | 'error';

/** Reducer state. */
export interface Lifecycle {
  /** State shown in the Status Item. */
  readonly state: ServerState;
  /** True from the moment a `Spawn` effect is emitted until the process is gone. */
  readonly live: boolean;
  /** True after a stop command, until the next restart command. */
  readonly userStopped: boolean;
  /** True when the workspace is trusted. */
  readonly trusted: boolean;
  /** Counts starts; tags processes, timers and clients of one start. */
  readonly generation: number;
  /** Timestamps (ms) of unexpected exits after `running` inside the window. */
  readonly exits: readonly number[];
}

/** Events fed to the reducer. */
export type LifecycleEvent =
  | { readonly type: 'AutoStart' }
  | { readonly type: 'TrustChanged'; readonly trusted: boolean }
  | { readonly type: 'RestartRequested' }
  | { readonly type: 'StopRequested' }
  | { readonly type: 'Resolved' }
  | { readonly type: 'ResolveFailed' }
  | { readonly type: 'SpawnFailed' }
  | { readonly type: 'Initialized' }
  | { readonly type: 'TimedOut' }
  | { readonly type: 'Exited'; readonly at: number; readonly requested: boolean }
  | { readonly type: 'RestartTimerFired' };

/** Kinds of error notification the controller can show. */
export type NotifyKind =
  | 'resolve-failed'
  | 'spawn-failed'
  | 'timeout'
  | 'exited'
  | 'restarts-stopped';

/** Effects the controller executes, in order. */
export type LifecycleEffect =
  | { readonly type: 'Resolve' }
  | { readonly type: 'Spawn' }
  | { readonly type: 'Kill' }
  | { readonly type: 'Notify'; readonly kind: NotifyKind }
  | {
      readonly type: 'Log';
      readonly level: 'info' | 'warn' | 'error';
      readonly message: string;
    };

/** Result of one reducer step. */
export interface StepResult {
  /** The state after the event. */
  readonly next: Lifecycle;
  /** Effects to run, in order. */
  readonly effects: readonly LifecycleEffect[];
}

/**
 * Build the state of a window that has not started the Server.
 *
 * @param trusted - Whether the workspace is trusted.
 * @returns The initial `stopped` state.
 */
export function initialLifecycle(trusted: boolean): Lifecycle {
  return {
    state: 'stopped',
    live: false,
    userStopped: false,
    trusted,
    generation: 0,
    exits: [],
  };
}

function unchanged(current: Lifecycle): StepResult {
  return { next: current, effects: [] };
}

function killIfLive(current: Lifecycle): LifecycleEffect[] {
  return current.live ? [{ type: 'Kill' }] : [];
}

// A start only resolves here; `Spawn` is emitted by `Resolved`, which keeps
// "Spawn only when not live" in one place and lets the controller finish a
// graceful Kill before it re-resolves.
function begin(current: Lifecycle, exits: readonly number[]): Lifecycle {
  return {
    ...current,
    state: 'starting',
    live: false,
    generation: current.generation + 1,
    exits,
  };
}

function fail(current: Lifecycle, notify: NotifyKind | null): StepResult {
  const effects: LifecycleEffect[] = killIfLive(current);
  if (notify !== null) {
    effects.push({ type: 'Notify', kind: notify });
  }
  return { next: { ...current, state: 'error', live: false }, effects };
}

function onExited(
  current: Lifecycle,
  event: Extract<LifecycleEvent, { type: 'Exited' }>,
  policy: RestartPolicy,
): StepResult {
  if (!current.live) {
    return unchanged(current);
  }
  const gone: Lifecycle = { ...current, live: false };
  if (current.state === 'running' && !event.requested) {
    const decision = decideRestart(current.exits, event.at, policy);
    if (decision.restart) {
      return {
        next: begin(gone, decision.exits),
        effects: [
          {
            type: 'Log',
            level: 'warn',
            message: 'The Server exited unexpectedly; restarting automatically.',
          },
          { type: 'Resolve' },
        ],
      };
    }
    return {
      next: { ...gone, state: 'error', exits: decision.exits },
      effects: [
        {
          type: 'Log',
          level: 'error',
          message: 'Automatic restarts were stopped after repeated unexpected exits.',
        },
        { type: 'Notify', kind: 'restarts-stopped' },
      ],
    };
  }
  if (current.state === 'starting' && !event.requested) {
    return fail(gone, 'exited');
  }
  // A requested exit of a process the reducer still considers live means the
  // controller and the reducer disagree; surface it as an error without a
  // notification or a crash-window entry.
  return fail(gone, null);
}

/**
 * Advance the lifecycle by one event.
 *
 * Total over every state and event pair: events that do not apply in the
 * current state return the state unchanged with no effects. `Spawn` is only
 * emitted from `Resolved` while no process is live.
 *
 * @param current - The state before the event.
 * @param event - The event.
 * @param policy - The restart policy for unexpected exits.
 * @returns The next state and the effects to run.
 */
export function step(
  current: Lifecycle,
  event: LifecycleEvent,
  policy: RestartPolicy,
): StepResult {
  switch (event.type) {
    case 'AutoStart':
      if (current.state !== 'stopped' || current.userStopped || !current.trusted) {
        return unchanged(current);
      }
      return {
        next: begin(current, current.exits),
        effects: [{ type: 'Resolve' }],
      };

    case 'TrustChanged':
      return { next: { ...current, trusted: event.trusted }, effects: [] };

    case 'RestartRequested': {
      if (!current.trusted) {
        // Starting is forbidden in an untrusted workspace; the flags are still
        // cleared so the grant of trust starts the Server.
        return {
          next: {
            ...current,
            state: 'stopped',
            live: false,
            userStopped: false,
            exits: [],
          },
          effects: [
            ...killIfLive(current),
            {
              type: 'Log',
              level: 'warn',
              message: 'The Server is not started because the workspace is not trusted.',
            },
          ],
        };
      }
      return {
        next: { ...begin(current, []), userStopped: false },
        effects: [...killIfLive(current), { type: 'Resolve' }],
      };
    }

    case 'StopRequested':
      return {
        next: { ...current, state: 'stopped', live: false, userStopped: true },
        effects: killIfLive(current),
      };

    case 'Resolved':
      if (current.state !== 'starting' || current.live) {
        return unchanged(current);
      }
      return { next: { ...current, live: true }, effects: [{ type: 'Spawn' }] };

    case 'ResolveFailed':
      if (current.state !== 'starting' || current.live) {
        return unchanged(current);
      }
      return fail(current, 'resolve-failed');

    case 'SpawnFailed':
      if (current.state !== 'starting') {
        return unchanged(current);
      }
      return fail(current, 'spawn-failed');

    case 'Initialized':
      if (current.state !== 'starting' || !current.live) {
        return unchanged(current);
      }
      return { next: { ...current, state: 'running' }, effects: [] };

    case 'TimedOut':
      if (current.state !== 'starting' || !current.live) {
        return unchanged(current);
      }
      return fail(current, 'timeout');

    case 'Exited':
      return onExited(current, event, policy);

    case 'RestartTimerFired':
      // Automatic restarts start at once, so no timer is armed.
      return unchanged(current);
  }
}
