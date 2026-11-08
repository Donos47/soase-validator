/**
 * Interpreter around the lifecycle reducer. It feeds events through `step`,
 * runs the resulting effects through injected ports and tags every process,
 * timer and client with the generation of its start, so that late events of
 * an old start never reach the reducer.
 */

import type { LogLevel } from '../format/log-line';
import { StderrCapture } from '../format/line-splitter';
import type { StatusSnapshot } from '../format/status-text';
import { buildServerCommand, formatCommand } from '../launcher/server-command';
import type { UvVersionProbe } from '../launcher/uv-version';
import type { TraceLevel } from '../settings/extension-settings';
import {
  initialLifecycle,
  step,
  type Lifecycle,
  type LifecycleEffect,
  type LifecycleEvent,
  type NotifyKind,
  type StepResult,
} from './lifecycle';
import type {
  ClientHooks,
  ControllerPorts,
  NotifyAction,
  NotifyDetails,
  ServerExit,
  ServerProcessHandle,
  StartedClient,
  TimerHandle,
} from './ports';
import { DEFAULT_RESTART_POLICY, type RestartPolicy } from './restart-policy';

/** Events that callers outside the controller may dispatch. */
export type ExternalEvent = Extract<
  LifecycleEvent,
  { readonly type: 'AutoStart' | 'TrustChanged' | 'RestartRequested' | 'StopRequested' }
>;

/** Options of createServerController. */
export interface ControllerOptions {
  /** Initial value of `workspace.isTrusted`. */
  readonly trusted: boolean;
  /** Restart policy; defaults to DEFAULT_RESTART_POLICY. */
  readonly policy?: RestartPolicy;
  /** Time allowed for a graceful stop before the forced kill; defaults to 5000. */
  readonly stopGraceMs?: number;
}

/** The interpreter around the lifecycle reducer. */
export interface ServerController {
  /**
   * Applies the event to the reducer immediately, then runs its effects in
   * order. The promise resolves when the effects have finished; the new state
   * is visible before that.
   */
  dispatch(event: ExternalEvent): Promise<void>;
  /** Current values for the status command. */
  snapshot(): StatusSnapshot;
  /** True while a started client exists, that is, after `initialize` and before the process ends. */
  isRunning(): boolean;
  /** Forwards to the started client; does nothing when no Server runs. */
  sendConfiguration(): void;
  /** Applies the level to the started client; does nothing when no Server runs. */
  setTrace(level: TraceLevel): void;
  /** Stops the process within 5 seconds and cancels timers. */
  dispose(): Promise<void>;
}

const DEFAULT_STOP_GRACE_MS = 5000;

// Waiting after the forced kill is bounded so a process that ignores the kill
// cannot block the effect queue.
const FORCED_KILL_SETTLE_MS = 1000;

const RESOLVE_FAILED_ACTIONS: readonly NotifyAction[] = ['open-install-docs', 'set-uv-path'];
const FAILURE_ACTIONS: readonly NotifyAction[] = ['show-output', 'restart-server'];

interface Deferred {
  readonly promise: Promise<void>;
  readonly resolve: () => void;
}

