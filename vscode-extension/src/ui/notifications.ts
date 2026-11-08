/**
 * Error notifications and the actions they offer.
 */

import * as vscode from 'vscode';

import type { NotifyKind } from '../lifecycle/lifecycle';
import type { NotifyAction, NotifyDetails } from '../lifecycle/ports';

/** The uv installation documentation page. */
export const UV_INSTALL_DOCS_URL = 'https://docs.astral.sh/uv/getting-started/installation/';

/** Setting the "Set uvPath" action filters the settings editor to. */
const UV_PATH_SETTING_ID = 'soase-validator.uvPath';

/** Button label per action. */
const ACTION_LABELS: Readonly<Record<NotifyAction, string>> = {
  'open-install-docs': 'Open install instructions',
  'set-uv-path': 'Set uvPath',
  'show-output': 'Show output',
  'restart-server': 'Restart server',
};

/**
 * Shows one error notification with the given buttons.
 *
 * @param _kind Kind of failure; the controller already chose the text and actions.
 * @param details Message and extra lines to display.
 * @param actions Buttons to offer, in order.
 * @returns The chosen action, or undefined when the user dismisses it.
 */
export async function showServerError(
  _kind: NotifyKind,
  details: NotifyDetails,
  actions: readonly NotifyAction[],
): Promise<NotifyAction | undefined> {
  const text = [details.message, ...details.lines].join('\n');
  const labels = actions.map((action) => ACTION_LABELS[action]);
  const chosen = await vscode.window.showErrorMessage(text, ...labels);
  return actions.find((action) => ACTION_LABELS[action] === chosen);
}

/**
 * Opens the uv installation documentation with `env.openExternal`.
 *
 * @returns Resolves when the request has been handed to VS Code.
 */
export async function openInstallDocs(): Promise<void> {
  await vscode.env.openExternal(vscode.Uri.parse(UV_INSTALL_DOCS_URL));
}

/**
 * Runs `workbench.action.openSettings` filtered to `soase-validator.uvPath`.
 *
 * @returns Resolves when the command has run.
 */
export async function openUvPathSetting(): Promise<void> {
  await vscode.commands.executeCommand('workbench.action.openSettings', UV_PATH_SETTING_ID);
}
