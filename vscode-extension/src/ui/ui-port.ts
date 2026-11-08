/**
 * Adapter from the controller's `UiPort` to the VS Code UI modules.
 */

import type { UiPort } from '../lifecycle/ports';
import { openInstallDocs, openUvPathSetting, showServerError } from './notifications';
import type { OutputLog } from './output-log';
import type { StatusItem } from './status-item';

/**
 * Creates the `UiPort` the controller uses.
 *
 * @param log The Output Channel owner.
 * @param status The Status Item owner.
 * @returns A `UiPort` over the given log and status item.
 */
export function createUiPort(log: OutputLog, status: StatusItem): UiPort {
  return {
    setState: (state) => {
      status.setState(state);
    },
    log: (level, message) => {
      log.log(level, message);
    },
    notifyError: showServerError,
    openInstallDocs,
    openUvPathSetting,
    showOutput: () => {
      log.show();
    },
  };
}
