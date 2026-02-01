```typescript
/***************************************************************************************************
 *  PaletteFlow Studio – SaveWorkspace Use-Case
 *  ------------------------------------------------
 *  This use-case is responsible for persisting the in-memory Workspace aggregate to the local
 *  filesystem.  It encapsulates all write-time concerns such as:
 *      • concurrency guards
 *      • incremental “dirty” checks
 *      • on-the-fly backups
 *      • plugin lifecycle hooks
 *      • basic crash-report enrichment
 *
 *  Because the core layer is framework-agnostic, we depend exclusively on ports (interfaces) that
 *  will be satisfied by infrastructure adapters (Electron FS, IndexedDB, cloud storage, etc.).
 ***************************************************************************************************/

import { Workspace } from '../../../domain/models/Workspace';
import { WorkspaceRepository } from '../../../domain/ports/WorkspaceRepository';
import { FileStorageGateway, FileWriteOptions } from '../../../domain/ports/FileStorageGateway';
import { Serializer } from '../../../domain/ports/Serializer';
import { DomainEventBus } from '../../../domain/ports/DomainEventBus';
import { Logger } from '../../../domain/ports/Logger';
import { CrashReporter } from '../../../domain/ports/CrashReporter';
import { AcquireLock, ReleaseLock } from '../../../domain/ports/ConcurrencyLocks';
import { PluginLifecycleGateway } from '../../../domain/ports/PluginLifecycleGateway';
import { WorkspaceSavedEvent } from '../../../domain/events/WorkspaceSavedEvent';
import { UseCase } from '../UseCase';

/* ------------------------------------------------------------------------------------------------------------------ */
/*  Types & Error Definitions                                                                                         */
/* ------------------------------------------------------------------------------------------------------------------ */

export type SaveFormat = 'json' | 'binary';

export interface SaveWorkspaceInput {
    workspaceId: string;
    format?: SaveFormat;               // default: json
    makeBackup?: boolean;              // default: true
    initiatedByAutoSave?: boolean;     // is this an autosave operation?
}

export interface SaveWorkspaceOutput {
    workspaceId: string;
    savedAt: Date;
    backupPath?: string;
}

export class WorkspaceNotFoundError extends Error {
    constructor(id: string) {
        super(`Workspace <${id}> does not exist.`);
        this.name = 'WorkspaceNotFoundError';
    }
}

export class ConcurrentSaveError extends Error {
    constructor(id: string) {
        super(`Another save operation is already running for workspace <${id}>.`);
        this.name = 'ConcurrentSaveError';
    }
}

/* ------------------------------------------------------------------------------------------------------------------ */
/*  Use-Case Implementation                                                                                           */
/* ------------------------------------------------------------------------------------------------------------------ */

export class SaveWorkspace
    implements UseCase<SaveWorkspaceInput, SaveWorkspaceOutput>
{
    private static readonly BACKUP_EXTENSION = '.bak';

    constructor(
        private readonly repository: WorkspaceRepository,
        private readonly serializer: Serializer<Workspace>,
        private readonly storage: FileStorageGateway,
        private readonly eventBus: DomainEventBus,
        private readonly pluginLifecycle: PluginLifecycleGateway,
        private readonly logger: Logger,
        private readonly crashReporter: CrashReporter,
        private readonly acquireLock: AcquireLock,
        private readonly releaseLock: ReleaseLock,
    ) {}

    public async execute(
        input: SaveWorkspaceInput,
    ): Promise<SaveWorkspaceOutput> {
        const {
            workspaceId,
            format = 'json',
            makeBackup = true,
            initiatedByAutoSave = false,
        } = input;

        /* ---------------------------------------------------------------------------------------------------------- */
        /*  1.  Fetch Aggregate                                                                                       */
        /* ---------------------------------------------------------------------------------------------------------- */

        const workspace = await this.repository.findById(workspaceId);
        if (!workspace) {
            throw new WorkspaceNotFoundError(workspaceId);
        }

        /* ---------------------------------------------------------------------------------------------------------- */
        /*  2.  Concurrency Guard                                                                                     */
        /* ---------------------------------------------------------------------------------------------------------- */

        const lockToken = await this.acquireLock(`workspace:${workspaceId}`);
        if (!lockToken) {
            throw new ConcurrentSaveError(workspaceId);
        }

        try {
            // Skip heavy I/O work if nothing changed and not forced.
            if (!workspace.isDirty && !initiatedByAutoSave) {
                this.logger.debug(
                    `[SaveWorkspace] Workspace <${workspaceId}> is clean; skipping save.`,
                );
                return {
                    workspaceId,
                    savedAt: workspace.meta.lastSavedAt ?? new Date(),
                };
            }

            /* ------------------------------------------------------------------------------------------------------ */
            /*  3.  Plugin Pre-Save Hooks                                                                             */
            /* ------------------------------------------------------------------------------------------------------ */
            await this.pluginLifecycle.onBeforeSave(workspace);

            /* ------------------------------------------------------------------------------------------------------ */
            /*  4.  Optional Backup                                                                                   */
            /* ------------------------------------------------------------------------------------------------------ */

            let backupPath: string | undefined;
            if (makeBackup && workspace.meta.filePath) {
                backupPath = `${workspace.meta.filePath}${SaveWorkspace.BACKUP_EXTENSION}`;
                try {
                    await this.storage.copyFile(
                        workspace.meta.filePath,
                        backupPath,
                    );
                } catch (backupErr) {
                    // Non-fatal: log but continue the save.
                    this.logger.warn(
                        `[SaveWorkspace] Failed to create backup for <${workspaceId}>: ${(backupErr as Error).message}`,
                    );
                }
            }

            /* ------------------------------------------------------------------------------------------------------ */
            /*  5.  Serialize Aggregate                                                                               */
            /* ------------------------------------------------------------------------------------------------------ */

            const serialized =
                format === 'binary'
                    ? await this.serializer.serialize(workspace, 'binary')
                    : await this.serializer.serialize(workspace, 'json');

            /* ------------------------------------------------------------------------------------------------------ */
            /*  6.  Persist to Storage                                                                                */
            /* ------------------------------------------------------------------------------------------------------ */

            const filePath =
                workspace.meta.filePath ??
                this.deriveDefaultPath(workspace, format);

            const writeOptions: FileWriteOptions = {
                encoding: format === 'binary' ? 'binary' : 'utf8',
                atomic: true, // write to temp then move
            };

            await this.storage.writeFile(filePath, serialized, writeOptions);

            /* ------------------------------------------------------------------------------------------------------ */
            /*  7.  Housekeeping & Events                                                                             */
            /* ------------------------------------------------------------------------------------------------------ */

            workspace.markClean();
            workspace.meta.lastSavedAt = new Date();
            workspace.meta.filePath = filePath;

            await this.repository.save(workspace);

            await this.eventBus.publish(
                new WorkspaceSavedEvent(workspace, initiatedByAutoSave),
            );

            await this.pluginLifecycle.onAfterSave(workspace);

            this.logger.info(
                `[SaveWorkspace] Saved workspace <${workspaceId}> at ${filePath}`,
            );

            return {
                workspaceId,
                savedAt: workspace.meta.lastSavedAt,
                backupPath,
            };
        } catch (err) {
            /* ------------------------------------------------------------------------------------------------------ */
            /*  8.  Error Handling & Crash-Report                                                                     */
            /* ------------------------------------------------------------------------------------------------------ */

            this.logger.error(
                `[SaveWorkspace] Failed to save workspace <${workspaceId}>: ${
                    (err as Error).message
                }`,
            );
            await this.crashReporter.captureException(err, {
                workspaceId,
                useCase: 'SaveWorkspace',
            });
            throw err;
        } finally {
            this.releaseLock(lockToken);
        }
    }

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*  Helper Methods                                                                                                    */
    /* ------------------------------------------------------------------------------------------------------------------ */

    /**
     * Derive a default storage path based on workspace title if a filePath has not been
     * assigned yet.  The actual directory is delegated to infrastructure adapters.
     *
     * Example: My Cool Space -> ~/PaletteFlow/Workspaces/My Cool Space.pf.json
     */
    private deriveDefaultPath(
        workspace: Workspace,
        format: SaveFormat,
    ): string {
        const sanitizedTitle = workspace.meta.title
            .replace(/[<>:"/\\|?*\x00-\x1F]/g, '') // remove illegal FS chars
            .trim();

        const extension = format === 'binary' ? '.pfbin' : '.pf.json';
        const fileName = `${sanitizedTitle || workspace.id}${extension}`;

        // Delegated to storage gateway; may resolve to userDataPath in Electron, etc.
        return this.storage.resolvePath(['Workspaces', fileName]);
    }
}
```
