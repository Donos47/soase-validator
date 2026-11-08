/**
 * Activation triggers: auto-start, workspace trust, opened documents and
 * configuration changes.
 */

import * as vscode from 'vscode';

import { affectsServerSetting } from './client/config-sync';
import type { ConfigSync } from './client/config-sync';
import type { ServerController } from './lifecycle/server-controller';
import { readExtensionSettings } from './settings/vscode-config-reader';
import type { OutputLog } from './ui/output-log';

/** Language id of SoaSE Files. */
const LANGUAGE_ID = 'soase';

/** Setting id whose change is applied to a running client without a restart. */
const TRACE_SETTING_ID = 'soase-validator.trace.server';

/** Dependencies of {@link registerActivation}. */
export interface ActivationDeps {
  /** The controller that receives the events. */
  readonly controller: ServerController;
  /** Debouncer that sends Server Setting changes. */
  readonly configSync: ConfigSync;
  /** Extension log. */
  readonly log: OutputLog;
}

/**
 * Registers the listeners that start the Server and keep it in sync, and
 * requests the first start.
 *
 * The first start is not awaited, so the caller returns before the Server is
 * ready. The reducer ignores an `AutoStart` that does not apply.
 *
 * @param deps Controller, debouncer and log.
 * @returns The listener registrations, for the caller to dispose.
 */
export function registerActivation(deps: ActivationDeps): vscode.Disposable[] {
  const { controller, configSync, log } = deps;

  const dispatch = (event: Parameters<ServerController['dispatch']>[0]): void => {
    controller.dispatch(event).catch((error: unknown) => {
      log.log('error', `Dispatching ${event.type} failed: ${describeError(error)}`);
    });
  };

  const disposables = [
    vscode.workspace.onDidGrantWorkspaceTrust(() => {
      dispatch({ type: 'TrustChanged', trusted: true });
      dispatch({ type: 'AutoStart' });
    }),
    vscode.workspace.onDidOpenTextDocument((document) => {
      if (document.languageId === LANGUAGE_ID && document.uri.scheme === 'file') {
        dispatch({ type: 'AutoStart' });
      }
    }),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (affectsServerSetting((id) => event.affectsConfiguration(id))) {
        configSync.notifyChange();
      }
      if (event.affectsConfiguration(TRACE_SETTING_ID)) {
        controller.setTrace(readExtensionSettings().trace);
      }
    }),
  ];

  dispatch({ type: 'AutoStart' });
  return disposables;
}

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
