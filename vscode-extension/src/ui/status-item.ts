/**
 * Owner of the single Status Item.
 */

import * as vscode from 'vscode';

import { statusItemLabel } from '../format/status-text';
import type { ServerState } from '../lifecycle/lifecycle';

/** Language identifier of SoaSE Files. */
const SOASE_LANGUAGE_ID = 'soase';

/** Command run when the user selects the Status Item. */
export const SHOW_STATUS_COMMAND = 'soase-validator.showStatus';

/** Owner of the single Status Item. */
export interface StatusItem {
  /** Updates text and background synchronously. */
  setState(state: ServerState): void;
  /** Disposes the item and its editor listener. */
  dispose(): void;
}

/**
 * Creates the Status Item, initially in the `stopped` state.
 *
 * @returns The item owner. Call it once per window.
 */
export function createStatusItem(): StatusItem {
  const item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left);
  item.name = 'SoaSE Validator';
  item.command = SHOW_STATUS_COMMAND;

  function updateVisibility(editor: vscode.TextEditor | undefined): void {
    if (editor?.document.languageId === SOASE_LANGUAGE_ID) {
      item.show();
    } else {
      item.hide();
    }
  }

  function setState(state: ServerState): void {
    item.text = statusItemLabel(state);
    item.backgroundColor =
      state === 'error' ? new vscode.ThemeColor('statusBarItem.errorBackground') : undefined;
  }

  setState('stopped');
  updateVisibility(vscode.window.activeTextEditor);
  const listener = vscode.window.onDidChangeActiveTextEditor(updateVisibility);

  return {
    setState,
    dispose(): void {
      listener.dispose();
      item.dispose();
    },
  };
}
