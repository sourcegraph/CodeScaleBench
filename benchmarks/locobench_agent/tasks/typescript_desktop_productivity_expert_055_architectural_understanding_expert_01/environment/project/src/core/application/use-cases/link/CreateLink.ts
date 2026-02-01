```typescript
/**
 * PaletteFlow Studio
 * Copyright (c) PaletteFlow
 *
 * Use-case: CreateLink
 * ------------------------------------
 * Orchestrates the creation of a semantic link between two nodes that live
 * inside the same Canvas.  The flow:
 *
 *  1. Validate command payload (IDs, link type, metadata)
 *  2. Load aggregate roots (Canvas, Nodes) inside a Unit-of-Work
 *  3. Perform domain-level invariants on the entities
 *  4. Persist changes through repositories
 *  5. Publish domain events so subscribers (UI, plugins, analytics) react
 *
 * This file purposefully contains zero UI / framework logic so that it can be
 * executed from Electron, CLI tooling, or the plugin host alike.
 */

import { v4 as uuidv4 } from "uuid";

import { Link, LinkId } from "../../../domain/entities/Link";
import { NodeId } from "../../../domain/entities/Node";
import { CanvasId } from "../../../domain/entities/Canvas";

import { ILinkRepository } from "../../../domain/repositories/ILinkRepository";
import { INodeRepository } from "../../../domain/repositories/INodeRepository";
import { ICanvasRepository } from "../../../domain/repositories/ICanvasRepository";

import { IEventBus } from "../../../shared/kernel/IEventBus";
import { ILogger } from "../../../shared/kernel/ILogger";
import { IUnitOfWork, UnitOfWorkFactory } from "../../../shared/infra/UnitOfWork";

import {
  InvalidCommandError,
  NotFoundError,
  DomainInvariantError,
} from "../../../shared/errors";
import { DomainEventTypes } from "../../../domain/events/DomainEventTypes";

/**
 * Command object delivered by controllers or other use-cases
 */
export interface CreateLinkCommand {
  readonly canvasId: CanvasId;
  readonly sourceNodeId: NodeId;
  readonly targetNodeId: NodeId;
  readonly linkType: Link["type"];
  readonly meta?: Partial<Link["meta"]>;
}

/**
 * Response sent back to whoever dispatched the command
 */
export interface CreateLinkResponse {
  readonly link: Link;
}

/**
 * Primary orchestrator class.
 * All dependencies are injected so that tests can mock them.
 */
export class CreateLinkUseCase {
  private readonly canvasRepo: ICanvasRepository;
  private readonly nodeRepo: INodeRepository;
  private readonly linkRepo: ILinkRepository;
  private readonly eventBus: IEventBus;
  private readonly logger: ILogger;
  private readonly uowFactory: UnitOfWorkFactory;

  constructor(deps: {
    canvasRepository: ICanvasRepository;
    nodeRepository: INodeRepository;
    linkRepository: ILinkRepository;
    eventBus: IEventBus;
    logger: ILogger;
    unitOfWorkFactory: UnitOfWorkFactory;
  }) {
    this.canvasRepo = deps.canvasRepository;
    this.nodeRepo = deps.nodeRepository;
    this.linkRepo = deps.linkRepository;
    this.eventBus = deps.eventBus;
    this.logger = deps.logger;
    this.uowFactory = deps.unitOfWorkFactory;
  }

  /**
   * Public entry point used by controllers/adapters
   */
  async execute(command: CreateLinkCommand): Promise<CreateLinkResponse> {
    // Step 1: defensive validation on primitive data
    this.validateCommand(command);

    // Step 2: open Unit-of-Work → all operations either succeed or rollback
    const uow: IUnitOfWork = this.uowFactory();

    try {
      // Step 3: load aggregate roots (Canvas, Nodes)
      const [canvas, sourceNode, targetNode] = await Promise.all([
        this.canvasRepo.findById(command.canvasId, uow),
        this.nodeRepo.findById(command.sourceNodeId, uow),
        this.nodeRepo.findById(command.targetNodeId, uow),
      ]);

      if (!canvas) {
        throw new NotFoundError("Canvas", command.canvasId);
      }
      if (!sourceNode) {
        throw new NotFoundError("Node", command.sourceNodeId);
      }
      if (!targetNode) {
        throw new NotFoundError("Node", command.targetNodeId);
      }

      // Step 4: domain-level invariants
      this.ensureNodesBelongToCanvas(canvas.id, sourceNode.id, targetNode.id);
      this.ensureNotSelfLink(sourceNode.id, targetNode.id);
      await this.ensureNotDuplicateLink(
        sourceNode.id,
        targetNode.id,
        command.linkType,
      );

      // Step 5: create link entity & persist
      const link: Link = {
        id: this.generateLinkId(),
        canvasId: canvas.id,
        sourceNodeId: sourceNode.id,
        targetNodeId: targetNode.id,
        type: command.linkType,
        meta: {
          createdAt: new Date(),
          createdBy: canvas.ownerId,
          label: command.meta?.label ?? "",
          color: command.meta?.color ?? canvas.defaultTheme.linkColor,
          ...command.meta,
        },
      };

      await this.linkRepo.save(link, uow);

      // Step 6: commit changes (persist) before emitting events
      await uow.commit();

      // Step 7: publish domain event
      await this.eventBus.publish({
        type: DomainEventTypes.LINK_CREATED,
        payload: { link },
        occurredAt: new Date(),
      });

      this.logger.debug(
        `Link ${link.id} created between ${sourceNode.id} ↔ ${targetNode.id}`,
      );

      return { link };
    } catch (error) {
      // Let the unit-of-work rollback any in-flight changes
      await uow.rollback();
      this.logger.error("CreateLinkUseCase failed", {
        error,
        command,
      });
      throw error;
    }
  }

  /* ---------------------------------------------------------------------- */
  /* --------------------------- Private helpers -------------------------- */
  /* ---------------------------------------------------------------------- */

  private generateLinkId(): LinkId {
    return `link_${uuidv4()}` as LinkId;
  }

  private validateCommand(cmd: CreateLinkCommand) {
    const missing: string[] = [];
    if (!cmd.canvasId) missing.push("canvasId");
    if (!cmd.sourceNodeId) missing.push("sourceNodeId");
    if (!cmd.targetNodeId) missing.push("targetNodeId");
    if (!cmd.linkType) missing.push("linkType");

    if (missing.length > 0) {
      throw new InvalidCommandError(
        `CreateLinkCommand missing field(s): ${missing.join(", ")}`,
        { missing },
      );
    }
  }

  private ensureNotSelfLink(source: NodeId, target: NodeId) {
    if (source === target) {
      throw new DomainInvariantError(
        "Cannot create a link where source and target are the same node.",
      );
    }
  }

  private async ensureNotDuplicateLink(
    source: NodeId,
    target: NodeId,
    type: Link["type"],
  ) {
    const existing = await this.linkRepo.findBetweenNodes(source, target, type);
    if (existing) {
      throw new DomainInvariantError(
        `A link of type ${type} between nodes ${source} and ${target} already exists.`,
      );
    }
  }

  private ensureNodesBelongToCanvas(
    canvasId: CanvasId,
    source: NodeId,
    target: NodeId,
  ) {
    // Invariant is already enforced in database but we double-check here for
    // better error messages and easier unit testing.
    if (
      !source.startsWith(canvasId) ||
      !target.startsWith(canvasId)
    ) {
      throw new DomainInvariantError(
        `Cannot create links between nodes that belong to different canvases (canvasId=${canvasId}).`,
      );
    }
  }
}
```