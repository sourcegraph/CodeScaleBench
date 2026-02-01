```typescript
/**********************************************************************************************
 * PaletteFlow Studio
 * File: src/core/application/use-cases/workspace/OpenWorkspace.ts
 *
 * Author: PaletteFlow Core Team
 * License: MIT
 *
 * Description:
 *   Interactor / Use-case for opening a Workspace.  Coordinates persistence, plugin–powered
 *   migrations, and event dispatch so that the rest of the app can react to an opened file.
 *
 *   ┌───────────────────────────────────────────────────────────────────────────┐
 *   │                        +-------------------------+                       │
 *   │ Request (`OpenWorkspaceCommand`)                 │                       │
 *   │        ───────────────▶  OpenWorkspace (this file) ────────────────┐      │
 *   │                               │                                   │      │
 *   │                               ▼                                   │      │
 *   │        WorkspaceRepository.loadById / loadFromPath                │      │
 *   │                               │                                   │      │
 *   │                               ▼                                   │      │
 *   │                      PluginMigrationService                       │      │
 *   │                               │                                   │      │
 *   │                               ▼                                   │      │
 *   │         EventBus.publish(WorkspaceOpenedEvent)  ◀──────────────────┘      │
 *   └───────────────────────────────────────────────────────────────────────────┘
 *********************************************************************************************/

import { Workspace } from '../../../domain/models/Workspace';
import { WorkspaceId } from '../../../domain/models/WorkspaceId';
import { IWorkspaceRepository } from '../../../domain/repositories/IWorkspaceRepository';
import { IPluginMigrationService } from '../../../domain/services/IPluginMigrationService';
import { IWorkspaceLockService } from '../../../domain/services/IWorkspaceLockService';
import { IRecentWorkspaceService } from '../../../domain/services/IRecentWorkspaceService';
import { EventBus } from '../../../infrastructure/event-bus/EventBus';
import {
  WorkspaceOpenedEvent,
  WorkspaceOpenFailedEvent,
} from '../../../domain/events/workspaceEvents';

import { Result, ok, err } from '../../../common/result';
import { Guard } from '../../../common/Guard';

/**
 * Command input for the OpenWorkspace use-case.
 */
export interface OpenWorkspaceCommand {
  /**
   * Unique identifier for a Workspace *or* absolute disk path to the
   * `.pf-workspace` bundle.  The repository implementation decides how to
   * interpret this string.
   */
  locator: string;

  /**
   * Optional hint that instructs the use-case to open the Workspace in
   * read-only mode (e.g., when another process already holds a lock).
   */
  readOnly?: boolean;
}

/**
 * DTO returned by the OpenWorkspace use-case.
 */
export interface OpenWorkspaceResponse {
  workspace: Workspace;
  readOnly: boolean;
}

/**
 * Domain-level error thrown when a Workspace cannot be opened.
 */
export class OpenWorkspaceError extends Error {
  readonly code:
    | 'NOT_FOUND'
    | 'ALREADY_OPEN'
    | 'LOCK_FAILED'
    | 'MIGRATION_FAILED'
    | 'UNKNOWN';

  constructor(code: OpenWorkspaceError['code'], message?: string, cause?: Error) {
    super(message ?? code);
    this.code = code;
    if (cause) {
      // node >= 16 supports the `cause` property
      (this as any).cause = cause;
    }
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Interactor for opening a Workspace.
 *
 * Responsibilities:
 *  • Retrieve workspace from persistence.
 *  • Enforce single-instance locking.
 *  • Run plugin-provided migrations (if necessary).
 *  • Register the workspace inside the "recent workspaces" store.
 *  • Emit domain events through the EventBus.
 *
 * Depends on abstractions only.  Concrete implementations are wired at runtime
 * by the application layer (DI container / service locator).
 */
export class OpenWorkspace {
  constructor(
    private readonly repository: IWorkspaceRepository,
    private readonly migrationService: IPluginMigrationService,
    private readonly lockService: IWorkspaceLockService,
    private readonly recentService: IRecentWorkspaceService,
    private readonly eventBus: EventBus,
  ) {}

  /**
   * Execute the use-case.
   */
  async execute(
    command: OpenWorkspaceCommand,
  ): Promise<Result<OpenWorkspaceResponse, OpenWorkspaceError>> {
    // 1. Validate input
    const guard = Guard.againstNullOrUndefined(command, 'OpenWorkspaceCommand');
    if (!guard.succeeded) {
      return err(
        new OpenWorkspaceError('UNKNOWN', 'OpenWorkspaceCommand was null/undefined'),
      );
    }

    const { locator, readOnly = false } = command;

    try {
      // 2. Load Workspace (Could be heavy IO; keep async)
      const workspaceOrNull = await this.repository.load(locator);
      if (!workspaceOrNull) {
        return err(
          new OpenWorkspaceError(
            'NOT_FOUND',
            `Workspace "${locator}" could not be located.`,
          ),
        );
      }

      const workspace = workspaceOrNull;

      // 3. If not in read-only mode, try to acquire a lock
      if (!readOnly) {
        const locked = await this.lockService.acquire(workspace.id);
        if (!locked) {
          return err(
            new OpenWorkspaceError(
              'ALREADY_OPEN',
              `Workspace "${workspace.id}" is currently open in another window or process.`,
            ),
          );
        }
      }

      // 4. Run plugin migrations (database / schema updates)
      const migrationResult = await this.migrationService.migrate(workspace);
      if (migrationResult.isErr()) {
        // Release lock on migration failure
        if (!readOnly) {
          await this.lockService.release(workspace.id);
        }
        return err(
          new OpenWorkspaceError(
            'MIGRATION_FAILED',
            `One or more plugin migrations failed for workspace "${workspace.id}".`,
            migrationResult.error,
          ),
        );
      }

      const migratedWorkspace = migrationResult.value;

      // 5. Put into "recent workspaces" store (fire-and-forget)
      this.recentService.push({ id: migratedWorkspace.id, lastOpened: new Date() });

      // 6. Emit domain event
      await this.eventBus.publish(
        new WorkspaceOpenedEvent({
          workspace: migratedWorkspace,
          readOnly,
        }),
      );

      return ok({ workspace: migratedWorkspace, readOnly });
    } catch (e: unknown) {
      // 7. Any uncaught error gets converted to UNKNOWN
      const wrapped =
        e instanceof OpenWorkspaceError
          ? e
          : new OpenWorkspaceError('UNKNOWN', (e as Error)?.message, e as Error);

      // Dispatch a failure event so listeners can react (telemetry, UI toaster, etc.)
      await this.eventBus.publish(
        new WorkspaceOpenFailedEvent({
          locator: command.locator,
          error: wrapped,
        }),
      );

      return err(wrapped);
    }
  }

  /**
   * Helper that returns the result or throws, letting UI layers decide the
   * error-handling strategy.
   */
  async executeOrThrow(command: OpenWorkspaceCommand): Promise<OpenWorkspaceResponse> {
    const result = await this.execute(command);
    if (result.isErr()) {
      throw result.error;
    }
    return result.value;
  }
}
```
