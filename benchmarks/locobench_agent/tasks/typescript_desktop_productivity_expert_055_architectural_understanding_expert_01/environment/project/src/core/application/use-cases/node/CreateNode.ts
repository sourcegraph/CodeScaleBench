```typescript
/**************************************************************************************************
 * PaletteFlow Studio
 * File:        src/core/application/use-cases/node/CreateNode.ts
 * Description: Application-layer use-case responsible for instantiating a brand-new canvas node,
 *              delegating validation to the domain layer, leveraging the plugin system to resolve
 *              node-type capabilities, persisting the result, and emitting domain events.
 *
 *              This file purposefully does NOT import from UI/Framework layers to keep the
 *              application service completely framework-agnostic (Clean Architecture).
 *************************************************************************************************/

import { Inject } from 'inversify'; // IOC helper (used across the codebase)
import { v4 as uuidv4 } from 'uuid';

import { TYPES } from '../../../ioc/types';
import { NodeRepository } from '../../../domain/ports/repositories/NodeRepository';
import { CanvasRepository } from '../../../domain/ports/repositories/CanvasRepository';
import { TransactionManager } from '../../../domain/ports/repositories/TransactionManager';
import { EventBus } from '../../../domain/ports/event-bus/EventBus';
import { PluginRegistry } from '../../../domain/ports/plugins/PluginRegistry';

import { Node } from '../../../domain/entities/Node';
import { Canvas } from '../../../domain/entities/Canvas';
import { NodeCreatedDomainEvent } from '../../../domain/events/NodeCreatedDomainEvent';

/**
 * Command data required to create a node.
 * (Use simple interface over a class to facilitate serialisation in case of async queues.)
 */
export interface CreateNodeCommand {
    readonly canvasId: string;
    readonly nodeType: string;
    readonly position: { x: number; y: number };
    readonly initialContent?: unknown;          // content is type-specific – left as unknown
    readonly requestedByUserId: string;         // audit / permission checks
}

/**
 * Return DTO for the newly created node.
 */
export interface CreateNodeResult {
    readonly nodeId: string;
    readonly canvasId: string;
    readonly nodeType: string;
    readonly createdAt: Date;
}

/**
 * Domain-level error thrown when the node type cannot be resolved via the plugin registry.
 */
export class UnknownNodeTypeError extends Error {
    constructor(public readonly nodeType: string) {
        super(`Unknown node type "${nodeType}". No plugin registered such node.`);
        Object.setPrototypeOf(this, new.target.prototype);
    }
}

/**
 * Application service orchestrating "create node" use case.
 * NOTE: The class is intentionally stateless; dependencies are injected via constructor.
 */
export class CreateNode {
    constructor(
        @Inject(TYPES.NodeRepository)
        private readonly nodeRepository: NodeRepository,

        @Inject(TYPES.CanvasRepository)
        private readonly canvasRepository: CanvasRepository,

        @Inject(TYPES.TransactionManager)
        private readonly txManager: TransactionManager,

        @Inject(TYPES.EventBus)
        private readonly eventBus: EventBus,

        @Inject(TYPES.PluginRegistry)
        private readonly pluginRegistry: PluginRegistry
    ) {}

    /**
     * Public facing API.
     */
    async execute(command: CreateNodeCommand): Promise<CreateNodeResult> {
        // Validate command upfront (fast-fail)
        this.assertValidCommand(command);

        // Resolve the node type implementation via plugin registry
        const nodeBlueprint = this.pluginRegistry.getNodeBlueprint(command.nodeType);
        if (!nodeBlueprint) {
            throw new UnknownNodeTypeError(command.nodeType);
        }

        // Fetch the canvas inside the transaction to avoid dirty reads
        return this.txManager.withTransaction(async () => {
            const canvas: Canvas = await this.canvasRepository.findById(command.canvasId);
            if (!canvas) {
                throw new Error(`Canvas "${command.canvasId}" does not exist.`);
            }

            // Ask the domain entity to verify that the user can modify it
            canvas.assertWriteAccess(command.requestedByUserId);

            // Build the new Node aggregate
            const nodeId = uuidv4();
            const now = new Date();

            const node: Node = Node.create({
                id: nodeId,
                type: command.nodeType,
                position: command.position,
                content: command.initialContent,
                createdAt: now,
                updatedAt: now,
                createdBy: command.requestedByUserId,
                // domain entity may enforce invariants such as "position cannot be NaN"
            }, nodeBlueprint);

            // Persist node first so it owns its ID in persistence layer
            await this.nodeRepository.save(node);

            // Update canvas (domain rule: a node must belong to a canvas)
            canvas.addNode(node);
            await this.canvasRepository.save(canvas);

            // Emit domain event (both in-process and to any eventual outbox)
            const event = new NodeCreatedDomainEvent({
                canvasId: canvas.id,
                nodeId: node.id,
                nodeType: node.type,
                occurredAt: now,
                initiatedBy: command.requestedByUserId
            });
            await this.eventBus.publish(event);

            // Return DTO (never leak domain entity outside use case boundary)
            const result: CreateNodeResult = {
                nodeId: node.id,
                canvasId: canvas.id,
                nodeType: node.type,
                createdAt: now
            };
            return result;
        });
    }

    /* ---------------------------------------------------------------------- */
    /* PRIVATE HELPERS                                                        */
    /* ---------------------------------------------------------------------- */

    private assertValidCommand(cmd: CreateNodeCommand): void {
        if (!cmd.canvasId?.trim()) {
            throw new Error('canvasId must be provided.');
        }
        if (!cmd.nodeType?.trim()) {
            throw new Error('nodeType must be provided.');
        }
        if (typeof cmd.position?.x !== 'number' || typeof cmd.position?.y !== 'number') {
            throw new Error('position must contain numeric x and y values.');
        }
        if (!cmd.requestedByUserId?.trim()) {
            throw new Error('requestedByUserId is required for auditing.');
        }
    }
}
```