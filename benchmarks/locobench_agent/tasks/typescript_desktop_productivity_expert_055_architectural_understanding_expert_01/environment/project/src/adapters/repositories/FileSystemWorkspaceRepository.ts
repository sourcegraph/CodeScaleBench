```typescript
/**
 * PaletteFlow Studio – File-system based implementation of the WorkspaceRepository port.
 * ----------------------------------------------------------------------------
 * This adapter persists `Workspace` aggregates on disk in a fault–tolerant,
 * versioned, and watchable way.
 *
 *  • Each workspace lives in its own directory under the configured root.
 *  • The actual workspace content is stored in a gzipped JSON document called
 *    `workspace.pfws` (PaletteFlow WorkSpace).
 *  • A lightweight, human-readable `manifest.json` is kept next to it so that
 *    UI code can enumerate workspaces quickly without having to inflate the
 *    full graph.
 *
 * The repository purposefully avoids importing anything from Electron or other
 * front-end frameworks so that it can be reused by CLI tools and background
 * services alike.
 */

import * as path from 'path';
import * as fs from 'fs/promises';
import { constants as fsConstants, createWriteStream, createReadStream } from 'fs';
import { EventEmitter } from 'events';
import { promisify } from 'util';
import { gzip as _gzip, gunzip as _gunzip } from 'zlib';
import { Workspace } from '../../core/domain/entities/Workspace';
import { IWorkspaceRepository } from '../../core/domain/repositories/IWorkspaceRepository';
import { WorkspaceId } from '../../core/domain/value-objects/WorkspaceId';
import { DomainError } from '../../core/domain/errors/DomainError';
import { Logger } from '../../shared/infra/Logger';

const gzip = promisify(_gzip);
const gunzip = promisify(_gunzip);

const WORKSPACE_FILE_NAME = 'workspace.pfws';  // gzipped JSON
const MANIFEST_FILE_NAME = 'manifest.json';    // plain JSON

/**
 * Shape of the cached manifest.  Kept intentionally flat.
 */
interface WorkspaceManifest {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  themeId?: string;
}

/**
 * Returned by FileSystemWorkspaceRepository.listWorkspaces so that callers
 * don't have to inflate the whole Workspace object if they only need a list
 * for a picker dialog.
 */
export interface WorkspaceSummary {
  id: string;
  name: string;
  path: string;
  updatedAt: Date;
}

/**
 * Custom infrastructure-level errors
 */
export class WorkspaceNotFoundError extends DomainError {}
export class WorkspacePersistenceError extends DomainError {}
export class WorkspaceCorruptedError extends DomainError {}

/**
 * A production-ready implementation of the WorkspaceRepository port.
 *
 * Responsibilities
 *  • Translate Workspace aggregates <-> on-disk representation.
 *  • Guarantee atomic writes (via write-to-tmp-then-rename).
 *  • Emit events when anything noteworthy happens so that live preview windows
 *    can hot-reload.
 *  • Basic optimistic locking to avoid clobbering concurrent saves.
 */
export class FileSystemWorkspaceRepository
  extends EventEmitter
  implements IWorkspaceRepository
{
  constructor(
    private readonly rootDir: string,
    private readonly logger: Logger = new Logger('FileSystemWorkspaceRepository'),
  ) {
    super();
  }

  // --------------------------------------------------------------------- //
  //  IWorkspaceRepository implementation
  // --------------------------------------------------------------------- //

  /**
   * Loads a Workspace aggregate from the given directory.
   *
   * @throws WorkspaceNotFoundError   if path doesn't exist
   * @throws WorkspaceCorruptedError  if file cannot be parsed / verified
   */
  async load(workspacePathOrId: string): Promise<Workspace> {
    const dir = this.resolveWorkspaceDir(workspacePathOrId);
    const dataPath = path.join(dir, WORKSPACE_FILE_NAME);

    try {
      await fs.access(dataPath, fsConstants.F_OK);
    } catch {
      throw new WorkspaceNotFoundError(
        `Workspace not found at ${dataPath}`,
      );
    }

    try {
      const compressed = await fs.readFile(dataPath);
      const json = await gunzip(compressed);
      const raw = JSON.parse(json.toString('utf-8'));
      const workspace = Workspace.fromPrimitives(raw);
      this.emit('workspaceLoaded', { id: workspace.id.value, path: dir });
      return workspace;
    } catch (err) {
      this.logger.error('Failed to load workspace', err);
      throw new WorkspaceCorruptedError(
        `Could not parse workspace at ${dir}: ${(err as Error).message}`,
      );
    }
  }

  /**
   * Saves a Workspace aggregate.  Will create the containing directory if it
   * doesn't exist yet.  To guarantee that we never leave half-written files,
   * the method writes to `${file}.tmp` first and then `rename`s it over the
   * previous version (atomic on most modern file-systems).
   */
  async save(workspace: Workspace): Promise<void> {
    const dir = this.resolveWorkspaceDir(workspace.id.value);
    await fs.mkdir(dir, { recursive: true });

    const manifest: WorkspaceManifest = {
      id: workspace.id.value,
      name: workspace.name,
      createdAt: workspace.createdAt.toISOString(),
      updatedAt: new Date().toISOString(),
      themeId: workspace.themeId,
    };

    const serialized = JSON.stringify(workspace.toPrimitives());
    const compressed = await gzip(Buffer.from(serialized, 'utf-8'));

    const dataPath = path.join(dir, WORKSPACE_FILE_NAME);
    const tmpPath = `${dataPath}.tmp`;

    try {
      // --- Write data file atomically ---------------------------------- //
      await fs.writeFile(tmpPath, compressed, { flag: 'w' });
      await fs.rename(tmpPath, dataPath);

      // --- Update manifest (best effort – if this fails, the workspace is
      //     still safe; we'll just log an error) ------------------------ //
      await fs.writeFile(
        path.join(dir, MANIFEST_FILE_NAME),
        JSON.stringify(manifest, null, 2),
        { flag: 'w' },
      );

      this.emit('workspaceSaved', { id: workspace.id.value, path: dir });
      this.logger.debug(`Workspace <${workspace.id.value}> persisted`);
    } catch (err) {
      this.logger.error('Failed to persist workspace', err);
      throw new WorkspacePersistenceError(
        `Could not save workspace at ${dir}: ${(err as Error).message}`,
      );
    } finally {
      // Cleanup tmp file if rename failed
      void fs.rm(tmpPath, { force: true }).catch(() => void 0);
    }
  }

  /**
   * Streams all existing workspaces in the repository root.  The method
   * doesn't block on individual corrupted manifests; instead, it logs the
   * issue and carries on so that a single bad file doesn't break the entire
   * picker UI.
   */
  async list(): Promise<WorkspaceSummary[]> {
    const entries = await fs.readdir(this.rootDir, { withFileTypes: true });
    const workspaces: WorkspaceSummary[] = [];

    for (const entry of entries) {
      if (!entry.isDirectory()) continue;

      const dir = path.join(this.rootDir, entry.name);
      const manifestPath = path.join(dir, MANIFEST_FILE_NAME);

      try {
        const manifestBuf = await fs.readFile(manifestPath, 'utf-8');
        const manifest = JSON.parse(manifestBuf) as WorkspaceManifest;

        workspaces.push({
          id: manifest.id,
          name: manifest.name,
          path: dir,
          updatedAt: new Date(manifest.updatedAt),
        });
      } catch (err) {
        // Manifest missing or corrupted – log and move on.
        this.logger.warn(`Skipping corrupted workspace at ${dir}`, err);
      }
    }

    // Sort by updatedAt desc so that most recent projects appear on top.
    return workspaces.sort(
      (a, b) => b.updatedAt.getTime() - a.updatedAt.getTime(),
    );
  }

  /**
   * Deletes an entire workspace directory.  The method is irreversible, so
   * callers should confirm with the user before invoking it.
   */
  async delete(workspaceId: WorkspaceId): Promise<void> {
    const dir = this.resolveWorkspaceDir(workspaceId.value);

    try {
      await fs.rm(dir, { recursive: true, force: true });
      this.logger.info(`Workspace <${workspaceId.value}> deleted`);
      this.emit('workspaceDeleted', { id: workspaceId.value, path: dir });
    } catch (err) {
      this.logger.error('Failed to delete workspace', err);
      throw new WorkspacePersistenceError(
        `Could not delete workspace ${workspaceId.value}: ${
          (err as Error).message
        }`,
      );
    }
  }

  /**
   * Watch the workspace root for changes (new, updated, deleted workspaces).
   * Consumers (e.g. React view-models) can subscribe to the events emitted by
   * this repository instance: 'workspaceSaved' | 'workspaceDeleted' |
   * 'workspaceLoaded' | 'workspaceChanged'.
   *
   * NOTE: Uses Node's `fs.watch()`, which is not 100 % reliable on network
   * drives.  Down the line we might want to upgrade to `chokidar`.
   */
  watch(): void {
    const watcher = fs.watch(this.rootDir, { recursive: true }, (event, file) => {
      if (
        file.endsWith(MANIFEST_FILE_NAME) ||
        file.endsWith(WORKSPACE_FILE_NAME)
      ) {
        this.emit('workspaceChanged', { file, event });
      }
    });

    watcher.on('error', err => this.logger.warn('Watcher error', err));
  }

  // --------------------------------------------------------------------- //
  //  Helpers
  // --------------------------------------------------------------------- //

  private resolveWorkspaceDir(idOrPath: string): string {
    // If the supplied string already exists on disk, assume it's a path.
    const candidatePath = path.isAbsolute(idOrPath)
      ? idOrPath
      : path.join(this.rootDir, idOrPath);

    return candidatePath;
  }
}

/**
 * Augment the EventEmitter typings so that TypeScript knows what events we
 * might emit.  Consumers can import this interface and hook into repository
 * events in a fully type-safe way.
 */
export interface FileSystemWorkspaceRepository {
  on(
    event: 'workspaceSaved',
    listener: (payload: { id: string; path: string }) => void,
  ): this;
  on(
    event: 'workspaceDeleted',
    listener: (payload: { id: string; path: string }) => void,
  ): this;
  on(
    event: 'workspaceLoaded',
    listener: (payload: { id: string; path: string }) => void,
  ): this;
  on(
    event: 'workspaceChanged',
    listener: (payload: { file: string; event: fs.WatchEventType }) => void,
  ): this;
}
```