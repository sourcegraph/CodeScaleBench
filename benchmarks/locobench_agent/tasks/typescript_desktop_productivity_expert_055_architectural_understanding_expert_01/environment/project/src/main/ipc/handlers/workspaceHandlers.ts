```typescript
/* PaletteFlow Studio
 * File: src/main/ipc/handlers/workspaceHandlers.ts
 *
 * IPC handlers related to Workspace lifecycle (create, open, save, export, etc.).
 *
 * The handlers are registered once during app bootstrap from main/index.ts
 * and translate renderer-level requests into domain use-case executions.
 *
 * All communication happens through Electron’s IPC “invoke/handle” channel
 * to guarantee request/response semantics as opposed to fire-and-forget.
 */

import { ipcMain, IpcMainInvokeEvent, BrowserWindow } from 'electron';
import { v4 as uuid } from 'uuid';

import { CreateWorkspaceUseCase } from '../../domain/useCases/workspace/CreateWorkspaceUseCase';
import { OpenWorkspaceUseCase } from '../../domain/useCases/workspace/OpenWorkspaceUseCase';
import { SaveWorkspaceUseCase } from '../../domain/useCases/workspace/SaveWorkspaceUseCase';
import { ExportWorkspaceUseCase } from '../../domain/useCases/workspace/ExportWorkspaceUseCase';
import { ApplyThemeUseCase } from '../../domain/useCases/theme/ApplyThemeUseCase';

import { RecentWorkspacesRepository } from '../../infrastructure/repositories/RecentWorkspacesRepository';
import { Logger } from '../../infrastructure/logging/Logger';
import { mainEventBus, MainEventTopic } from '../eventBus';

const log = Logger.child({ module: 'ipc/workspaceHandlers' });

/* -------------------------------------------------------------------------- */
/*                                IPC CHANNELS                                */
/* -------------------------------------------------------------------------- */

const CHANNEL = {
  CREATE: 'workspace:create',
  OPEN: 'workspace:open',
  SAVE: 'workspace:save',
  EXPORT: 'workspace:export',
  APPLY_THEME: 'workspace:apply-theme',
  LIST_RECENT: 'workspace:list-recent',
} as const;

/* -------------------------------------------------------------------------- */
/*                               SAVE QUEUE MAP                               */
/* -------------------------------------------------------------------------- */

/**
 * A simple Map to serialise SAVE operations per workspace.  
 * Prevents clobbering the filesystem when a user mashes CMD+S repeatedly.
 */
const saveQueue: Map<string, Promise<void>> = new Map();

/* -------------------------------------------------------------------------- */
/*                             HANDLER REGISTRATION                           */
/* -------------------------------------------------------------------------- */

/**
 * Register all Workspace-related IPC handlers.
 * Must be called from the main process before creating BrowserWindows.
 */
export function registerWorkspaceHandlers(): void {
  ipcMain.handle(CHANNEL.CREATE, createWorkspace);
  ipcMain.handle(CHANNEL.OPEN, openWorkspace);
  ipcMain.handle(CHANNEL.SAVE, saveWorkspace);
  ipcMain.handle(CHANNEL.EXPORT, exportWorkspace);
  ipcMain.handle(CHANNEL.APPLY_THEME, applyTheme);
  ipcMain.handle(CHANNEL.LIST_RECENT, listRecentWorkspaces);

  log.info('Workspace IPC handlers registered');
}

/* -------------------------------------------------------------------------- */
/*                                 HANDLERS                                   */
/* -------------------------------------------------------------------------- */

async function createWorkspace(
  event: IpcMainInvokeEvent,
  payload: { name: string; directory?: string },
): Promise<{ workspaceId: string }> {
  const { name, directory } = payload;
  const correlationId = uuid();

  log.debug({ correlationId, name, directory }, 'Creating workspace');

  try {
    const useCase = new CreateWorkspaceUseCase();
    const workspace = await useCase.execute({ name, directory });

    await RecentWorkspacesRepository.push(workspace);

    sendEventToWindow(event, MainEventTopic.WorkspaceCreated, { workspace });

    return { workspaceId: workspace.id };
  } catch (err) {
    log.error({ err, correlationId }, 'Failed to create workspace');
    throw serializeError(err);
  }
}

async function openWorkspace(
  event: IpcMainInvokeEvent,
  payload: { path: string },
): Promise<{ workspaceId: string }> {
  const { path } = payload;
  const correlationId = uuid();

  log.debug({ correlationId, path }, 'Opening workspace');

  try {
    const useCase = new OpenWorkspaceUseCase();
    const workspace = await useCase.execute({ path });

    await RecentWorkspacesRepository.push(workspace);

    sendEventToWindow(event, MainEventTopic.WorkspaceOpened, { workspace });

    // Broadcast to plugin subsystem
    mainEventBus.publish(MainEventTopic.WorkspaceOpened, { workspace });

    return { workspaceId: workspace.id };
  } catch (err) {
    log.error({ err, correlationId }, 'Failed to open workspace');
    throw serializeError(err);
  }
}

async function saveWorkspace(
  _event: IpcMainInvokeEvent,
  payload: { workspaceId: string },
): Promise<void> {
  const { workspaceId } = payload;

  // Chain saves sequentially per workspace
  const queued = saveQueue.get(workspaceId) ?? Promise.resolve();

  const next = queued
    .catch(() => {
      /* swallow previous errors to not stop the chain */
    })
    .then(async () => {
      const useCase = new SaveWorkspaceUseCase();
      await useCase.execute({ workspaceId });
      log.info({ workspaceId }, 'Workspace saved');
    })
    .finally(() => {
      // Remove queue entry to allow GC for inactive workspaces
      if (saveQueue.get(workspaceId) === next) {
        saveQueue.delete(workspaceId);
      }
    });

  saveQueue.set(workspaceId, next);

  return next;
}

async function exportWorkspace(
  _event: IpcMainInvokeEvent,
  payload: { workspaceId: string; format: 'zip' | 'json'; outputPath?: string },
): Promise<{ exportedPath: string }> {
  const { workspaceId, format, outputPath } = payload;
  const correlationId = uuid();

  log.debug({ correlationId, workspaceId, format }, 'Exporting workspace');

  try {
    const useCase = new ExportWorkspaceUseCase();
    const exportedPath = await useCase.execute({ workspaceId, format, outputPath });

    log.info({ workspaceId, exportedPath }, 'Workspace exported');

    return { exportedPath };
  } catch (err) {
    log.error({ err, correlationId }, 'Failed to export workspace');
    throw serializeError(err);
  }
}

async function applyTheme(
  event: IpcMainInvokeEvent,
  payload: { workspaceId: string; themeId: string },
): Promise<void> {
  const { workspaceId, themeId } = payload;
  const correlationId = uuid();

  log.debug({ correlationId, workspaceId, themeId }, 'Applying theme');

  try {
    const useCase = new ApplyThemeUseCase();
    await useCase.execute({ workspaceId, themeId });

    sendEventToWindow(event, MainEventTopic.ThemeApplied, { workspaceId, themeId });
  } catch (err) {
    log.error({ err, correlationId }, 'Failed to apply theme');
    throw serializeError(err);
  }
}

async function listRecentWorkspaces(): Promise<
  Array<{ id: string; name: string; path: string; lastOpened: number }>
> {
  return RecentWorkspacesRepository.list();
}

/* -------------------------------------------------------------------------- */
/*                                UTILITIES                                   */
/* -------------------------------------------------------------------------- */

/**
 * Send a domain event payload to the BrowserWindow that originated the IPC call.
 */
function sendEventToWindow(
  event: IpcMainInvokeEvent,
  topic: MainEventTopic,
  payload: unknown,
): void {
  const window = BrowserWindow.fromWebContents(event.sender);
  if (!window || window.isDestroyed()) {
    log.warn({ topic }, 'Unable to locate renderer window for event dispatch');
    return;
  }
  window.webContents.send(topic, payload);
}

/**
 * Basic error serialisation so the renderer can `instanceof` the original error name.
 * Electron’s structured clone strips out prototypes; we manually preserve them.
 */
function serializeError(err: unknown): Error {
  if (err instanceof Error) {
    const serialised = new Error(err.message);
    (serialised as any).name = err.name;
    (serialised as any).stack = err.stack;
    return serialised;
  }
  return new Error('Unknown error');
}
```