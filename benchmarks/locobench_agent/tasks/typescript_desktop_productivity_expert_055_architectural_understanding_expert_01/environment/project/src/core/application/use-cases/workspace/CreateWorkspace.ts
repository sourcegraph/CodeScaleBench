```typescript
/**************************************************************************************************
 *  PaletteFlow Studio - CreateWorkspace Use-Case                                                *
 *  -------------------------------------------------------------------------------------------- *
 *  This file contains the application-layer use-case responsible for creating a new workspace   *
 *  entity. It orchestrates validation, template cloning, plugin hooks, persistence, and event   *
 *  publishing while remaining framework-agnostic.                                               *
 **************************************************************************************************/

import { Workspace } from '../../../domain/entities/Workspace';
import { UserId } from '../../../domain/value-objects/UserId';
import { WorkspaceId } from '../../../domain/value-objects/WorkspaceId';
import { ThemeId } from '../../../domain/value-objects/ThemeId';
import { IWorkspaceRepository } from '../../../domain/repositories/IWorkspaceRepository';
import { IEventBus } from '../../../domain/events/IEventBus';
import { WorkspaceCreatedEvent } from '../../../domain/events/workspace/WorkspaceCreatedEvent';
import { WorkspaceName } from '../../../domain/value-objects/WorkspaceName';
import { IDateTimeProvider } from '../../ports/IDateTimeProvider';
import { IIdGenerator } from '../../ports/IIdGenerator';
import { ITemplateService } from '../../ports/ITemplateService';
import { IPluginBus } from '../../ports/IPluginBus';
import { InvariantViolationError, AlreadyExistsError, ValidationError } from '../../errors';

/* ============================================================================
 * DTOs & Interfaces
 * ========================================================================= */

/**
 * Command object passed to the use-case.
 */
export interface CreateWorkspaceCommand {
  readonly name: string;
  readonly ownerUserId: string;
  readonly templateId?: string;  // Optional: clone nodes/canvases from an existing template
  readonly themeId?: string;     // Optional: apply a theme after creation
  readonly description?: string;
}

/**
 * Result returned by the use-case.
 */
export interface CreateWorkspaceResult {
  readonly workspaceId: string;
}

/* ============================================================================
 * CreateWorkspace Use-Case
 * ========================================================================= */

export class CreateWorkspace {
  constructor(
    private readonly workspaceRepo: IWorkspaceRepository,
    private readonly idGenerator: IIdGenerator,
    private readonly dateTime: IDateTimeProvider,
    private readonly eventBus: IEventBus,
    private readonly templateService: ITemplateService,
    private readonly pluginBus: IPluginBus
  ) {}

  /**
   * Executes the business rules to create a new workspace.
   */
  public async execute(
    command: CreateWorkspaceCommand
  ): Promise<CreateWorkspaceResult> {
    // -------------------------------
    // 1. Input validation
    // -------------------------------
    this.assertCommandValid(command);

    // -------------------------------
    // 2. Ensure name uniqueness
    // -------------------------------
    const workspaceName = new WorkspaceName(command.name);
    const existing = await this.workspaceRepo.findByName(workspaceName);
    if (existing) {
      throw new AlreadyExistsError(
        `Workspace with name "${workspaceName.value}" already exists`
      );
    }

    // -------------------------------
    // 3. Calculate identifiers & timestamps
    // -------------------------------
    const workspaceId = new WorkspaceId(this.idGenerator.generate());
    const ownerUserId = new UserId(command.ownerUserId);
    const createdAt = this.dateTime.now();

    // -------------------------------
    // 4. Create base domain entity
    // -------------------------------
    const workspace = Workspace.create({
      id: workspaceId,
      name: workspaceName,
      ownerUserId,
      description: command.description ?? '',
      createdAt,
      updatedAt: createdAt,
      themeId: command.themeId ? new ThemeId(command.themeId) : undefined
    });

    // -------------------------------
    // 5. Plugin pre-create hooks
    // -------------------------------
    await this.pluginBus.emit('workspace:preCreate', { workspace, command });

    // -------------------------------
    // 6. Optional template instantiation
    // -------------------------------
    if (command.templateId) {
      await this.templateService.applyTemplate(
        workspace,
        command.templateId,
        ownerUserId
      );
    }

    // -------------------------------
    // 7. Persist workspace (transactional)
    // -------------------------------
    await this.workspaceRepo.save(workspace);

    // -------------------------------
    // 8. Plugin post-create hooks
    // -------------------------------
    await this.pluginBus.emit('workspace:postCreate', { workspace, command });

    // -------------------------------
    // 9. Publish domain event
    // -------------------------------
    await this.eventBus.publish(
      new WorkspaceCreatedEvent({
        workspaceId: workspace.id,
        ownerUserId: workspace.ownerUserId,
        occurredAt: createdAt
      })
    );

    // -------------------------------
    // 10. Return result
    // -------------------------------
    return { workspaceId: workspace.id.value };
  }

  /* ============================================================================
   * Internal helpers
   * ========================================================================= */

  /**
   * Validates the invariants of the incoming command object.
   */
  private assertCommandValid(cmd: CreateWorkspaceCommand): void {
    if (!cmd.name || typeof cmd.name !== 'string') {
      throw new ValidationError('Workspace name must be a non-empty string');
    }
    if (!cmd.ownerUserId) {
      throw new ValidationError('ownerUserId is required');
    }
    if (cmd.themeId && typeof cmd.themeId !== 'string') {
      throw new ValidationError('themeId must be a string when provided');
    }
    if (cmd.templateId && typeof cmd.templateId !== 'string') {
      throw new ValidationError('templateId must be a string when provided');
    }
    if (cmd.description && cmd.description.length > 1024) {
      throw new ValidationError('description must be <= 1024 characters');
    }
  }
}
```