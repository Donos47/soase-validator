/**
 * Extension entry point and composition root: builds the real ports and
 * wires the controller, the adapters, the commands and the triggers.
 */

import { accessSync, constants, statSync } from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import * as vscode from 'vscode';

import { registerActivation } from './activation';
import { createStartClient } from './client/client-factory';
import { ConfigSync } from './client/config-sync';
import type { TestOverride } from './client/spawn-server';
import { registerCommands } from './commands';
import { resolveUvx } from './launcher/resolve-uvx';
import type { Platform, UvxResolution } from './launcher/resolve-uvx';
import { execFileAdapter, probeUvVersion } from './launcher/uv-version';
import type { UvVersionProbe } from './launcher/uv-version';
import type { ControllerPorts } from './lifecycle/ports';
import { createServerController } from './lifecycle/server-controller';
import type { ServerController } from './lifecycle/server-controller';
import { createConfigReader, readExtensionSettings } from './settings/vscode-config-reader';
import { createOutputLog } from './ui/output-log';
import type { OutputLog } from './ui/output-log';
import { createStatusItem } from './ui/status-item';
import type { StatusItem } from './ui/status-item';
import { createUiPort } from './ui/ui-port';

/** Test-only hooks; present on the returned API only when `context.extensionMode === vscode.ExtensionMode.Test`. */
export interface ExtensionTestApi {
  /** Replaces uvx resolution and process spawn; pass undefined to restore the real behaviour. Takes effect at the next start. */
  setTestOverride(override: TestOverride | undefined): void;
  /** The controller, so host tests can dispatch events and read snapshots. */
  readonly controller: ServerController;
}

/** What `activate` returns. */
export interface ExtensionApi {
  /** Undefined outside Test mode. */
  readonly testing?: ExtensionTestApi;
}

/** Longest time `deactivate` waits for the Server to stop. */
const DEACTIVATE_TIMEOUT_MS = 5000;

interface Active {
  readonly controller: ServerController;
  readonly configSync: ConfigSync;
  readonly log: OutputLog;
  readonly status: StatusItem;
}

let active: Active | undefined;

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function currentPlatform(): Platform {
  if (process.platform === 'win32') {
    return 'win32';
  }
  return process.platform === 'darwin' ? 'darwin' : 'linux';
}

// The resolver stays pure, so the file system check lives here.
function isExecutableFile(candidate: string, platform: Platform): boolean {
  try {
    if (!statSync(candidate).isFile()) {
      return false;
    }
    if (platform !== 'win32') {
      accessSync(candidate, constants.X_OK);
    }
    return true;
  } catch {
    return false;
  }
}

function buildPorts(
  log: OutputLog,
  ui: ControllerPorts['ui'],
  getOverride: () => TestOverride | undefined,
): ControllerPorts {
  const platform = currentPlatform();
  const readConfig = createConfigReader();

  const readSettings = () => {
    const settings = readExtensionSettings();
    for (const warning of settings.warnings) {
      log.warnOnce('startupTimeoutSeconds', warning, warning);
    }
    return settings;
  };

  const resolve = (): UvxResolution => {
    const override = getOverride();
    if (override !== undefined) {
      return { found: true, path: override.uvxPath, source: 'uvPath' };
    }
    return resolveUvx(readSettings().uvPath, {
      platform,
      env: process.env,
      homeDir: os.homedir(),
      isExecutableFile: (candidate) => isExecutableFile(candidate, platform),
      joinPath: (...parts) => path.join(...parts),
    });
  };

  const probeVersion = (uvxPath: string): Promise<UvVersionProbe> => {
    if (getOverride() !== undefined) {
      return Promise.resolve({ available: false, reason: 'test override' });
    }
    return probeUvVersion(uvxPath, execFileAdapter);
  };

  return {
    now: Date.now,
    setTimer: (ms, fn) => {
      const handle = setTimeout(fn, ms);
      return { cancel: () => clearTimeout(handle) };
    },
    resolve,
    probeVersion,
    settings: () => {
      const { serverSource, timeoutSeconds, trace } = readSettings();
      return { serverSource, timeoutSeconds, trace };
    },
    folders: () => ({
      paths: (vscode.workspace.workspaceFolders ?? []).map((folder) => folder.uri.fsPath),
      home: os.homedir(),
    }),
    startClient: createStartClient({
      outputChannel: log.channel,
      readConfig,
      getTestOverride: getOverride,
      getTrace: () => readSettings().trace,
      onInvalidSetting: (key, value) => {
        log.warnOnce(key, value, `Ignoring setting soase-validator.${key}: the value has the wrong type.`);
      },
      env: process.env,
    }),
    ui,
  };
}

/**
 * Activates the Extension; completes without waiting for the Server.
 *
 * Any failure is logged, shown as one notification and swallowed, so the
 * window keeps working.
 *
 * @param context Extension context supplied by VS Code.
 * @returns The API; `testing` is present only in Test mode.
 */
export function activate(context: vscode.ExtensionContext): ExtensionApi {
  let log: OutputLog | undefined;
  try {
    const isTestMode = context.extensionMode === vscode.ExtensionMode.Test;
    let override: TestOverride | undefined;
    const getOverride = (): TestOverride | undefined => (isTestMode ? override : undefined);

    const outputLog = createOutputLog();
    log = outputLog;
    const status = createStatusItem();
    const ui = createUiPort(outputLog, status);
    const controller = createServerController(buildPorts(outputLog, ui, getOverride), {
      trusted: vscode.workspace.isTrusted,
    });
    const configSync = new ConfigSync({
      now: Date.now,
      setTimer: (ms, fn) => {
        const handle = setTimeout(fn, ms);
        return { cancel: () => clearTimeout(handle) };
      },
      send: () => controller.sendConfiguration(),
    });
    active = { controller, configSync, log: outputLog, status };

    context.subscriptions.push(
      ...registerCommands({ controller, ui }),
      ...registerActivation({ controller, configSync, log: outputLog }),
    );

    if (!isTestMode) {
      return {};
    }
    return {
      testing: {
        setTestOverride: (next) => {
          override = next;
        },
        controller,
      },
    };
  } catch (error) {
    const message = `SoaSE Validator failed to activate: ${describeError(error)}`;
    log?.log('error', message);
    void vscode.window.showErrorMessage(message);
    return {};
  }
}

/**
 * Stops the Server within 5 seconds and disposes the channel and status item.
 *
 * @returns Resolves after the controller has been disposed.
 */
export async function deactivate(): Promise<void> {
  const current = active;
  active = undefined;
  if (current === undefined) {
    return;
  }
  current.configSync.dispose();
  let timer: NodeJS.Timeout | undefined;
  const limit = new Promise<void>((resolve) => {
    timer = setTimeout(resolve, DEACTIVATE_TIMEOUT_MS);
  });
  try {
    await Promise.race([current.controller.dispose(), limit]);
  } catch (error) {
    current.log.log('error', `Stopping the Server failed: ${describeError(error)}`);
  } finally {
    clearTimeout(timer);
    current.status.dispose();
    current.log.dispose();
  }
}
