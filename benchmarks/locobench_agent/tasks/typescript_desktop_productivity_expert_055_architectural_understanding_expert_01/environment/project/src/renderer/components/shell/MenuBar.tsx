```typescript
/***************************************************************************************************
 * PaletteFlow Studio – Menu Bar (Renderer)
 *
 * This component is *not* visible UI.  It lives in the renderer process and is responsible for
 * instructing the main‐process to build / rebuild the native application menu whenever:
 *   • the application starts
 *   • user preferences relevant to the menu change (e.g. language, theme, keymap)
 *   • plugins register or unregister menu contributions
 *
 * The actual native menu is constructed in the *main* process for security reasons; the renderer
 * communicates through a context-isolated IPC bridge exposed on `window.paletteflow.menu`.
 *
 * ──────────────────────────────────────────────────────────────────────────────────────────────── */

import React, { useContext, useEffect, useMemo } from 'react';
import { v4 as uuid } from 'uuid';

import { PluginRegistryContext } from '../providers/PluginRegistryProvider';
import { PreferencesContext } from '../providers/PreferencesProvider';
import { CommandDispatcherContext } from '../providers/CommandDispatcherProvider';
import { logger } from '../../utils/logger';

/* ╔══════════════════════════════════════════════════════════════════════════════════════════════╗
 * ║                                   Type Declarations                                          ║
 * ╚══════════════════════════════════════════════════════════════════════════════════════════════╝ */

type CommandId = string;

/**
 * Simple declarative representation of a menu contribution, agnostic of Electron specifics so that
 * *domain* and *plugin* code never has to import Electron types.
 */
export interface MenuContribution {
  id?: string; // <–––– optional stable identifier (used when a plugin wants to patch an existing item)
  label: string;
  accelerator?: string;
  action?: CommandId | (() => void);
  enabled?: boolean;
  role?: Electron.MenuItemConstructorOptions['role'];
  submenu?: MenuContribution[];
  orderHint?: number; // lower = further to the left / top
}

/**
 * Globally exposed (via preload) contract for talking to the main process.
 */
declare global {
  // eslint-disable-next-line @typescript-eslint/consistent-type-definitions
  interface Window {
    paletteflow?: {
      menu: {
        /**
         * Replaces the current native application menu with the provided *serialized* template.
         * The renderer side only deals with vanilla JSON-serializable data structures.
         */
        setTemplate(
          template: SerializedMenuContribution[],
        ): Promise<void>;
      };
    };
  }
}

/**
 * The data structure that the main process understands (no functions, only primitives / arrays).
 * Functions are replaced with IPC command ids so that the main process can dispatch back to the
 * renderer when a menu item is invoked.
 */
type SerializedMenuContribution = Omit<MenuContribution, 'action' | 'submenu' | 'enabled'> & {
  enabled?: boolean;
  action?:
    | { type: 'ipc'; command: CommandId }                 // link to command dispatcher
    | { type: 'noop' }                                    // placeholder, non-interactive
  submenu?: SerializedMenuContribution[];
};

/* ╔══════════════════════════════════════════════════════════════════════════════════════════════╗
 * ║                                  Helper / Utility Logic                                     ║
 * ╚══════════════════════════════════════════════════════════════════════════════════════════════╝ */

/**
 * Recursively turns an in-memory {@link MenuContribution} into a
 * {@link SerializedMenuContribution}, registering any inline callbacks in the command dispatcher so
 * that they can be invoked later across the IPC boundary.
 */
function serializeMenu(
  contribution: MenuContribution,
  registerCommand: (fn: () => void) => CommandId,
): SerializedMenuContribution {
  const {
    submenu,
    action,
    ...rest
  } = contribution;

  let serializedAction: SerializedMenuContribution['action'] | undefined;

  if (action === undefined) {
    serializedAction = undefined;
  } else if (typeof action === 'string') {
    serializedAction = { type: 'ipc', command: action };
  } else if (typeof action === 'function') {
    serializedAction = { type: 'ipc', command: registerCommand(action) };
  } else {
    serializedAction = { type: 'noop' };
  }

  return {
    ...rest,
    action: serializedAction,
    submenu: submenu?.map((sub) => serializeMenu(sub, registerCommand)),
  };
}

/* ╔══════════════════════════════════════════════════════════════════════════════════════════════╗
 * ║                                    React Component                                          ║
 * ╚══════════════════════════════════════════════════════════════════════════════════════════════╝ */

const CORE_MENU: MenuContribution[] = [
  {
    label: 'File',
    submenu: [
      { label: 'New Canvas', accelerator: 'CmdOrCtrl+N', action: 'canvas.new' },
      { label: 'Open…', accelerator: 'CmdOrCtrl+O', action: 'canvas.open' },
      { label: 'Save', accelerator: 'CmdOrCtrl+S', action: 'canvas.save' },
      { label: 'Save As…', accelerator: 'CmdOrCtrl+Shift+S', action: 'canvas.saveAs' },
      { label: 'Export…', accelerator: 'CmdOrCtrl+E', action: 'canvas.export' },
      { label: 'Close Window', role: 'close' },
    ],
  },
  {
    label: 'Edit',
    submenu: [
      { role: 'undo', label: 'Undo' },
      { role: 'redo', label: 'Redo' },
      { type: 'separator' } as unknown as MenuContribution,
      { role: 'cut', label: 'Cut' },
      { role: 'copy', label: 'Copy' },
      { role: 'paste', label: 'Paste' },
      { label: 'Delete', accelerator: 'Backspace', action: 'selection.delete' },
    ],
  },
  {
    label: 'View',
    submenu: [
      { role: 'togglefullscreen', label: 'Toggle Full Screen' },
      { role: 'zoomIn', label: 'Zoom In' },
      { role: 'zoomOut', label: 'Zoom Out' },
      { type: 'separator' } as unknown as MenuContribution,
      { label: 'Toggle DevTools', accelerator: 'Alt+CmdOrCtrl+I', action: 'debug.devTools' },
    ],
  },
  {
    label: 'Help',
    submenu: [
      {
        label: 'PaletteFlow Documentation',
        action: () => window.open('https://docs.paletteflow.app', '_blank', 'noopener'),
      },
      {
        label: 'Report an Issue…',
        action: () => window.open('https://github.com/paletteflow/studio/issues', '_blank', 'noopener'),
      },
      { type: 'separator' } as unknown as MenuContribution,
      { label: 'About PaletteFlow Studio', action: 'app.about' },
    ],
  },
];

/**
 * MenuBar mounts once (per window) and keeps the native application menu synchronized with React
 * state & plugin registry.  Returns `null` because it doesn't render anything on screen.
 */
export const MenuBar: React.FC = () => {
  const plugins = useContext(PluginRegistryContext);
  const preferences = useContext(PreferencesContext);
  const commandDispatcher = useContext(CommandDispatcherContext);

  /* ─────────────────────────── Command Registration ───────────────────────────── */

  /**
   * Registers a one-shot function in the command dispatcher that will be executed when the main
   * process tells us the menu item was invoked.
   */
  const registerDynamicCommand = (fn: () => void): CommandId => {
    const cmdId = `dynamic.menu.${uuid()}`;
    commandDispatcher.register(cmdId, fn);

    return cmdId;
  };

  /* ────────────────────────────── Menu Assembly ───────────────────────────────── */

  /**
   * Merge core menu with contributions from every loaded plugin.
   */
  const mergedMenu: MenuContribution[] = useMemo(() => {
    const contributionsFromPlugins = plugins.getMenuContributions?.() ?? [];

    /* Sort by orderHint so plugins can determine position deterministically */
    const sorted = [...contributionsFromPlugins].sort(
      (a, b) => (a.orderHint ?? 0) - (b.orderHint ?? 0),
    );

    return [...CORE_MENU, ...sorted];
  }, [plugins]);

  /**
   * After every render that affects the menu (preferences, plugin changes, …) push the updated
   * template over to the main process.
   */
  useEffect(() => {
    let disposed = false;

    (async () => {
      try {
        const serialized = mergedMenu.map((item) =>
          serializeMenu(item, registerDynamicCommand),
        );

        await window.paletteflow?.menu.setTemplate(serialized);

        logger.debug('[MenuBar] Native menu updated', { serialized });
      } catch (error) /* istanbul ignore next */ {
        if (!disposed) {
          logger.error('[MenuBar] Failed to set native menu', error as Error);
        }
      }
    })();

    return () => {
      disposed = true;
    };
  }, [mergedMenu, preferences.locale, preferences.keymap]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ════════════════════════════════════════════════════════════════════════════ */
  return null;
};

export default MenuBar;
```
