/**
 * Registration of the four Extension commands.
 */

import * as vscode from 'vscode';

import { formatStatus } from './format/status-text';
import type { ServerController } from './lifecycle/server-controller';
import type { UiPort } from './lifecycle/ports';

/** Dependencies of {@link registerCommands}. */
export interface CommandDeps {
  /** The controller that receives restart and stop requests. */
  readonly controller: ServerController;
  /** Used to reveal the Output Channel. */
  readonly ui: UiPort;
}

/**
 * Registers `restartServer`, `stopServer`, `showOutput` and `showStatus`.
 *
 * Restart re-sends settings by starting a new process: the controller reads
 * settings again at each start.
 *
 * @param deps Controller and UI port.
 * @returns The command registrations, for the caller to dispose.
 */
export function registerCommands(deps: CommandDeps): vscode.Disposable[] {
  const { controller, ui } = deps;
  return [
    vscode.commands.registerCommand('soase-validator.restartServer', () =>
      controller.dispatch({ type: 'RestartRequested' }),
    ),
    vscode.commands.registerCommand('soase-validator.stopServer', () =>
      controller.dispatch({ type: 'StopRequested' }),
    ),
    vscode.commands.registerCommand('soase-validator.showOutput', () => {
      ui.showOutput();
    }),
    vscode.commands.registerCommand('soase-validator.showStatus', async () => {
      await vscode.window.showInformationMessage(formatStatus(controller.snapshot()), {
        modal: false,
      });
    }),
  ];
}
