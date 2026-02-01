```typescript
/****************************************************************************************
 * PaletteFlow Studio – Domain Layer                                                    *
 * File:        src/core/domain/entities/Node.ts                                        *
 * Description: Core entity representing a single canvas node.                         *
 * Author:      PaletteFlow Studio Core Team                                           *
 ****************************************************************************************/

import { v4 as uuidv4, validate as uuidValidate } from 'uuid';

/**
 * Pure value-object wrapping a UUID v4.
 * Guards against invalid identifiers and hides raw strings from the rest of the app.
 */
export class NodeId {
    private readonly _value: string;

    private constructor(id: string) {
        if (!uuidValidate(id)) {
            throw new Error(`Invalid NodeId provided: "${id}"`);
        }
        this._value = id;
    }

    /** Generates a brand-new identifier */
    public static create(): NodeId {
        return new NodeId(uuidv4());
    }

    /** Reconstitutes an identifier from persistence */
    public static fromString(id: string): NodeId {
        return new NodeId(id);
    }

    public toString(): string {
        return this._value;
    }

    public equals(other: NodeId): boolean {
        return this._value === other._value;
    }
}

/**
 * Semantic classification of a node (markdown, code, audio, etc.).
 * Extensible by plugins at runtime; therefore only minimal validation is applied.
 */
export class NodeType {
    private readonly _value: string;

    private constructor(type: string) {
        if (!type || type.trim().length === 0) {
            throw new Error('NodeType cannot be empty.');
        }
        this._value = type.trim();
    }

    public static of(type: string): NodeType {
        return new NodeType(type);
    }

    public toString(): string {
        return this._value;
    }

    public equals(other: NodeType): boolean {
        return this._value === other._value;
    }
}

/**
 * Simple 2-dimensional vector for positioning on the infinite canvas.
 */
export interface Vector2D {
    readonly x: number;
    readonly y: number;
}

/**
 * Domain-level metadata carried by every node.
 */
export interface NodeMetadata {
    readonly label: string;
    readonly createdAt: Date;
    readonly updatedAt: Date;
    readonly tags: ReadonlyArray<string>;
}

/**
 * Generic domain event definition.  Domain events are emitted by entities
 * but dispatched by the application layer; therefore they are kept minimal here.
 */
export interface DomainEvent<TPayload = unknown> {
    readonly type: string;
    readonly payload: TPayload;
    readonly occurredOn: Date;
}

/**
 * Wire-format used when persisting/reconstructing nodes.
 * NOTE: Kept separate from public API so that persistence migrations
 * don’t leak into business logic.
 */
export interface NodeSnapshot<TContent = unknown> {
    readonly id: string;
    readonly type: string;
    readonly position: Vector2D;
    readonly content: TContent;
    readonly metadata: NodeMetadata;
    readonly links: ReadonlyArray<string>; // Outgoing edges only
}

/**
 * Aggregate root representing a single canvas node.
 * The class is generic so that plugins can extend content shape in a type-safe manner.
 */
export class Node<TContent = unknown> {
    /***************************
     * Construction & Factory  *
     ***************************/
    private constructor(private readonly _id: NodeId,
                        private _type: NodeType,
                        private _position: Vector2D,
                        private _content: TContent,
                        private _metadata: NodeMetadata,
                        private readonly _outgoingLinks: Set<NodeId>) { }

    /**
     * Factory for new nodes created by the user/UI.
     */
    public static create<TContent>(
        params: {
            type: NodeType | string;
            position?: Vector2D;
            content?: TContent;
            label?: string;
            tags?: string[];
        }
    ): Node<TContent> {

        const now = new Date();
        return new Node<TContent>(
            NodeId.create(),
            typeof params.type === 'string' ? NodeType.of(params.type) : params.type,
            params.position ?? { x: 0, y: 0 },
            params.content ?? ({} as unknown as TContent),
            {
                label: params.label ?? '',
                createdAt: now,
                updatedAt: now,
                tags: Object.freeze(params.tags ?? [])
            },
            new Set()
        )._registerEvent('NodeCreated');
    }

    /**
     * Reconstitutes a node that was previously persisted.
     * No domain events are emitted because this does not represent a new business occurrence.
     */
    public static fromSnapshot<TContent>(snapshot: NodeSnapshot<TContent>): Node<TContent> {
        return new Node<TContent>(
            NodeId.fromString(snapshot.id),
            NodeType.of(snapshot.type),
            snapshot.position,
            snapshot.content,
            snapshot.metadata,
            new Set(snapshot.links.map(l => NodeId.fromString(l)))
        );
    }

    /*******************
     * Public Getters  *
     *******************/
    public get id(): NodeId {
        return this._id;
    }

    public get type(): NodeType {
        return this._type;
    }

    public get position(): Vector2D {
        return { ...this._position };
    }

    public get content(): TContent {
        // Defensive copy for plain objects; deep-copy is responsibility of caller.
        return (typeof this._content === 'object'
            ? { ...(this._content as Record<string, unknown>) }
            : this._content) as TContent;
    }

    public get metadata(): NodeMetadata {
        return { ...this._metadata, tags: [...this._metadata.tags] };
    }

    /**
     * IDs of nodes this node points to (directed graph).
     */
    public get outgoingLinks(): ReadonlyArray<NodeId> {
        return [...this._outgoingLinks];
    }

    /*******************************
     * Domain Behaviour / Mutators *
     *******************************/
    /**
     * Updates node content (marks metadata.updatedAt).
     */
    public updateContent(content: TContent): this {
        if (content === undefined) {
            throw new Error('Node content cannot be undefined.');
        }
        this._content = content;
        this._touch();
        return this._registerEvent('NodeContentUpdated', { content });
    }

    /**
     * Moves node to a new absolute position.
     */
    public moveTo(position: Vector2D): this {
        if (Number.isNaN(position.x) || Number.isNaN(position.y)) {
            throw new Error('Position must contain valid numbers.');
        }
        this._position = { x: position.x, y: position.y };
        this._touch();
        return this._registerEvent('NodeMoved', { position: this._position });
    }

    /**
     * Adds a directed link to another node.
     */
    public linkTo(target: NodeId): this {
        if (this._id.equals(target)) {
            throw new Error('A node cannot link to itself.');
        }
        if (this._outgoingLinks.has(target)) {
            return this; // Idempotent
        }
        this._outgoingLinks.add(target);
        this._touch();
        return this._registerEvent('NodeLinkAdded', { target: target.toString() });
    }

    /**
     * Removes a directed link to another node.
     */
    public unlinkFrom(target: NodeId): this {
        if (this._outgoingLinks.delete(target)) {
            this._touch();
            return this._registerEvent('NodeLinkRemoved', { target: target.toString() });
        }
        return this;
    }

    /**
     * Changes the node’s human-readable label.
     */
    public rename(label: string): this {
        if (label === undefined || label === null) {
            throw new Error('Label must be a defined string (can be empty).');
        }
        this._metadata = {
            ...this._metadata,
            label
        };
        this._touch();
        return this._registerEvent('NodeRenamed', { label });
    }

    /**
     * Replaces the entire tag array (immutable).
     */
    public setTags(tags: string[]): this {
        this._metadata = {
            ...this._metadata,
            tags: Object.freeze([...tags])
        };
        this._touch();
        return this._registerEvent('NodeTagsChanged', { tags: [...tags] });
    }

    /*****************************
     * Persistence / Serialization
     *****************************/
    public snapshot(): NodeSnapshot<TContent> {
        return {
            id: this._id.toString(),
            type: this._type.toString(),
            position: { ...this._position },
            content: this._content,
            metadata: this.metadata,
            links: this.outgoingLinks.map(l => l.toString())
        };
    }

    /**********************************
     * Domain Event Collection Helpers
     **********************************/
    private readonly _domainEvents: DomainEvent[] = [];

    public pullDomainEvents(): DomainEvent[] {
        const events = [...this._domainEvents];
        this._domainEvents.length = 0; // Clear queue
        return events;
    }

    private _registerEvent(type: string, payload: unknown = {}): this {
        this._domainEvents.push({
            type,
            payload,
            occurredOn: new Date()
        });
        return this;
    }

    private _touch(): void {
        this._metadata = {
            ...this._metadata,
            updatedAt: new Date()
        };
    }
}
```