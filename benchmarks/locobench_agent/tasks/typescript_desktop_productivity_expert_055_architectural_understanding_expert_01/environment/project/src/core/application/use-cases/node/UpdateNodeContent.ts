```typescript
/**
 * PaletteFlow Studio
 * core/application/use-cases/node/UpdateNodeContent.ts
 *
 * Use-case: UpdateNodeContent
 * -----------------------------------
 * Updates the content of a single Canvas Node, performing:
 *  • Existence & optimistic-lock checks
 *  • Content validation via plugin-provided validators
 *  • Revision bookkeeping for undo/redo
 *  • Domain-event publication
 *
 * The implementation is framework-agnostic and lives in the
 * application layer; adapters (Electron IPC, CLI, etc.) invoke
 * it by constructing the command object and wiring the needed
 * dependencies.
 */

import { v4 as uuid } from 'uuid';

import { Node } from '../../../domain/entities/Node';
import { NodeId } from '../../../domain/value-objects/NodeId';
import { Version } from '../../../domain/value-objects/Version';
import { NodeRepository } from '../../../domain/repositories/NodeRepository';
import { NodeRevisionRepository } from '../../../domain/repositories/NodeRevisionRepository';
import { DomainEventBus } from '../../../domain/events/DomainEventBus';
import { NodeContentUpdatedEvent } from '../../../domain/events/NodeContentUpdatedEvent';
import { NodeContentValidatorFactory } from '../../../domain/services/NodeContentValidatorFactory';

// ────────────────────────────────────────────────────────────────────────────────
//  Command / DTO
// ────────────────────────────────────────────────────────────────────────────────

export interface UpdateNodeContentCommand {
  /** Target node identifier */
  nodeId: string;

  /** Latest content payload coming from the UI/editor */
  newContent: unknown;

  /** Optional version for optimistic locking */
  expectedVersion?: number;

  /**
   * Optional editor identifier (for multi-cursor or remote editing telemetry);
   * persisted only in revision metadata, not on the node itself.
   */
  editorId?: string;

  /** Optional correlation ID for tracing across bounded contexts */
  correlationId?: string;
}

// ────────────────────────────────────────────────────────────────────────────────
//  Errors
// ────────────────────────────────────────────────────────────────────────────────

export class NodeNotFoundError extends Error {
  constructor(id: string) {
    super(`Node <${id}> does not exist or is no longer available.`);
    this.name = 'NodeNotFoundError';
  }
}

export class NodeContentValidationError extends Error {
  constructor(readonly validationErrors: readonly string[]) {
    super('Provided node content failed validation.');
    this.name = 'NodeContentValidationError';
  }
}

export class OptimisticLockError extends Error {
  constructor(readonly expected: number, readonly actual: number) {
    super(
      `Optimistic-lock check failed. Expected version <${expected}>, but current version is <${actual}>.`,
    );
    this.name = 'OptimisticLockError';
  }
}

// ────────────────────────────────────────────────────────────────────────────────
//  Use-case
// ────────────────────────────────────────────────────────────────────────────────

/**
 * Application-layer orchestrator that mutates the aggregate and persists it
 * through the repository. No UI/event-loop details leak in.
 */
export class UpdateNodeContent {
  constructor(
    private readonly nodeRepo: NodeRepository,
    private readonly revisionRepo: NodeRevisionRepository,
    private readonly validatorFactory: NodeContentValidatorFactory,
    private readonly eventBus: DomainEventBus,
  ) {}

  /**
   * Execute the command.
   *
   * @throws NodeNotFoundError           When the node is missing.
   * @throws NodeContentValidationError  When validators reject the content.
   * @throws OptimisticLockError         When expectedVersion mismatches.
   */
  public async execute(command: UpdateNodeContentCommand): Promise<Node> {
    const {
      nodeId,
      newContent,
      expectedVersion,
      editorId,
      correlationId = uuid(),
    } = command;

    // 1. Retrieve the aggregate
    const node = await this.nodeRepo.findById(NodeId.fromString(nodeId));
    if (!node) {
      throw new NodeNotFoundError(nodeId);
    }

    // 2. Optimistic-lock check (if requested)
    if (
      typeof expectedVersion === 'number' &&
      node.version.value !== expectedVersion
    ) {
      throw new OptimisticLockError(expectedVersion, node.version.value);
    }

    // 3. Validate new content using plugin-provided validator
    const validator = this.validatorFactory.forNodeType(node.type);
    const validationErrors = await validator.validate(newContent);
    if (validationErrors.length) {
      throw new NodeContentValidationError(validationErrors);
    }

    // 4. Short-circuit if content is identical (no-op)
    if (node.contentEquals(newContent)) {
      return node; // Idempotent update
    }

    // 5. Persist a revision snapshot (for undo/redo and audit trail)
    await this.revisionRepo.save({
      id: uuid(),
      nodeId: node.id,
      previousContent: node.content,
      nextContent: newContent,
      editorId,
      createdAt: new Date(),
    });

    // 6. Apply mutation on the aggregate + bump version
    node.updateContent(newContent, {
      updatedAt: new Date(),
      updatedBy: editorId ?? 'system',
    });

    // 7. Commit through repository (may apply further locking/transactions)
    await this.nodeRepo.save(node);

    // 8. Publish domain event (async, fire-and-forget)
    this.eventBus.publish(
      new NodeContentUpdatedEvent({
        nodeId: node.id.value,
        version: node.version.value,
        correlationId,
        editorId,
      }),
    );

    return node;
  }
}

// ────────────────────────────────────────────────────────────────────────────────
//  MOCK / PLACEHOLDER TYPE DECLARATIONS
//  (Remove once real implementations are available.)
//  These declarations exist solely to make the file compile in isolation
//  for the purpose of this prompt. In the real codebase, they already exist.
// ────────────────────────────────────────────────────────────────────────────────

/* eslint-disable @typescript-eslint/ban-types */

/* c8 ignore start */
declare module '../../../domain/entities/Node' {
  export interface Node {
    id: NodeId;
    type: string;
    version: Version;
    content: unknown;

    contentEquals(other: unknown): boolean;
    updateContent(
      newContent: unknown,
      meta: { updatedAt: Date; updatedBy: string },
    ): void;
  }
}

declare module '../../../domain/value-objects/NodeId' {
  export class NodeId {
    private constructor(value: string);
    static fromString(value: string): NodeId;
    readonly value: string;
  }
}

declare module '../../../domain/value-objects/Version' {
  export class Version {
    private constructor(value: number);
    readonly value: number;
    bump(): void;
  }
}

declare module '../../../domain/repositories/NodeRepository' {
  import { Node } from '../entities/Node';
  import { NodeId } from '../value-objects/NodeId';

  export interface NodeRepository {
    findById(id: NodeId): Promise<Node | null>;
    save(node: Node): Promise<void>;
  }
}

declare module '../../../domain/repositories/NodeRevisionRepository' {
  export interface NodeRevisionRepository {
    save(revision: {
      id: string;
      nodeId: any;
      previousContent: unknown;
      nextContent: unknown;
      editorId?: string;
      createdAt: Date;
    }): Promise<void>;
  }
}

declare module '../../../domain/events/DomainEventBus' {
  export interface DomainEventBus {
    publish(event: any): void | Promise<void>;
  }
}

declare module '../../../domain/events/NodeContentUpdatedEvent' {
  export class NodeContentUpdatedEvent {
    constructor(props: {
      nodeId: string;
      version: number;
      correlationId: string;
      editorId?: string;
    });
  }
}

declare module '../../../domain/services/NodeContentValidatorFactory' {
  export interface NodeContentValidator {
    validate(content: unknown): Promise<readonly string[]>;
  }

  export interface NodeContentValidatorFactory {
    forNodeType(type: string): NodeContentValidator;
  }
}
/* c8 ignore stop */
```