```typescript
/***************************************************************************************************
 * File:    src/core/application/use-cases/node/UpdateNodePosition.ts
 * Project: PaletteFlow Studio (desktop_productivity)
 * Author:  PaletteFlow Core Team
 *
 * Description:
 *  Use-case that updates the coordinates of a Node on a Canvas.  While it looks deceptively simple,
 *  moving a node has a ripple-effect throughout the system: links must be re-routed, view-models
 *  need to animate, plugins may veto the move, and collaboration back-channels need deltas
 *  broadcasted.  This interactor isolates those concerns behind clean architecture boundaries.
 *
 *  – Validates input and entity invariants
 *  – Executes inside an ACID-like transaction provided by the Persistence layer
 *  – Notifies the domain event-bus so observers (view, plugin-SDK, collab service) react
 *  – Exposes a Result<E, A> functional style API for ergonomic error handling up-stack
 ***************************************************************************************************/

import { injectable, inject } from "tsyringe";
import { NodeRepository } from "../../ports/NodeRepository";
import { CanvasRepository } from "../../ports/CanvasRepository";
import { DomainEventBus } from "../../ports/DomainEventBus";
import { PluginHost } from "../../ports/PluginHost";
import { TransactionManager } from "../../ports/TransactionManager";
import { NodeId, CanvasId, UserId } from "../../../domain/value-objects";
import { Node } from "../../../domain/entities/Node";
import { NodePositionUpdated } from "../../../domain/events/NodePositionUpdated";

/* -------------------------------------------------------------------------- */
/*                                  Result<E,A>                               */
/* -------------------------------------------------------------------------- */

type Ok<A>    = { ok: true;  value: A };
type Err<E>   = { ok: false; error: E };
export type Result<E, A> = Ok<A> | Err<E>;

const ok   = <A>(value: A): Ok<A>      => ({ ok: true,  value });
const err  = <E>(error: E): Err<E>     => ({ ok: false, error });

/* -------------------------------------------------------------------------- */
/*                               Error Contracts                              */
/* -------------------------------------------------------------------------- */

export enum UpdateNodePositionErrorKind {
    INVALID_INPUT            = "INVALID_INPUT",
    NODE_NOT_FOUND           = "NODE_NOT_FOUND",
    CANVAS_NOT_FOUND         = "CANVAS_NOT_FOUND",
    NODE_NOT_IN_CANVAS       = "NODE_NOT_IN_CANVAS",
    PLUGIN_REJECTED_POSITION = "PLUGIN_REJECTED_POSITION",
    PERSISTENCE_ERROR        = "PERSISTENCE_ERROR"
}

export class UpdateNodePositionError extends Error {
    constructor(
        public readonly kind: UpdateNodePositionErrorKind,
        details?: string
    ) {
        super(`[UpdateNodePosition] ${kind}${details ? ` – ${details}` : ""}`);
        this.name = "UpdateNodePositionError";
    }
}

/* -------------------------------------------------------------------------- */
/*                                Input DTO                                   */
/* -------------------------------------------------------------------------- */

export interface UpdateNodePositionDTO {
    canvasId   : CanvasId;
    nodeId     : NodeId;
    x          : number;
    y          : number;
    initiatedBy: UserId;
}

/* -------------------------------------------------------------------------- */
/*                            UpdateNodePosition                              */
/* -------------------------------------------------------------------------- */

@injectable()
export class UpdateNodePosition {
    constructor(
        @inject("NodeRepository")
        private readonly nodeRepo: NodeRepository,

        @inject("CanvasRepository")
        private readonly canvasRepo: CanvasRepository,

        @inject("DomainEventBus")
        private readonly eventBus: DomainEventBus,

        @inject("PluginHost")
        private readonly pluginHost: PluginHost,

        @inject("TransactionManager")
        private readonly tx: TransactionManager
    ) {}

    /**
     * Executes the use-case.
     *
     * PRE-CONDITIONS
     *  – nodeId and canvasId are UUIDv4 strings
     *  – x and y are finite numbers
     * POST-CONDITIONS
     *  – Node’s position is updated in storage
     *  – Domain event is published
     */
    async execute(dto: UpdateNodePositionDTO): Promise<Result<UpdateNodePositionError, void>> {
        /* ------------------------------ Validation ------------------------------ */
        if (!this.isFiniteCoordinate(dto.x, dto.y)) {
            return err(new UpdateNodePositionError(
                UpdateNodePositionErrorKind.INVALID_INPUT,
                `Coordinates must be finite numbers. Received (${dto.x}, ${dto.y})`
            ));
        }

        /* ----------------------- Fetch Canvas + Node ------------------------ */
        const canvas = await this.canvasRepo.findById(dto.canvasId);
        if (!canvas) {
            return err(new UpdateNodePositionError(
                UpdateNodePositionErrorKind.CANVAS_NOT_FOUND,
                `Canvas <${dto.canvasId}> does not exist`
            ));
        }

        const node = await this.nodeRepo.findById(dto.nodeId);
        if (!node) {
            return err(new UpdateNodePositionError(
                UpdateNodePositionErrorKind.NODE_NOT_FOUND,
                `Node <${dto.nodeId}> does not exist`
            ));
        }

        if (!canvas.containsNode(node.id)) {
            return err(new UpdateNodePositionError(
                UpdateNodePositionErrorKind.NODE_NOT_IN_CANVAS,
                `Node <${dto.nodeId}> is not part of Canvas <${dto.canvasId}>`
            ));
        }

        /* ------------------ Plugin‐level veto / transformation ------------------ */
        const pluginDisposition = await this.pluginHost.hooks.beforeNodeMove.reduce(
            async (incomingPosition, hook) => hook(node, await incomingPosition),
            Promise.resolve({ x: dto.x, y: dto.y })
        );

        if (pluginDisposition === false) {
            return err(new UpdateNodePositionError(
                UpdateNodePositionErrorKind.PLUGIN_REJECTED_POSITION,
                `A plugin vetoed the node move.`
            ));
        }

        /* -------------------- Execute inside a transaction -------------------- */
        try {
            await this.tx.runInTransaction(async () => {
                const oldPosition = { ...node.position };
                node.moveTo(pluginDisposition.x, pluginDisposition.y);
                await this.nodeRepo.save(node);

                /* --------- Domain event lets observers (UI, collab) react -------- */
                await this.eventBus.publish(new NodePositionUpdated({
                    nodeId      : node.id,
                    canvasId    : dto.canvasId,
                    oldPosition,
                    newPosition : { ...node.position },
                    initiatedBy : dto.initiatedBy
                }));
            });
        } catch (e) {
            return err(new UpdateNodePositionError(
                UpdateNodePositionErrorKind.PERSISTENCE_ERROR,
                (e as Error).message
            ));
        }

        /* ------------------------------ Epilogue ----------------------------- */
        await this.pluginHost.hooks.afterNodeMove.forEach(hook =>
            hook(node, { x: node.position.x, y: node.position.y })
        );

        return ok(undefined);
    }

    /* ---------------------------------------------------------------------- */
    /*                                Helpers                                 */
    /* ---------------------------------------------------------------------- */

    private isFiniteCoordinate(x: number, y: number): boolean {
        return Number.isFinite(x) && Number.isFinite(y);
    }
}
```