```typescript
/**
 * PaletteFlow Studio – Main Process
 * src/main/ipc/handlers/fileSystemHandlers.ts
 *
 * Centralised IPC wiring for all file-system related operations coming
 * from renderer windows (Canvas, Settings, Plugin Manager, …).
 *
 * The handler layer’s responsibility is to:
 *   1. Validate un-trusted payloads coming over IPC.
 *   2. Translate them into domain use-cases / infrastructure services.
 *   3. Serialise domain responses back to primitives understood by
 *      the renderer.
 *
 * NOTE: No Electron renderer APIs must be imported from this file.
 */

import { ipcMain, dialog, BrowserWindow } from 'electron';
import { promises as fs, createWriteStream, watch, FSWatcher } from 'fs';
import path from 'path';
import os from 'os';
import crypto from 'crypto';

import { ExportWorkspaceUseCase } from '../../core/useCases/workspace/ExportWorkspaceUseCase';
import { ImportWorkspaceUseCase } from '../../core/useCases/workspace/ImportWorkspaceUseCase';
import { SaveWorkspaceSnapshotUseCase } from '../../core/useCases/workspace/SaveWorkspaceSnapshotUseCase';

import logger from '../../infrastructure/logger';
import { z } from 'zod';

/* -------------------------------------------------------------------------- */
/*                               IPC CHANNELS                                 */
/* -------------------------------------------------------------------------- */

const CHANNELS = {
  OPEN_DIALOG: 'fileSystem:open-dialog',
  SAVE_WORKSPACE: 'fileSystem:save-workspace',
  EXPORT_WORKSPACE: 'fileSystem:export-workspace',
  READ_DIR: 'fileSystem:read-dir',
  CREATE_TEMP_DIR: 'fileSystem:create-temp-dir',
  WATCH_FILE: 'fileSystem:watch-file',
  UNWATCH_FILE: 'fileSystem:unwatch-file',
} as const;

type Channel = (typeof CHANNELS)[keyof typeof CHANNELS];

/* -------------------------------------------------------------------------- */
/*                               HELPER TYPES                                 */
/* -------------------------------------------------------------------------- */

interface FileWatchDescriptor {
  watcher: FSWatcher;
  window: BrowserWindow;
}

const activeWatchers = new Map<string, FileWatchDescriptor>();

/* -------------------------------------------------------------------------- */
/*                         PAYLOAD VALIDATION (Zod)                           */
/* -------------------------------------------------------------------------- */

const SaveWorkspacePayload = z.object({
  filePath: z.string().min(1),
  snapshot: z.string().min(1), // JSON stringified snapshot
});

const ExportWorkspacePayload = z.object({
  workspaceId: z.string().uuid(),
  destination: z.string().min(1),
});

const ReadDirPayload = z.object({
  dirPath: z.string().min(1),
  depth: z.number().int().min(0).max(5).optional().default(1),
});

const WatchFilePayload = z.object({
  filePath: z.string().min(1),
});

/* -------------------------------------------------------------------------- */
/*                            SECURE PATH HELPERS                             */
/* -------------------------------------------------------------------------- */

/**
 * Prevent path traversal by resolving & comparing with root
 */
function safelyResolve(userPath: string): string {
  const resolved = path.resolve(userPath);
  if (!resolved.startsWith(os.homedir())) {
    // For this product we sandbox IO to the user’s home directory.
    throw new Error('Attempt to access a path outside the sandbox.');
  }
  return resolved;
}

/* -------------------------------------------------------------------------- */
/*                             HANDLER REGISTRATION                           */
/* -------------------------------------------------------------------------- */

export function registerFileSystemHandlers(): void {
  /* ---------------------------- OPEN SYSTEM DIALOG --------------------------- */
  ipcMain.handle(CHANNELS.OPEN_DIALOG, async (_, opts: Electron.OpenDialogOptions) => {
    const window = BrowserWindow.getFocusedWindow() ?? undefined;
    const result = await dialog.showOpenDialog(window, {
      ...opts,
      properties: opts?.properties ?? ['openFile', 'createDirectory', 'promptToCreate', 'dontAddToRecent'],
    });

    return {
      canceled: result.canceled,
      filePaths: result.filePaths.map((p) => path.normalize(p)),
    };
  });

  /* ---------------------------- SAVE WORKSPACE ------------------------------- */
  ipcMain.handle(CHANNELS.SAVE_WORKSPACE, async (_, payload: unknown) => {
    const { filePath, snapshot } = SaveWorkspacePayload.parse(payload);

    const safePath = safelyResolve(filePath);

    try {
      await fs.mkdir(path.dirname(safePath), { recursive: true });
      await fs.writeFile(safePath, snapshot, { encoding: 'utf8' });

      // Optionally invoke domain use-case for side-effects (analytics, hooks)
      await SaveWorkspaceSnapshotUseCase.execute({ filePath: safePath });

      return { success: true };
    } catch (err) {
      logger.error('Failed to save workspace', err);
      return { success: false, error: (err as Error).message };
    }
  });

  /* ---------------------------- EXPORT WORKSPACE ----------------------------- */
  ipcMain.handle(CHANNELS.EXPORT_WORKSPACE, async (_, payload: unknown) => {
    const { workspaceId, destination } = ExportWorkspacePayload.parse(payload);
    const safeDest = safelyResolve(destination);

    try {
      await ExportWorkspaceUseCase.execute({ workspaceId, destination: safeDest });
      return { success: true };
    } catch (err) {
      logger.error('Failed to export workspace', err);
      return { success: false, error: (err as Error).message };
    }
  });

  /* ------------------------------ READ DIRECTORY ----------------------------- */
  ipcMain.handle(CHANNELS.READ_DIR, async (_, payload: unknown) => {
    const { dirPath, depth } = ReadDirPayload.parse(payload);
    const safeDir = safelyResolve(dirPath);

    async function readRecursively(currentPath: string, currentDepth: number): Promise<Record<string, any>> {
      const stats = await fs.stat(currentPath);
      if (!stats.isDirectory() || currentDepth === 0) {
        return { name: path.basename(currentPath), isDir: false };
      }

      const children = await fs.readdir(currentPath);
      const entries = await Promise.all(
        children.map((child) =>
          readRecursively(path.join(currentPath, child), currentDepth - 1)
        )
      );

      return {
        name: path.basename(currentPath),
        isDir: true,
        children: entries,
      };
    }

    try {
      const tree = await readRecursively(safeDir, depth);
      return { success: true, tree };
    } catch (err) {
      logger.error('read-dir failed', err);
      return { success: false, error: (err as Error).message };
    }
  });

  /* --------------------------- CREATE TEMP DIRECTORY ------------------------- */
  ipcMain.handle(CHANNELS.CREATE_TEMP_DIR, async () => {
    try {
      const tmpDir = path.join(os.tmpdir(), `paletteflow-${crypto.randomUUID()}`);
      await fs.mkdir(tmpDir, { recursive: true });
      return { success: true, path: tmpDir };
    } catch (err) {
      logger.error('create-temp-dir failed', err);
      return { success: false, error: (err as Error).message };
    }
  });

  /* ----------------------------- WATCH FILE / DIR ---------------------------- */
  ipcMain.handle(CHANNELS.WATCH_FILE, async (event, payload: unknown) => {
    const { filePath } = WatchFilePayload.parse(payload);
    const safePath = safelyResolve(filePath);
    const window = BrowserWindow.fromWebContents(event.sender);
    if (!window) {
      return { success: false, error: 'No window found.' };
    }

    // create unique id for this watcher
    const id = crypto.randomUUID();
    try {
      const watcher = watch(safePath, { recursive: false }, (eventType) => {
        if (!window.isDestroyed()) {
          window.webContents.send(`${CHANNELS.WATCH_FILE}:changed`, {
            id,
            eventType,
            path: safePath,
          });
        }
      });

      activeWatchers.set(id, { watcher, window });

      // Clean up when the window is closed
      window.on('closed', () => {
        watcher.close();
        activeWatchers.delete(id);
      });

      return { success: true, id };
    } catch (err) {
      logger.error('Failed to watch file', err);
      return { success: false, error: (err as Error).message };
    }
  });

  ipcMain.handle(CHANNELS.UNWATCH_FILE, async (_, id: string) => {
    const descriptor = activeWatchers.get(id);
    if (!descriptor) return { success: false, error: 'Watcher not found' };
    descriptor.watcher.close();
    activeWatchers.delete(id);
    return { success: true };
  });

  /* ----------------------------- CRASH SAFETY -------------------------------- */
  ipcMain.on('renderer:crashed', (_, info) => {
    logger.error('Renderer process crashed', info);
    // In a real-world app we might prompt the user or auto reload.
  });

  logger.info('File-system IPC handlers registered.');
}

/* -------------------------------------------------------------------------- */
/*                               AUTO-EXECUTION                               */
/* -------------------------------------------------------------------------- */

// Auto-register handlers when this module is imported.
registerFileSystemHandlers();
```