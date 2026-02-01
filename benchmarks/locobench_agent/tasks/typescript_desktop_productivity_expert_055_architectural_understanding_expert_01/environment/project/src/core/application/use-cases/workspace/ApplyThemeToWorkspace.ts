```typescript
/***************************************************************************************************
 *  PaletteFlow Studio – ApplyThemeToWorkspace Use-Case
 *  ---------------------------------------------------
 *  This application-layer service orchestrates the process of applying a Theme to an existing
 *  Workspace.  It performs permission checks, verifies compatibility, persists the updated
 *  aggregate through the repository abstraction, and finally emits a domain event so that any
 *  interested adapters (Electron windows, plug-ins, etc.) can react to the change.
 *
 *  The use-case is intentionally free of framework-specific code, fulfilling the Clean
 *  Architecture principles adopted by the PaletteFlow codebase.
 ***************************************************************************************************/

import { Workspace, WorkspaceId } from '../../../domain/entities/Workspace';
import { Theme, ThemeId } from '../../../domain/entities/Theme';
import { UserId } from '../../../domain/value-objects/UserId';

import { WorkspaceRepository } from '../../../domain/repositories/WorkspaceRepository';
import { ThemeRepository } from '../../../domain/repositories/ThemeRepository';

import { DomainEventBus } from '../../../domain/events/DomainEventBus';
import { WorkspaceThemeApplied } from '../../../domain/events/WorkspaceEvents';

import { PermissionDeniedError } from '../../../domain/errors/PermissionDeniedError';
import { NotFoundError } from '../../../domain/errors/NotFoundError';
import { InvalidOperationError } from '../../../domain/errors/InvalidOperationError';

import { TransactionManager } from '../../services/TransactionManager';

/**
 * DTO received by the use-case.
 */
export interface ApplyThemeToWorkspaceInput {
  /** ID of the workspace that will receive the theme. */
  workspaceId: WorkspaceId;

  /** ID of the theme that will be applied to the workspace. */
  themeId: ThemeId;

  /** The user performing the operation. */
  requestingUserId: UserId;

  /**
   * By default, trying to apply an already-active theme throws an InvalidOperationError.
   * Setting `force` circumvents that safeguard.
   */
  force?: boolean;
}

/**
 * Output DTO.  We return the new theme so UI layers can update optimistic state.
 */
export interface ApplyThemeToWorkspaceOutput {
  workspaceId: WorkspaceId;
  appliedTheme: Theme;
}

/**
 * Core application service that applies a theme to a workspace.
 *
 * The service is implemented to be stateless and reusable; all stateful collaborators
 * (repositories, event bus, transaction manager) are injected through the constructor.
 */
export class ApplyThemeToWorkspace {
  constructor(
    private readonly workspaceRepo: WorkspaceRepository,
    private readonly themeRepo: ThemeRepository,
    private readonly eventBus: DomainEventBus,
    private readonly tx: TransactionManager,
  ) {}

  /**
   * Execute the use-case.
   *
   * @throws NotFoundError          When either the workspace or the theme does not exist.
   * @throws PermissionDeniedError  When the user lacks write permissions over the workspace.
   * @throws InvalidOperationError  When attempting a no-op (applying the current theme without force).
   */
  async execute({
    workspaceId,
    themeId,
    requestingUserId,
    force = false,
  }: ApplyThemeToWorkspaceInput): Promise<ApplyThemeToWorkspaceOutput> {
    return this.tx.runInTransaction(async () => {
      // ------------------------------------------------------------------
      // 1. Load aggregate roots
      // ------------------------------------------------------------------
      const [workspace, theme] = await Promise.all([
        this.workspaceRepo.findById(workspaceId),
        this.themeRepo.findById(themeId),
      ]);

      if (!workspace) {
        throw new NotFoundError(`Workspace '${workspaceId}' was not found.`);
      }
      if (!theme) {
        throw new NotFoundError(`Theme '${themeId}' was not found.`);
      }

      // ------------------------------------------------------------------
      // 2. Permission check
      // ------------------------------------------------------------------
      if (!workspace.canBeEditedBy(requestingUserId)) {
        throw new PermissionDeniedError(
          `User '${requestingUserId}' does not have permission to modify workspace '${workspaceId}'.`,
        );
      }

      // ------------------------------------------------------------------
      // 3. Business-rule validations
      // ------------------------------------------------------------------
      if (workspace.theme?.id === theme.id && !force) {
        throw new InvalidOperationError(
          `Theme '${theme.name}' is already active for workspace '${workspaceId}'. Pass { force: true } to override.`,
        );
      }

      if (!theme.isCompatibleWith(workspace)) {
        throw new InvalidOperationError(
          `Theme '${theme.name}' is not compatible with the current workspace configuration.`,
        );
      }

      // ------------------------------------------------------------------
      // 4. Apply the theme
      // ------------------------------------------------------------------
      workspace.applyTheme(theme, requestingUserId);

      // Persist the aggregate
      await this.workspaceRepo.save(workspace);

      // ------------------------------------------------------------------
      // 5. Emit domain event
      // ------------------------------------------------------------------
      const event = new WorkspaceThemeApplied({
        workspaceId,
        themeId,
        triggeredBy: requestingUserId,
        timestamp: new Date(),
      });
      await this.eventBus.publish(event);

      // ------------------------------------------------------------------
      // 6. Return DTO for presentation layer
      // ------------------------------------------------------------------
      return {
        workspaceId,
        appliedTheme: theme,
      };
    });
  }
}
```
