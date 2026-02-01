```typescript
/***************************************************************************************************
 * PaletteFlow Studio – Renderer Store
 *
 * This is the single source-of-truth Redux store that powers the renderer (web) context.  All UI
 * components subscribe to this store; business-level changes are executed through dispatched
 * commands that eventually hit Clean-Architecture use-cases in the main process via IPC.
 *
 * The store supports:
 *   • Dynamic reducer injection for palette plugins
 *   • Cross-window action broadcasting (BroadcastChannel + Electron IPC)
 *   • Automatic preference persistence to disk
 *   • Crash-resilient analytics middleware
 *
 * Author: PaletteFlow Core Team
 **************************************************************************************************/

import {
  configureStore,
  combineReducers,
  Reducer,
  Middleware,
  PayloadAction,
  AnyAction,
  ThunkDispatch,
  isPlain,
  createListenerMiddleware,
} from '@reduxjs/toolkit';
import { ipcRenderer, IpcRendererEvent } from 'electron';
import debounce from 'lodash.debounce';
import { v4 as uuid } from 'uuid';

import workspaceReducer, {
  WorkspaceState,
} from './slices/workspaceSlice';
import uiReducer, { UIState } from './slices/uiSlice';
import pluginHubReducer, {
  PluginHubState,
} from './slices/pluginHubSlice';

////////////////////////////////////////////////////////////////////////////////
// Types
////////////////////////////////////////////////////////////////////////////////

/** Root state exposed to React hooks and other consumers */
export interface RootState {
  workspace: WorkspaceState;
  ui: UIState;
  pluginHub: PluginHubState;
  // Dynamically injected reducers are stitched into this map.
  [dynamicKey: string]: unknown;
}

/** Type for the Redux dispatch including thunks */
export type AppDispatch = ThunkDispatch<RootState, unknown, AnyAction>;

/** Extended window object (preload exposes the uuid) */
declare global {
  // eslint-disable-next-line @typescript-eslint/consistent-type-definitions
  interface Window {
    __WINDOW_ID__: string;
  }
}

////////////////////////////////////////////////////////////////////////////////
// Dynamic reducer registry
////////////////////////////////////////////////////////////////////////////////

type DynamicReducers = Record<string, Reducer>;

const staticReducers = {
  workspace: workspaceReducer,
  ui: uiReducer,
  pluginHub: pluginHubReducer,
};

const dynamicReducers: DynamicReducers = {};
let combinedReducer = combineReducers<RootState>({
  ...staticReducers,
});

/**
 * Attaches a new reducer under a supplied key.
 * Used by plugins to expand the global state tree.
 *
 * @param key   Unique slice key
 * @param reducer The reducer function
 * @returns Unregister callback
 */
export function registerDynamicReducer(
  key: string,
  reducer: Reducer
): () => void {
  if (staticReducers[key] || dynamicReducers[key]) {
    console.warn(
      `[store] Attempt to register duplicate reducer "${key}". Skipped.`
    );
    return () => undefined;
  }

  dynamicReducers[key] = reducer;
  combinedReducer = combineReducers<RootState>({
    ...staticReducers,
    ...dynamicReducers,
  });

  store.replaceReducer(combinedReducer);

  return () => {
    delete dynamicReducers[key];
    combinedReducer = combineReducers<RootState>({
      ...staticReducers,
      ...dynamicReducers,
    });
    store.replaceReducer(combinedReducer);
  };
}

////////////////////////////////////////////////////////////////////////////////
// Persistence helpers
////////////////////////////////////////////////////////////////////////////////

const PERSIST_KEY = 'pf.renderer.state.v1';
const PERSIST_DEBOUNCE_MS = 750;

function loadPersistedState(): Partial<RootState> | undefined {
  try {
    const raw = localStorage.getItem(PERSIST_KEY);
    if (!raw) return undefined;
    return JSON.parse(raw);
  } catch (err) {
    console.error('[store] Failed to parse persisted state:', err);
    return undefined;
  }
}

const persistStateDebounced = debounce((state: RootState) => {
  try {
    localStorage.setItem(PERSIST_KEY, JSON.stringify(state));
  } catch (err) {
    // Storage quota may be exceeded in rare cases. We swallow the error
    // because persistence is a best-effort operation.
    console.warn('[store] Unable to persist state:', err);
  }
}, PERSIST_DEBOUNCE_MS);

////////////////////////////////////////////////////////////////////////////////
// Middleware
////////////////////////////////////////////////////////////////////////////////

/**
 * Bridges Redux actions across Electron windows & processes.
 */
const crossWindowSyncMiddleware: Middleware<
  {}, // no extra arg
  RootState
> = (api) => (next) => (action: AnyAction) => {
  const result = next(action);

  // Only broadcast certain action types or plain objects to avoid needless traffic.
  if (isPlain(action) && action.meta?.broadcast !== false) {
    try {
      const windowId = window.__WINDOW_ID__ ?? 'unknown';
      ipcRenderer.send('renderer:action-broadcast', {
        windowId,
        action,
      });
    } catch (err) {
      console.error('[store] Unable to broadcast action:', err);
    }
  }
  return result;
};

/**
 * Collects non-fatal errors and sends them to the crash analytics service.
 */
const crashAnalyticsMiddleware: Middleware<{}, RootState> =
  () => (next) => (action) => {
    try {
      return next(action);
    } catch (err) {
      // eslint-disable-next-line @typescript-eslint/no-unsafe-argument
      ipcRenderer.invoke('analytics:renderer-error', {
        actionType: action.type,
        message: (err as Error).message,
        stack: (err as Error).stack,
      });
      throw err; // rethrow to not hide original error
    }
  };

/**
 * Listener middleware used for side-effects that don't belong in reducers.
 */
const listenerMiddleware = createListenerMiddleware();

/* Example effect: persist workspace name whenever it changes */
listenerMiddleware.startListening({
  predicate: (action, currentState, previousState) =>
    previousState?.workspace.name !== currentState.workspace.name,
  effect: async (_, listenerApi) => {
    const { workspace } = listenerApi.getState() as RootState;
    // Persist just the workspace slice
    persistStateDebounced({ workspace } as RootState);
  },
});

////////////////////////////////////////////////////////////////////////////////
// Store construction
////////////////////////////////////////////////////////////////////////////////

const preloadedState = loadPersistedState();

export const store = configureStore({
  reducer: combinedReducer,
  middleware: (getDefaultMiddleware) => {
    const defaultMw = getDefaultMiddleware({
      serializableCheck: {
        // Ignore non-serializable values from Electron IPC
        isSerializable: (value) =>
          isPlain(value) ||
          ArrayBuffer.isView(value) ||
          value instanceof ArrayBuffer,
      },
    });
    return defaultMw
      .prepend(listenerMiddleware.middleware)
      .concat(crossWindowSyncMiddleware, crashAnalyticsMiddleware);
  },
  devTools: process.env.NODE_ENV !== 'production',
  preloadedState,
});

////////////////////////////////////////////////////////////////////////////////
// IPC listeners (back-channel)
////////////////////////////////////////////////////////////////////////////////

/**
 * Receives broadcasted actions from the main process and re-dispatches them
 * locally.  This keeps multiple renderer windows in sync.
 */
ipcRenderer.on(
  'main:action-broadcast',
  (_: IpcRendererEvent, { originId, action }) => {
    // Avoid echoing back to original window
    if (originId !== window.__WINDOW_ID__) {
      store.dispatch(action as AnyAction);
    }
  }
);

/**
 * Hot-replacement: The main process can request a full state replace
 * (e.g. after loading a workspace file).
 */
ipcRenderer.on('main:state-replace', (_: IpcRendererEvent, nextState) => {
  store.dispatch({
    type: 'INTERNAL/STATE_REPLACE',
    payload: nextState,
    meta: { broadcast: false },
  });
});

////////////////////////////////////////////////////////////////////////////////
// Utility helpers
////////////////////////////////////////////////////////////////////////////////

/**
 * Shorthand hook consumers may use instead of store.getState()
 */
export const select = <T>(fn: (state: RootState) => T): T =>
  fn(store.getState());

/**
 * Unique window ID used for cross-window broadcasting.
 * Generated here if the preload script did not set one yet.
 */
if (!window.__WINDOW_ID__) {
  // eslint-disable-next-line functional/immutable-data
  window.__WINDOW_ID__ = uuid();
}

/***************************************************************************************************
 * End of renderer/state/store.ts
 **************************************************************************************************/
```