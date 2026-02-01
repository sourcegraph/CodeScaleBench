```typescript
/**************************************************************************************************
 * PaletteFlow Studio
 * File: core/domain/entities/Canvas.ts
 *
 * The Canvas aggregate root. A Canvas is an infinite work-area that owns Nodes and Links
 * and can be themed.  It is a pure domain construct (framework-agnostic) and therefore
 * carries no knowledge about persistence, UI, or infrastructure concerns.
 **************************************************************************************************/

// ──────────────────────────────────────────────────────────────────────────────────────────
// Imports
// ──────────────────────────────────────────────────────────────────────────────────────────
import { UniqueEntityID } from '../value-objects/UniqueEntityID';
import { Guard } from '../logic/Guard';
import { DomainError } from '../errors/DomainError';
import { DomainEventPublisher } from '../events/DomainEventPublisher';
import { Node } from './Node';
import { Link } from './Link';

// ──────────────────────────────────────────────────────────────────────────────────────────
// Events
// ──────────────────────────────────────────────────────────────────────────────────────────

/** Dispatched whenever a new node is added to the canvas. */
export class NodeAddedToCanvas {
  readonly occurredOn = new Date();
  constructor(
    public readonly canvasId: UniqueEntityID,
    public readonly nodeId: UniqueEntityID
  ) {}
}

/** Dispatched whenever a link is added to the canvas. */
export class LinkCreatedOnCanvas {
  readonly occurredOn = new Date();
  constructor(
    public readonly canvasId: UniqueEntityID,
    public readonly linkId: UniqueEntityID
  ) {}
}

/** Dispatched when the canvas metadata itself changes (title, theme, etc.). */
export class CanvasModified {
  readonly occurredOn = new Date();
  constructor(public readonly canvasId: UniqueEntityID) {}
}

// ──────────────────────────────────────────────────────────────────────────────────────────
// Aggregate Root
// ──────────────────────────────────────────────────────────────────────────────────────────

interface CanvasProps {
  title: string;
  themeId?: UniqueEntityID;
  nodes?: Map<string, Node>;
  links?: Map<string, Link>;
  createdAt?: Date;
  updatedAt?: Date;
}

/**
 * Canvas aggregate root.
 *
 * Responsibilities:
 *  • Own nodes & links
 *  • Enforce invariants (no duplicate nodes, valid connections, etc.)
 *  • Publish domain events
 */
export class Canvas {
  // ── Factory ────────────────────────────────────────────────────────────────────────────
  public static create(props: CanvasProps, id?: UniqueEntityID): Canvas {
    const guard = Guard.againstNullOrUndefinedBulk([
      { argument: props.title, argumentName: 'title' }
    ]);
    if (!guard.succeeded) {
      throw new DomainError(guard.message);
    }

    return new Canvas(
      {
        title: props.title,
        themeId: props.themeId,
        nodes: props.nodes ?? new Map(),
        links: props.links ?? new Map(),
        createdAt: props.createdAt ?? new Date(),
        updatedAt: props.updatedAt ?? new Date()
      },
      id ?? UniqueEntityID.create()
    );
  }

  // ── Private Constructor ────────────────────────────────────────────────────────────────
  private constructor(private props: CanvasProps, private readonly _id: UniqueEntityID) {
    // invariant ‑ each link must connect nodes that actually exist on this canvas
    for (const link of this.props.links!.values()) {
      if (
        !this.props.nodes!.has(link.sourceId.toString()) ||
        !this.props.nodes!.has(link.targetId.toString())
      ) {
        throw new DomainError(
          `Link (${link.id}) references nodes that are not part of the canvas.`
        );
      }
    }
  }

  // ── Getters ────────────────────────────────────────────────────────────────────────────
  get id(): UniqueEntityID {
    return this._id;
  }

  get title(): string {
    return this.props.title;
  }

  get themeId(): UniqueEntityID | undefined {
    return this.props.themeId;
  }

  get createdAt(): Date {
    return this.props.createdAt!;
  }

  get updatedAt(): Date {
    return this.props.updatedAt!;
  }

  /** Returns a read-only snapshot of nodes. */
  get nodes(): ReadonlyMap<string, Node> {
    return new Map(this.props.nodes);
  }

  /** Returns a read-only snapshot of links. */
  get links(): ReadonlyMap<string, Link> {
    return new Map(this.props.links);
  }

  // ── Business Operations ────────────────────────────────────────────────────────────────

  /** Mutates title (trimmed) and fires a `CanvasModified` event. */
  rename(newTitle: string): void {
    const trimmed = newTitle.trim();
    if (!trimmed) {
      throw new DomainError('Canvas title cannot be empty.');
    }
    if (trimmed === this.props.title) {
      return; // no-op
    }
    this.props.title = trimmed;
    this.touch();
    DomainEventPublisher.publish(new CanvasModified(this.id));
  }

  /** Applies a theme to the canvas. */
  applyTheme(themeId: UniqueEntityID): void {
    if (this.props.themeId?.equals(themeId)) {
      return; // already applied
    }
    this.props.themeId = themeId;
    this.touch();
    DomainEventPublisher.publish(new CanvasModified(this.id));
  }

  /** Adds (or replaces) a node. */
  addNode(node: Node): void {
    if (!node) {
      throw new DomainError('Attempted to add an undefined node.');
    }
    this.props.nodes!.set(node.id.toString(), node);
    this.touch();
    DomainEventPublisher.publish(new NodeAddedToCanvas(this.id, node.id));
  }

  /** Removes a node and any links referencing it. */
  removeNode(nodeId: UniqueEntityID): void {
    const key = nodeId.toString();
    if (!this.props.nodes!.has(key)) {
      throw new DomainError(`Node (${key}) does not exist on this canvas.`);
    }
    this.props.nodes!.delete(key);

    // Cascade delete links
    for (const [linkId, link] of Array.from(this.props.links!.entries())) {
      if (
        link.sourceId.equals(nodeId) ||
        link.targetId.equals(nodeId)
      ) {
        this.props.links!.delete(linkId);
      }
    }

    this.touch();
    DomainEventPublisher.publish(new CanvasModified(this.id));
  }

  /** Creates and stores a new link between two existing nodes. */
  createLink(link: Link): void {
    if (!this.props.nodes!.has(link.sourceId.toString())) {
      throw new DomainError('Source node does not belong to this canvas.');
    }
    if (!this.props.nodes!.has(link.targetId.toString())) {
      throw new DomainError('Target node does not belong to this canvas.');
    }
    this.props.links!.set(link.id.toString(), link);
    this.touch();
    DomainEventPublisher.publish(new LinkCreatedOnCanvas(this.id, link.id));
  }

  /** Removes a link from the canvas. */
  removeLink(linkId: UniqueEntityID): void {
    const key = linkId.toString();
    if (!this.props.links!.has(key)) {
      throw new DomainError(`Link (${key}) not found on canvas.`);
    }
    this.props.links!.delete(key);
    this.touch();
    DomainEventPublisher.publish(new CanvasModified(this.id));
  }

  // ── Persistence/Serialization ──────────────────────────────────────────────────────────
  /** Serializes this aggregate into a plain JSON object safe for persistence. */
  toJSON(): object {
    return {
      id: this.id.toString(),
      title: this.title,
      themeId: this.themeId?.toString() ?? null,
      nodes: Array.from(this.props.nodes!.values()).map((n) => n.toJSON()),
      links: Array.from(this.props.links!.values()).map((l) => l.toJSON()),
      createdAt: this.createdAt.toISOString(),
      updatedAt: this.updatedAt.toISOString()
    };
  }

  /** Updates the `updatedAt` timestamp. */
  private touch(): void {
    this.props.updatedAt = new Date();
  }
}
```
