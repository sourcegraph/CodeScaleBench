```typescript
/******************************************************************************************
 *  StellarStage Carnival – Show Aggregate Root
 *  File:  packages/backend/src/domain/entities/show.entity.ts
 *
 *  Description:
 *  The Show entity represents a single interactive performance (concert, esport match,
 *  film festival, etc.) within StellarStage Carnival.  It is the aggregate-root that
 *  owns Acts, controls the performance state machine, and raises domain-events consumed
 *  by application-services (e.g. MintShowPass, DistributeLoot, CastLiveVote).
 *
 *  NOTE:  This entity purposefully has ZERO knowledge of persistence, blockchain,
 *  GraphQL or any other infrastructure detail.  Those concerns live behind adapters
 *  injected at the application service layer, in accordance with Clean Architecture.
 ******************************************************************************************/

import { v4 as uuidv4 } from 'uuid';

/* -------------------------------------------------------------------------- */
/*                               Value Objects                                */
/* -------------------------------------------------------------------------- */

/** Simple opaque identifier for an Aggregate or Entity */
export type UniqueId = string;

/** Helper to generate a cryptographically-random identifier */
export const createUniqueId = (): UniqueId => uuidv4();

/* -------------------------------------------------------------------------- */
/*                                 Errors                                     */
/* -------------------------------------------------------------------------- */

/** Domain-error thrown on invalid state transitions, invariant violations, etc. */
export class DomainError extends Error {
  constructor(message: string) {
    super(`DomainError: ${message}`);
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/* -------------------------------------------------------------------------- */
/*                           Domain Event Contracts                           */
/* -------------------------------------------------------------------------- */

export interface DomainEvent<TPayload = unknown> {
  readonly name: string;
  readonly occurredAt: Date;
  readonly aggregateId: UniqueId;
  readonly payload: TPayload;
}

/** micro-helper to decorate event objects */
function createEvent<TPayload>(
  aggregateId: UniqueId,
  name: string,
  payload: TPayload,
): DomainEvent<TPayload> {
  return {
    name,
    occurredAt: new Date(),
    aggregateId,
    payload,
  };
}

/* -------------------------------------------------------------------------- */
/*                               Act Entity                                   */
/* -------------------------------------------------------------------------- */

/**
 *  An Act represents a sub-segment of a Show (opening band, comedian, film block, etc.)
 *  It is a lightweight child-entity owned by the Show aggregate.
 *  In a full implementation this would live in its own file, but it is embedded here
 *  for brevity / compilation isolation.
 */
export interface ActProps {
  readonly id?: UniqueId;
  readonly title: string;
  readonly performer: string;
  readonly ordinal: number; // position within the line-up
}

export class Act {
  public readonly id: UniqueId;
  public readonly title: string;
  public readonly performer: string;
  public readonly ordinal: number;

  constructor(props: ActProps) {
    this.id = props.id ?? createUniqueId();
    this.title = props.title;
    this.performer = props.performer;
    this.ordinal = props.ordinal;
  }
}

/* -------------------------------------------------------------------------- */
/*                            Show Lifecycle State                            */
/* -------------------------------------------------------------------------- */

export enum ShowStatus {
  Scheduled = 'SCHEDULED',
  Live = 'LIVE',
  Paused = 'PAUSED',
  Finished = 'FINISHED',
  Cancelled = 'CANCELLED',
}

/** Valid state-machine transitions for the Show aggregate */
const ALLOWED_TRANSITIONS: Record<ShowStatus, ShowStatus[]> = {
  [ShowStatus.Scheduled]: [ShowStatus.Live, ShowStatus.Cancelled],
  [ShowStatus.Live]: [ShowStatus.Paused, ShowStatus.Finished, ShowStatus.Cancelled],
  [ShowStatus.Paused]: [ShowStatus.Live, ShowStatus.Finished, ShowStatus.Cancelled],
  [ShowStatus.Finished]: [],
  [ShowStatus.Cancelled]: [],
};

/* -------------------------------------------------------------------------- */
/*                               Show Entity                                  */
/* -------------------------------------------------------------------------- */

export interface ShowProps {
  readonly id?: UniqueId;
  readonly title: string;
  readonly description?: string;
  readonly scheduledStart: Date;
  /** Acts included in this show; must be in ascending ordinal order */
  readonly acts?: Act[];
  /** Number of NFTs available for minting; 0 means unlimited */
  readonly maxPassSupply?: number;
}

export interface ShowSnapshot extends Omit<ShowProps, 'acts'> {
  acts: ActProps[];
  status: ShowStatus;
  version: number;
}

/**
 * Aggregate-root representing a single Show
 */
export class Show {
  /* --------------------------------- core --------------------------------- */

  private readonly _id: UniqueId;
  private _title: string;
  private _description?: string;
  private _scheduledStart: Date;
  private _status: ShowStatus = ShowStatus.Scheduled;
  private _acts: Act[] = [];
  private _maxPassSupply?: number;

  /**
   * Internal optimistic-locking version. Incremented on every mutation so that
   * out-of-date writes can be rejected by repositories/persistence adapters.
   */
  private _version = 0;

  /** Collected domain-events awaiting dispatch */
  private readonly _events: DomainEvent[] = [];

  /* ------------------------------- factory -------------------------------- */

  private constructor(props: ShowProps) {
    this._id = props.id ?? createUniqueId();
    this._title = props.title;
    this._description = props.description;
    this._scheduledStart = props.scheduledStart;
    this._acts = [...(props.acts ?? [])].sort((a, b) => a.ordinal - b.ordinal);
    this._maxPassSupply = props.maxPassSupply;
  }

  public static create(props: ShowProps): Show {
    const show = new Show(props);
    show.raiseEvent(
      createEvent(show.id, 'ShowScheduled', {
        title: show._title,
        scheduledStart: show._scheduledStart,
      }),
    );
    return show;
  }

  /* ------------------------- public read accessors ------------------------ */

  get id(): UniqueId {
    return this._id;
  }

  get title(): string {
    return this._title;
  }

  get description(): string | undefined {
    return this._description;
  }

  get scheduledStart(): Date {
    return this._scheduledStart;
  }

  get status(): ShowStatus {
    return this._status;
  }

  get version(): number {
    return this._version;
  }

  get acts(): readonly Act[] {
    return this._acts;
  }

  get maxPassSupply(): number | undefined {
    return this._maxPassSupply;
  }

  get events(): readonly DomainEvent[] {
    return this._events;
  }

  /* ---------------------------- state machine ----------------------------- */

  /**
   * Starts the live show. Only allowed from the Scheduled or Paused states.
   */
  public start(): void {
    this.transitionTo(ShowStatus.Live, 'ShowStarted', {
      liveAt: new Date(),
    });
  }

  /** Temporarily pauses a live show (e.g. technical difficulties, encore break) */
  public pause(): void {
    this.transitionTo(ShowStatus.Paused, 'ShowPaused', {
      pausedAt: new Date(),
    });
  }

  /** Finishes a show; no further passes can be used to earn XP, etc. */
  public finish(): void {
    this.transitionTo(ShowStatus.Finished, 'ShowFinished', {
      finishedAt: new Date(),
    });
  }

  /** Cancels a show prior to completion (e.g. weather, artist illness) */
  public cancel(): void {
    this.transitionTo(ShowStatus.Cancelled, 'ShowCancelled', {
      cancelledAt: new Date(),
    });
  }

  /**
   * Core transition logic enforcing allowed state changes and publishing events
   */
  private transitionTo(
    nextStatus: ShowStatus,
    eventName: string,
    payload: Record<string, unknown> = {},
  ): void {
    if (!ALLOWED_TRANSITIONS[this._status].includes(nextStatus)) {
      throw new DomainError(
        `Invalid status transition: ${this._status} → ${nextStatus}`,
      );
    }
    this._status = nextStatus;
    this._version += 1;
    this.raiseEvent(createEvent(this.id, eventName, payload));
  }

  /* ------------------------------ mutations ------------------------------- */

  /**
   * Update the show metadata. Can be performed anytime before Finished/Cancelled.
   */
  public updateMetadata(params: {
    title?: string;
    description?: string;
    scheduledStart?: Date;
  }): void {
    if ([ShowStatus.Finished, ShowStatus.Cancelled].includes(this._status)) {
      throw new DomainError('Cannot update a finished or cancelled show');
    }

    let changed = false;

    if (params.title && params.title !== this._title) {
      this._title = params.title;
      changed = true;
    }
    if (
      params.description !== undefined &&
      params.description !== this._description
    ) {
      this._description = params.description;
      changed = true;
    }
    if (
      params.scheduledStart &&
      params.scheduledStart.getTime() !== this._scheduledStart.getTime()
    ) {
      if (params.scheduledStart < new Date()) {
        throw new DomainError('scheduledStart cannot be set in the past');
      }
      this._scheduledStart = params.scheduledStart;
      changed = true;
    }

    if (changed) {
      this._version += 1;
      this.raiseEvent(
        createEvent(this.id, 'ShowMetadataUpdated', {
          title: this._title,
          description: this._description,
          scheduledStart: this._scheduledStart,
        }),
      );
    }
  }

  /** Insert a new Act into the lineup; rejects duplicate ordinals or ids */
  public addAct(actProps: Omit<ActProps, 'ordinal'> & { ordinal?: number }): Act {
    if (
      [ShowStatus.Finished, ShowStatus.Cancelled, ShowStatus.Live].includes(
        this._status,
      )
    ) {
      throw new DomainError('Cannot add acts once the show has started/ended');
    }

    const ordinal =
      actProps.ordinal ?? (this._acts.length ? this._acts[this._acts.length - 1].ordinal + 1 : 1);

    if (this._acts.some(a => a.ordinal === ordinal)) {
      throw new DomainError(`Act with ordinal ${ordinal} already exists`);
    }
    if (actProps.id && this._acts.some(a => a.id === actProps.id)) {
      throw new DomainError(`Act with id ${actProps.id} already exists`);
    }

    const act = new Act({ ...actProps, ordinal });
    this._acts.push(act);
    this._acts.sort((a, b) => a.ordinal - b.ordinal);

    this._version += 1;
    this.raiseEvent(
      createEvent(this.id, 'ActAdded', {
        actId: act.id,
        ordinal: act.ordinal,
        title: act.title,
        performer: act.performer,
      }),
    );

    return act;
  }

  /** Remove an act by id */
  public removeAct(actId: UniqueId): void {
    const idx = this._acts.findIndex(a => a.id === actId);
    if (idx === -1) {
      throw new DomainError(`Act ${actId} not found`);
    }
    if (
      [ShowStatus.Live, ShowStatus.Paused, ShowStatus.Finished].includes(
        this._status,
      )
    ) {
      throw new DomainError('Cannot remove acts once the show has started');
    }

    const [removed] = this._acts.splice(idx, 1);
    this._acts.sort((a, b) => a.ordinal - b.ordinal);
    this._version += 1;
    this.raiseEvent(
      createEvent(this.id, 'ActRemoved', {
        actId: removed.id,
        removedAt: new Date(),
      }),
    );
  }

  /* --------------------------- Event management --------------------------- */

  private raiseEvent(event: DomainEvent): void {
    this._events.push(event);
  }

  /**
   * Pulls and clears all pending domain-events.
   * Repositories call this right before persisting.
   */
  public pullEvents(): DomainEvent[] {
    return this._events.splice(0, this._events.length);
  }

  /* ---------------------------- persistence ------------------------------- */

  /**
   * Build an aggregate from the persistence layer.
   * Do NOT call directly from production code; use ShowRepository.
   */
  public static rehydrate(snapshot: ShowSnapshot): Show {
    const show = new Show({
      ...snapshot,
      acts: snapshot.acts.map(props => new Act(props)),
    });
    show._status = snapshot.status;
    show._version = snapshot.version;
    return show;
  }

  /**
   * Produce a plain object for persistence serialization.
   */
  public toSnapshot(): ShowSnapshot {
    return {
      id: this._id,
      title: this._title,
      description: this._description,
      scheduledStart: this._scheduledStart,
      acts: this._acts.map(a => ({
        id: a.id,
        title: a.title,
        performer: a.performer,
        ordinal: a.ordinal,
      })),
      status: this._status,
      version: this._version,
      maxPassSupply: this._maxPassSupply,
    };
  }
}
```