function createDeferred(): Deferred {
  let resolve: () => void = () => undefined;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

/** State of one start; created by the Spawn effect and owned by exactly one generation. */
interface Run {
  readonly generation: number;
  readonly stderr: StderrCapture;
  readonly timeoutSeconds: number;
  readonly trace: TraceLevel;
  /** Settles when the process is known or the client start has failed. */
  readonly ready: Deferred;
  /** Settles when the process has ended. */
  readonly ended: Deferred;
  handle: ServerProcessHandle | undefined;
  client: StartedClient | undefined;
  startupTimer: TimerHandle | undefined;
  killRequested: boolean;
  exited: boolean;
}

type PreparedEffect =
  | { readonly type: 'Resolve'; readonly generation: number }
  | { readonly type: 'Spawn'; readonly generation: number }
  | { readonly type: 'Kill'; readonly run: Run | undefined }
  | { readonly type: 'Notify'; readonly kind: NotifyKind; readonly details: NotifyDetails }
  | { readonly type: 'Log'; readonly level: LogLevel; readonly message: string };

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function describeExit(exit: ServerExit): string {
  if (exit.code !== null) {
    return `exit code ${exit.code}`;
  }
  return exit.signal !== null ? `signal ${exit.signal}` : 'no exit code';
}

class Controller implements ServerController {
  private lifecycle: Lifecycle;
  private current: Run | undefined;
  private tail: Promise<void> = Promise.resolve();
  private disposed = false;
  private disposing: Promise<void> | undefined;
  private uvxPath: string | undefined;
  private commandText: string | undefined;
  private readonly policy: RestartPolicy;
  private readonly stopGraceMs: number;

  constructor(
    private readonly ports: ControllerPorts,
    options: ControllerOptions,
  ) {
    this.policy = options.policy ?? DEFAULT_RESTART_POLICY;
    this.stopGraceMs = options.stopGraceMs ?? DEFAULT_STOP_GRACE_MS;
    this.lifecycle = initialLifecycle(options.trusted);
    this.guard(() => this.ports.ui.setState(this.lifecycle.state));
  }

  async dispatch(event: ExternalEvent): Promise<void> {
    try {
      await this.post(event);
      await this.settle();
    } catch (error) {
      this.log('error', `Internal error while handling ${event.type}: ${describeError(error)}`);
    }
  }

  snapshot(): StatusSnapshot {
    return {
      state: this.lifecycle.state,
      uvxPath: this.uvxPath,
      command: this.commandText,
      serverVersion: this.runningClient()?.serverVersion,
    };
  }

  isRunning(): boolean {
    return this.runningClient() !== undefined;
  }

  sendConfiguration(): void {
    const client = this.runningClient();
    if (client === undefined) {
      return;
    }
    this.guard(() => client.sendConfiguration(), 'Sending the configuration failed');
  }

  setTrace(level: TraceLevel): void {
    const client = this.runningClient();
    if (client === undefined) {
      return;
    }
    this.guard(() => client.setTrace(level), 'Applying the trace level failed');
  }

  dispose(): Promise<void> {
    if (this.disposing !== undefined) {
      return this.disposing;
    }
    this.disposed = true;
    const run = this.current;
    this.current = undefined;
    if (run !== undefined) {
      run.killRequested = true;
    }
    // The stop runs next to the queue, not behind it, so a slow stop already
    // in the queue cannot push disposal past the grace period.
    this.disposing = Promise.all([
      run === undefined ? Promise.resolve() : this.killRun(run, 0),
      this.tail,
    ]).then(
      () => undefined,
      () => undefined,
    );
    return this.disposing;
  }

  private runningClient(): StartedClient | undefined {
    const run = this.current;
    if (run === undefined || run.exited || this.lifecycle.state !== 'running') {
      return undefined;
    }
    return run.client;
  }

  private isCurrent(run: Run): boolean {
    return (
      !this.disposed && this.current === run && run.generation === this.lifecycle.generation
    );
  }

  private log(level: LogLevel, message: string): void {
    this.guard(() => this.ports.ui.log(level, message));
  }

  // A failing port must never escape into the reducer loop or an event
  // handler, so every outward call goes through here.
  private guard(action: () => void, failure?: string): void {
    try {
      action();
    } catch (error) {
      if (failure !== undefined) {
        try {
          this.ports.ui.log('error', `${failure}: ${describeError(error)}`);
        } catch {
          // Nothing else can report this failure.
        }
      }
    }
  }

  private swallow(pending: PromiseLike<unknown>, failure: string): void {
    pending.then(undefined, (error: unknown) => {
      this.log('error', `${failure}: ${describeError(error)}`);
    });
  }

  private async settle(): Promise<void> {
    let seen: Promise<void>;
    do {
      seen = this.tail;
      await seen;
    } while (seen !== this.tail);
  }

  // The reducer step and the bookkeeping that depends on its result happen
  // synchronously, so the state is already consistent when any effect or
  // callback runs; only the effects wait in the queue.
  private post(event: LifecycleEvent, run?: Run): Promise<void> {
    if (this.disposed) {
      return this.tail;
    }
    const previous = this.lifecycle;
    let result: StepResult;
    try {
      result = step(previous, event, this.policy);
    } catch (error) {
      this.log('error', `Internal error in the lifecycle reducer: ${describeError(error)}`);
      return this.tail;
    }
    this.lifecycle = result.next;
    const prepared = this.prepare(result.effects, run);
    if (result.next.state !== 'starting') {
      this.current?.startupTimer?.cancel();
    }
    if (result.next.state !== previous.state) {
      const state = result.next.state;
      this.guard(() => this.ports.ui.setState(state), 'Updating the status item failed');
    }
    if (prepared.length === 0) {
      return this.tail;
    }
    const work = this.tail.then(() => this.runEffects(prepared));
    this.tail = work;
    return work;
  }

  private prepare(effects: readonly LifecycleEffect[], run: Run | undefined): PreparedEffect[] {
    const prepared: PreparedEffect[] = [];
    for (const effect of effects) {
      switch (effect.type) {
        case 'Resolve':
        case 'Spawn':
          prepared.push({ type: effect.type, generation: this.lifecycle.generation });
          break;
        case 'Kill': {
          const target = this.current;
          if (target !== undefined) {
            target.killRequested = true;
            target.startupTimer?.cancel();
            this.current = undefined;
          }
          prepared.push({ type: 'Kill', run: target });
          break;
        }
        case 'Notify':
          prepared.push({
            type: 'Notify',
            kind: effect.kind,
            details: this.describeNotification(effect.kind, run),
          });
          break;
        case 'Log':
          prepared.push({ type: 'Log', level: effect.level, message: effect.message });
          break;
      }
    }
    return prepared;
  }

  private describeNotification(kind: NotifyKind, run: Run | undefined): NotifyDetails {
    const head = run === undefined ? [] : run.stderr.headLines();
    switch (kind) {
      case 'resolve-failed':
        return {
          message: 'uv is required to run the SoaSE Validator server, but uvx was not found.',
          lines: [],
        };
      case 'spawn-failed':
        return { message: 'The SoaSE Validator server failed to start.', lines: head };
      case 'timeout':
        return {
          message:
            run === undefined
              ? 'The SoaSE Validator server did not start in time.'
              : `The SoaSE Validator server did not start within ${run.timeoutSeconds} seconds.`,
          lines: [],
        };
      case 'exited':
        return {
          message: 'The SoaSE Validator server exited before it finished starting.',
          lines: head,
        };
      case 'restarts-stopped':
        return {
          message:
            'The SoaSE Validator server stopped unexpectedly. Automatic restarts were stopped.',
          lines: [],
        };
    }
  }

  private async runEffects(effects: readonly PreparedEffect[]): Promise<void> {
    for (const effect of effects) {
      try {
        await this.runEffect(effect);
      } catch (error) {
        this.log('error', `Internal error while running ${effect.type}: ${describeError(error)}`);
      }
    }
  }

  private async runEffect(effect: PreparedEffect): Promise<void> {
    switch (effect.type) {
      case 'Log':
        this.log(effect.level, effect.message);
        return;
      case 'Notify':
        if (!this.disposed) {
          this.showNotification(effect.kind, effect.details);
        }
        return;
      case 'Kill':
        if (effect.run !== undefined) {
          await this.killRun(effect.run, FORCED_KILL_SETTLE_MS);
        }
        return;
      case 'Resolve':
        if (this.canResolve(effect.generation)) {
          this.runResolve();
        }
        return;
      case 'Spawn':
        if (this.canSpawn(effect.generation)) {
          this.runSpawn();
        }
        return;
    }
  }

  private canResolve(generation: number): boolean {
    const lifecycle = this.lifecycle;
    return (
      !this.disposed &&
      lifecycle.generation === generation &&
      lifecycle.state === 'starting' &&
      !lifecycle.live
    );
  }

  private canSpawn(generation: number): boolean {
    const lifecycle = this.lifecycle;
    return (
      !this.disposed &&
      lifecycle.generation === generation &&
      lifecycle.state === 'starting' &&
      lifecycle.live &&
      this.current === undefined
    );
  }

  private runResolve(): void {
    let resolution: ReturnType<ControllerPorts['resolve']>;
    try {
      resolution = this.ports.resolve();
    } catch (error) {
      this.log('error', `Resolving uvx failed: ${describeError(error)}`);
      resolution = { found: false, searched: [], reason: 'not-found' };
    }
    if (resolution.found) {
      this.uvxPath = resolution.path;
      void this.post({ type: 'Resolved' });
      return;
    }
    this.uvxPath = undefined;
    this.commandText = undefined;
    this.log(
      'error',
      resolution.reason === 'uvPath-invalid'
        ? 'soase-validator.uvPath does not point to an executable uvx.'
        : 'uvx was not found.',
    );
    for (const location of resolution.searched) {
      this.log('info', `Searched: ${location}`);
    }
    void this.post({ type: 'ResolveFailed' });
  }

  private runSpawn(): void {
    const uvxPath = this.uvxPath;
    if (uvxPath === undefined) {
      this.log('error', 'The Server cannot start because uvx is not resolved.');
      void this.post({ type: 'SpawnFailed' });
      return;
    }
    this.log('info', `Using uvx at ${uvxPath}`);
    this.probeInBackground(uvxPath);

    let run: Run | undefined;
    try {
      const settings = this.ports.settings();
      const folders = this.ports.folders();
      const command = buildServerCommand(uvxPath, settings.serverSource, folders.paths, folders.home);
      this.commandText = formatCommand(command);
      this.log('info', `Starting the Server: ${this.commandText}`);

      const started: Run = {
        generation: this.lifecycle.generation,
        stderr: new StderrCapture(),
        timeoutSeconds: settings.timeoutSeconds,
        trace: settings.trace,
        ready: createDeferred(),
        ended: createDeferred(),
        handle: undefined,
        client: undefined,
        startupTimer: undefined,
        killRequested: false,
        exited: false,
      };
      run = started;
      this.current = started;
      started.startupTimer = this.ports.setTimer(settings.timeoutSeconds * 1000, () => {
        this.onStartupTimeout(started);
      });

      const hooks: ClientHooks = {
        onSpawned: (handle) => {
          this.attachHandle(started, handle);
        },
        onStderrLine: (line) => {
          started.stderr.add([line]);
        },
        onExit: (exit) => {
          this.onProcessExit(started, exit);
        },
      };
      let pending: Promise<StartedClient>;
      try {
        pending = this.ports.startClient(command, hooks);
      } catch (error) {
        pending = Promise.reject(error instanceof Error ? error : new Error(String(error)));
      }
      pending.then(
        (client) => {
          this.onClientStarted(started, client);
        },
        (error: unknown) => {
          this.onClientFailed(started, error);
        },
      );
    } catch (error) {
      this.log('error', `The Server failed to start: ${describeError(error)}`);
      void this.post({ type: 'SpawnFailed' }, run);
    }
  }

  private probeInBackground(uvxPath: string): void {
    let probe: Promise<UvVersionProbe>;
    try {
      probe = this.ports.probeVersion(uvxPath);
    } catch (error) {
      probe = Promise.reject(error instanceof Error ? error : new Error(String(error)));
    }
    probe.then(
      (result) => {
        if (result.available) {
          this.log('info', `uvx version: ${result.text}`);
        } else {
          this.log('warn', `The uvx version is unavailable: ${result.reason}`);
        }
      },
      (error: unknown) => {
        this.log('warn', `The uvx version is unavailable: ${describeError(error)}`);
      },
    );
  }

  private attachHandle(run: Run, handle: ServerProcessHandle): void {
    if (run.handle === handle) {
      return;
    }
    run.handle = handle;
    run.ready.resolve();
    handle.exited.then(
      (exit) => {
        this.onProcessExit(run, exit);
      },
      () => {
        this.onProcessExit(run, { code: null, signal: null });
      },
    );
    if (run.killRequested) {
      // The stop request arrived before the process was reported.
      this.guard(() => handle.kill(), 'Terminating the Server failed');
    }
  }

  private onClientStarted(run: Run, client: StartedClient): void {
    this.attachHandle(run, client.process);
    run.ready.resolve();
    if (!this.isCurrent(run)) {
      this.discardClient(run, client);
      return;
    }
    run.client = client;
    run.startupTimer?.cancel();
    this.guard(() => client.setTrace(run.trace), 'Applying the trace level failed');
    void this.post({ type: 'Initialized' }, run);
  }

  private onClientFailed(run: Run, error: unknown): void {
    run.ready.resolve();
    const text = describeError(error);
    if (!this.isCurrent(run)) {
      this.log('debug', `The start of a stopped Server ended: ${text}`);
      return;
    }
    this.log('error', `The Server failed to start: ${text}`);
    void this.post({ type: 'SpawnFailed' }, run);
  }

  // A client that finishes starting after its run was stopped must not
  // outlive that run.
  private discardClient(run: Run, client: StartedClient): void {
    const stopped = Promise.resolve()
      .then(() => client.stop())
      .catch((error: unknown) => {
        this.log('debug', `Stopping a late client failed: ${describeError(error)}`);
      });
    this.swallow(
      stopped.then(() => {
        if (!run.exited) {
          this.guard(() => run.handle?.kill(), 'Terminating the Server failed');
        }
      }),
      'Cleaning up a late client failed',
    );
  }

  private onStartupTimeout(run: Run): void {
    if (!this.isCurrent(run) || run.client !== undefined) {
      return;
    }
    this.log('error', `Startup timed out after ${run.timeoutSeconds} seconds.`);
    void this.post({ type: 'TimedOut' }, run);
  }

  private onProcessExit(run: Run, exit: ServerExit): void {
    if (run.exited) {
      return;
    }
    run.exited = true;
    run.ended.resolve();
    run.startupTimer?.cancel();
    const description = describeExit(exit);
    const owned = this.current === run;
    if (owned) {
      this.current = undefined;
    }
    if (!owned || this.disposed || run.generation !== this.lifecycle.generation) {
      this.log('info', `The Server process ended (${description}).`);
      return;
    }
    this.log('error', `The Server process exited unexpectedly (${description}).`);
    const tail = run.stderr.tailLines();
    if (tail.length === 0) {
      this.log('info', 'The Server wrote nothing to standard error.');
    } else {
      this.log('info', `Last ${tail.length} lines of standard error:`);
      for (const line of tail) {
        this.log('info', `stderr: ${line}`);
      }
    }
    void this.post(
      { type: 'Exited', at: this.ports.now(), requested: run.killRequested },
      run,
    );
  }

  private showNotification(kind: NotifyKind, details: NotifyDetails): void {
    const actions = kind === 'resolve-failed' ? RESOLVE_FAILED_ACTIONS : FAILURE_ACTIONS;
    let pending: Promise<NotifyAction | undefined>;
    try {
      pending = this.ports.ui.notifyError(kind, details, actions);
    } catch (error) {
      this.log('error', `Showing a notification failed: ${describeError(error)}`);
      return;
    }
    pending.then(
      (action) => {
        this.onAction(action);
      },
      (error: unknown) => {
        this.log('error', `Showing a notification failed: ${describeError(error)}`);
      },
    );
  }

  private onAction(action: NotifyAction | undefined): void {
    const ui = this.ports.ui;
    try {
      switch (action) {
        case undefined:
          return;
        case 'open-install-docs':
          this.swallow(ui.openInstallDocs(), 'Opening the install instructions failed');
          return;
        case 'set-uv-path':
          this.swallow(ui.openUvPathSetting(), 'Opening the uvPath setting failed');
          return;
        case 'show-output':
          ui.showOutput();
          return;
        case 'restart-server':
          void this.dispatch({ type: 'RestartRequested' });
          return;
      }
    } catch (error) {
      this.log('error', `Handling the notification action failed: ${describeError(error)}`);
    }
  }

  private waitFor(pending: Promise<unknown>, ms: number): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      let done = false;
      let timer: TimerHandle | undefined;
      const finish = (value: boolean): void => {
        if (done) {
          return;
        }
        done = true;
        timer?.cancel();
        resolve(value);
      };
      try {
        timer = this.ports.setTimer(ms, () => {
          finish(false);
        });
      } catch {
        finish(false);
        return;
      }
      pending.then(
        () => {
          finish(true);
        },
        () => {
          finish(true);
        },
      );
    });
  }

  // Stops the process gracefully when a started client exists, and kills it
  // when it ignores the stop request for the grace period.
  private async killRun(run: Run, settleMs: number): Promise<void> {
    run.startupTimer?.cancel();
    if (run.handle === undefined) {
      await this.waitFor(run.ready.promise, this.stopGraceMs);
    }
    const handle = run.handle;
    if (handle === undefined) {
      this.log('warn', 'The Server process was not reported in time; it is terminated once it appears.');
      return;
    }
    if (run.exited) {
      return;
    }
    const client = run.client;
    if (client === undefined) {
      this.guard(() => handle.kill(), 'Terminating the Server failed');
    } else {
      this.swallow(
        Promise.resolve().then(() => client.stop()),
        'Stopping the Server failed',
      );
    }
    if (await this.waitFor(run.ended.promise, this.stopGraceMs)) {
      return;
    }
    this.log(
      'warn',
      `The Server did not exit within ${this.stopGraceMs / 1000} seconds of the stop request; terminating it.`,
    );
    this.guard(() => handle.kill(), 'Terminating the Server failed');
    if (settleMs > 0) {
      await this.waitFor(run.ended.promise, settleMs);
    }
  }
}

/**
 * Creates the controller.
 *
 * @param ports - Everything the controller needs from the outside.
 * @param options - Initial trust, restart policy and stop grace period.
 * @returns A controller in the `stopped` state; nothing starts until an event is dispatched.
 */
export function createServerController(
  ports: ControllerPorts,
  options: ControllerOptions,
): ServerController {
  return new Controller(ports, options);
}
