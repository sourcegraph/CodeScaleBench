```typescript
/**
 * PaletteFlow Studio – Link Entity
 * ---------------------------------
 * A Link semantically connects two Canvas Nodes and carries additional
 * metadata such as directionality, display label and arbitrary user data.
 * Links live exclusively in the core domain layer and therefore know
 * nothing about persistence, rendering or UI frameworks.
 */

import { v4 as uuid } from 'uuid';
import { DomainEvent } from '../events/DomainEvent';
import { Result, ok, err } from '../lib/Result';
import { Guard } from '../lib/Guard';
import { UniqueEntityID } from '../value-objects/UniqueEntityID';
import { Entity } from '../base/Entity';

/**
 * Possible semantic link types.  Plugins may introduce additional types at runtime.
 * Because this is domain-layer code, we only ship the default ones here.
 */
export enum LinkType {
  Reference  = 'REFERENCE',   // “See also” / citation style
  Dependency = 'DEPENDENCY',  // A needs B
  Flow       = 'FLOW',        // Ordering / execution flow
  Annotation = 'ANNOTATION',  // Purely descriptive note
  Custom     = 'CUSTOM',      // Namespaced, plugin-defined semantics
}

/**
 * Data needed to construct a new Link.
 * Dates are optional because they are generated automatically when omitted.
 */
export interface LinkProps {
  sourceNodeId: UniqueEntityID;
  targetNodeId: UniqueEntityID;
  type: LinkType;
  label?: string;
  directed?: boolean;                     // Default: true
  metadata?: Record<string, unknown>;     // Arbitrary JSON-serializable blob
  createdAt?: Date;
  updatedAt?: Date;
}

/**
 * Simple domain event fired whenever a new Link is created.
 * Use-cases listen to this event to trigger side-effects (e.g. analytics).
 */
export class LinkCreated implements DomainEvent {
  readonly occurredAt: Date = new Date();
  constructor(public readonly linkId: UniqueEntityID) {}
}

/**
 * Aggregate Root representing a semantic connection between two nodes.
 */
export class Link extends Entity<LinkProps> {
  /**
   * Factory method that enforces invariants and returns a Result wrapper.
   */
  public static create(
    props: LinkProps,
    id: UniqueEntityID = new UniqueEntityID(uuid()),
  ): Result<Link> {
    /* ---------- Domain Invariant Guards ---------- */

    const guardResult = Guard.againstNullOrUndefinedBulk([
      { argument: props.sourceNodeId, argumentName: 'sourceNodeId' },
      { argument: props.targetNodeId, argumentName: 'targetNodeId' },
      { argument: props.type,          argumentName: 'type' },
    ]);

    if (guardResult.isFailure) {
      return err(guardResult.error);
    }

    if (props.sourceNodeId.equals(props.targetNodeId)) {
      return err(new Error('A Link cannot connect a node to itself.'));
    }

    /* ---------- Apply Defaults ---------- */

    const now = new Date();
    const defaulted: LinkProps = {
      ...props,
      directed: props.directed ?? true,
      createdAt: props.createdAt ?? now,
      updatedAt: props.updatedAt ?? now,
    };

    const link = new Link(defaulted, id);
    link.addDomainEvent(new LinkCreated(link.id));

    return ok(link);
  }

  /* ---------- Business Behaviors ---------- */

  /**
   * Change the link type (e.g. from REFERENCE to DEPENDENCY).
   */
  public changeType(newType: LinkType): void {
    if (this.props.type === newType) return;

    this.props.type = newType;
    this.touch();
  }

  /**
   * Human-readable label shown in the Canvas UI.
   */
  public rename(newLabel: string | undefined): void {
    if (this.props.label === newLabel) return;

    this.props.label = newLabel?.trim();
    this.touch();
  }

  /**
   * Upsert arbitrary user metadata.  Pass `undefined` to remove a key.
   */
  public setMetadata(key: string, value: unknown): void {
    Guard.againstNullOrUndefined(key, 'metadata key');
    if (!this.props.metadata) this.props.metadata = {};

    if (value === undefined) {
      delete this.props.metadata[key];
    } else {
      this.props.metadata[key] = value;
    }
    this.touch();
  }

  /**
   * Swap source and target while preserving direction flag.
   */
  public reverse(): void {
    [this.props.sourceNodeId, this.props.targetNodeId] = [
      this.props.targetNodeId,
      this.props.sourceNodeId,
    ];
    this.touch();
  }

  /**
   * Convert the entity into a serializable plain object for persistence.
   * (Repositories & data mappers rely on this.)
   */
  public toPrimitive(): Readonly<Required<LinkProps> & { id: string }> {
    return Object.freeze({
      id: this.id.toString(),
      sourceNodeId: this.props.sourceNodeId.toString(),
      targetNodeId: this.props.targetNodeId.toString(),
      label: this.props.label,
      type: this.props.type,
      directed: this.props.directed!,
      metadata: { ...this.props.metadata },
      createdAt: new Date(this.props.createdAt!),
      updatedAt: new Date(this.props.updatedAt!),
    });
  }

  /* ---------- Helpers ---------- */

  private touch(): void {
    this.props.updatedAt = new Date();
  }

  private constructor(props: LinkProps, id: UniqueEntityID) {
    super(props, id);
  }
}
```