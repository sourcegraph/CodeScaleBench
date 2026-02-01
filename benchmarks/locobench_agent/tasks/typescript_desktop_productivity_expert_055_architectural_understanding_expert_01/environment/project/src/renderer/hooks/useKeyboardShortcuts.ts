```typescript
/**
 * PaletteFlow Studio — useKeyboardShortcuts hook
 * ------------------------------------------------
 * This hook lets React components declaratively register keyboard shortcuts
 * that execute Command-Pattern actions held in the app-wide CommandRegistry.
 *
 * Design goals:
 *  • Leverage React lifecycle → register/unregister automatically.
 *  • Normalise key combos across Windows/Linux/macOS.
 *  • Prevent interference with text inputs unless explicitly allowed.
 *  • Support runtime enable/disable (e.g. when opening modal dialogues).
 *  • Allow plugins to contribute their own shortcuts via composition.
 *
 * Usage example:
 *  useKeyboardShortcuts(
 *      [
 *          { combo: 'cmd+d', command: 'canvas.duplicateSelection' },
 *          { combo: 'shift+space', run: () => player.toggle() },
 *          { combo: 'esc', command: 'ui.dismissOverlay', allowInInput: true },
 *      ],
 *      { scope: 'canvas' }
 *  );
 */

import { useEffect, useRef } from 'react';
import { ipcRenderer } from 'electron';

import { CommandRegistry } from '../services/commands/CommandRegistry';
import { isEditableElement } from '../utils/dom/isEditableElement';
import { logger } from '../utils/logger';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ShortcutScope =
    | 'global'      // Always active
    | 'workspace'   // Active while any workspace window focused
    | 'canvas'      // Active while a canvas is focused/visible
    | 'nodeEditor'  // Active while a node editor is focused/visible
    | (string & {}); // Arbitrary plugin-defined scopes

export interface KeyboardShortcut {
    /** Normalised key combo, e.g. `cmd+k`, `ctrl+shift+r`, `alt+arrowup` */
    combo: string;

    /** Either the id of a registered command or an inline callback. */
    command?: string;
    run?: () => void | Promise<void>;

    /** Prevent default browser behaviour (default = true) */
    preventDefault?: boolean;

    /** Execute even if a text input / contentEditable is focused. */
    allowInInput?: boolean;

    /** Optional scope. Default = `global`. */
    scope?: ShortcutScope;
}

export interface UseKeyboardShortcutsOptions {
    /** Whether the shortcuts are currently enabled. */
    enabled?: boolean;

    /** Scope at which the shortcuts are applied; overrides each shortcut.scope. */
    scope?: ShortcutScope;

    /**
     * An optional abort signal. When triggered, all listeners are detached
     * regardless of component lifecycle (useful for hot-reload scenarios).
     */
    abortSignal?: AbortSignal;
}

// ---------------------------------------------------------------------------
// Key Combo Utilities
// ---------------------------------------------------------------------------

const PLATFORM_IS_MAC = /Mac|iPod|iPhone|iPad/.test(navigator.platform);

/**
 * Convert a KeyboardEvent into a normalised key combo string.
 * Example → 'cmd+shift+k'
 */
function eventToCombo(e: KeyboardEvent): string {
    const modifiers: string[] = [];

    if (e.ctrlKey && !e.metaKey)           modifiers.push('ctrl');
    if (e.altKey)                          modifiers.push('alt');
    if (e.shiftKey)                        modifiers.push('shift');
    if (e.metaKey)                         modifiers.push('cmd'); // macOS ⌘

    const mainKey = normaliseKey(e.key);

    // Only include the main key if it's not itself a modifier
    if (!['ctrl', 'alt', 'shift', 'cmd'].includes(mainKey)) {
        modifiers.push(mainKey);
    }

    return modifiers.join('+');
}

/**
 * Attempt to normalise key names across browsers/platforms.
 */
function normaliseKey(key: string): string {
    switch (key.toLowerCase()) {
        case ' ':              return 'space';
        case 'arrowup':        return 'arrowup';
        case 'arrowdown':      return 'arrowdown';
        case 'arrowleft':      return 'arrowleft';
        case 'arrowright':     return 'arrowright';
        default:               return key.toLowerCase();
    }
}

/**
 * Helper converting user-authored combos into canonical form so that
 * matching is case-insensitive & order-independent (`cmd+shift+k` === `SHIFT+CMD+K`)
 */
function normaliseCombo(combo: string): string {
    const items = combo
        .split('+')
        .map(p => p.trim().toLowerCase());

    const mainKey = items.find(k => !['ctrl', 'alt', 'shift', 'cmd'].includes(k));
    const modifiers = items
        .filter(k => k !== mainKey)
        .sort((a, b) => a.localeCompare(b)); // deterministic order

    return [...modifiers, mainKey!].join('+');
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useKeyboardShortcuts(
    shortcuts: KeyboardShortcut[],
    options: UseKeyboardShortcutsOptions = {}
): void {
    const {
        enabled = true,
        scope = undefined,
        abortSignal,
    } = options;

    // Store latest shortcuts ref so listener can access up-to-date callbacks
    const shortcutsRef = useRef<KeyboardShortcut[]>(shortcuts);
    shortcutsRef.current = shortcuts;

    useEffect(() => {
        if (!enabled) { return; }

        const onKeyDown = async (event: KeyboardEvent): Promise<void> => {
            let combo = eventToCombo(event);

            // Bail early if no combo produced (should not happen)
            if (!combo) return;

            combo = normaliseCombo(combo);

            // Ignore keystrokes while typing unless explicitly overridden
            if (
                !shortcutsRef.current.some(s => s.allowInInput && normaliseCombo(s.combo) === combo) &&
                isEditableElement(event.target as HTMLElement)
            ) {
                return;
            }

            for (const shortcut of shortcutsRef.current) {
                const effectiveScope = scope ?? shortcut.scope ?? 'global';
                if (!isScopeActive(effectiveScope)) continue;

                if (normaliseCombo(shortcut.combo) === combo) {
                    try {
                        if (shortcut.preventDefault !== false) {
                            event.preventDefault();
                        }

                        if (shortcut.run) {
                            await shortcut.run();
                        } else if (shortcut.command) {
                            // Resolve command via CommandRegistry
                            const registry = CommandRegistry.instance();
                            await registry.execute(shortcut.command);
                        } else {
                            logger.warn('[useKeyboardShortcuts] No action provided for combo:', combo);
                        }
                    } catch (err) {
                        logger.error('[useKeyboardShortcuts] Error executing shortcut:', {
                            combo,
                            err,
                        });
                        // Notify crash analytics without breaking UI
                        ipcRenderer.send('analytics:exception', {
                            domain: 'keyboardShortcut',
                            combo,
                            error: (err as Error).stack ?? String(err),
                        });
                    }
                    break; // Stop at first match
                }
            }
        };

        window.addEventListener('keydown', onKeyDown, { passive: false });

        const abortHandler = (): void => {
            window.removeEventListener('keydown', onKeyDown);
        };

        if (abortSignal) {
            abortSignal.addEventListener('abort', abortHandler);
        }

        return () => {
            window.removeEventListener('keydown', onKeyDown);
            if (abortSignal) {
                abortSignal.removeEventListener('abort', abortHandler);
            }
        };
    }, [enabled, scope, abortSignal]);
}

// ---------------------------------------------------------------------------
// Scope Helpers
// ---------------------------------------------------------------------------

/**
 * Determine whether a given scope is active in the current renderer context.
 * In the future this can consult application state; for now we keep it simple.
 */
function isScopeActive(scope: ShortcutScope): boolean {
    switch (scope) {
        case 'global':
            return true;

        case 'workspace':
            // Workspace is active as long as a workspace window is focused.
            return document.hasFocus();

        case 'canvas':
            return document.activeElement?.closest?.('[data-paletteflow-canvas]') != null;

        case 'nodeEditor':
            return document.activeElement?.closest?.('[data-paletteflow-nodeeditor]') != null;

        default:
            // Allow plugins to register scope resolvers via IPC/Context in future.
            const detail = { scope };
            const customEvt = new CustomEvent<boolean>('PF:isScopeActive', {
                detail,
                cancelable: true,
            });
            window.dispatchEvent(customEvt);
            return (customEvt as any).returnValue ?? true;
    }
}
```
