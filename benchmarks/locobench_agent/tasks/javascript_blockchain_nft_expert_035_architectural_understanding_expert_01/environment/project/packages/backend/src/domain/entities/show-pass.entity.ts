```typescript
// File: StellarStageCarnival/packages/backend/src/domain/entities/show-pass.entity.ts

/**
 * The ShowPass entity represents an up-gradable, stake-able NFT ticket that
 * grants access to a live show inside StellarStage Carnival.  It lives purely
 * in the domain layer and knows nothing about how/where it will be persisted
 * or minted on-chain.  All side-effects are exposed via Domain Events so that
 * application services and infrastructure adapters can react appropriately.
 */

import { v4 as uuid } from 'uuid';

/* -------------------------------------------------------------------------- */
/*                              Utility / Helpers                             */
/* -------------------------------------------------------------------------- */

type EthereumAddress = `0x${string}`;

/**
 * Very small address validator.  In a real code-base we might depend on
 * `ethers.utils.isAddress`, but the domain layer avoids heavy libs.
 */
function assertValidAddress(address: string): asserts address is EthereumAddress {
  const re = /^0x[a-fA-F0-9]{40}$/;
  if (!re.test(address)) {
    throw new DomainError(`Invalid Ethereum address: ${address}`);
  }
}

/* -------------------------------------------------------------------------- */
/*                                  Errors                                    */
/* -------------------------------------------------------------------------- */

export class DomainError extends Error {
  readonly name = 'DomainError';
}

/* -------------------------------------------------------------------------- */
/*                               Domain Events                                */
/* -------------------------------------------------------------------------- */

export interface DomainEvent<T = unknown> {
  readonly name: string;
  readonly payload: T;
  readonly occurredOn: Date;
}

/**
 * A super-lightweight synchronous event dispatcher used only in the domain
 * layer to register side-effect-free callbacks. Infrastructure code can wire
 * this up to a real bus (RabbitMQ, SNS, etc.) at the application boundary.
 */
export class DomainEvents {
  private static handlers: Map<string, Set<(event: DomainEvent) => void>> =
    new Map();

  static publish(event: DomainEvent): void {
    const listeners = this.handlers.get(event.name);
    if (!listeners?.size) return;

    listeners.forEach((cb) => {
      try {
        cb(event);
      } catch (err) {
        /* eslint-disable no-console */
        console.error(`[DomainEvents] Handler threw for event ${event.name}`, err);
        /* eslint-enable  no-console */
      }
    });
  }

  static subscribe(eventName: string, cb: (event: DomainEvent) => void): void {
    const listeners = this.handlers.get(eventName) ?? new Set();
    listeners.add(cb);
    this.handlers.set(eventName, listeners);
  }

  static clear(): void {
    this.handlers.clear();
  }
}

/* -------------------------------------------------------------------------- */
/*                               Value Objects                                */
/* -------------------------------------------------------------------------- */

/** A trait is a mutable property embedded in token metadata. */
export interface PassTrait {
  key: string;
  value: string | number | boolean;
  /** RFC-3339 ISO string; easier to serialize than Date. */
  lastUpdated: string;
}

/* -------------------------------------------------------------------------- */
/*                                Aggregate                                   */
/* -------------------------------------------------------------------------- */

interface ShowPassProps {
  tokenId: bigint; // On-chain tokenId (ERC-721 compatible).
  showId: string; // UUID of the Show aggregate this pass belongs to.
  owner: EthereumAddress;
  traits: PassTrait[];
  /** Unix millis where the pass began staking. 0 means not currently staked. */
  stakedAt: number;
  /** Total governance voting power accumulated by this pass. */
  governancePower: number;
  /** URI pointing to the IPFS JSON metadata. */
  metadataUri: string;
  /** Logical deletion flag. Burned tokens keep historical presence off-chain. */
  burned: boolean;
  /** Creation timestamp captured for audit trails. */
  createdAt: number;
  /** Last domain change timestamp. */
  updatedAt: number;
}

/**
 * Aggregate root representing a Show Pass.
 *
 * All state-mutating methods are synchronous and perform validation up-front,
 * emitting immutable Domain Events afterwards.
 */
export class ShowPass {
  /* ---------------------------------------------------------------------- */
  /*                                  Factory                               */
  /* ---------------------------------------------------------------------- */

  static mint(props: {
    showId: string;
    tokenId: bigint;
    initialOwner: EthereumAddress;
    metadataUri: string;
  }): ShowPass {
    assertValidAddress(props.initialOwner);

    const now = Date.now();

    const entity = new ShowPass({
      tokenId: props.tokenId,
      showId: props.showId,
      owner: props.initialOwner,
      traits: [],
      stakedAt: 0,
      governancePower: 0,
      metadataUri: props.metadataUri,
      burned: false,
      createdAt: now,
      updatedAt: now,
    });

    DomainEvents.publish({
      name: 'ShowPassMinted',
      payload: { showId: props.showId, tokenId: props.tokenId, owner: props.initialOwner },
      occurredOn: new Date(now),
    });

    return entity;
  }

  /* ---------------------------------------------------------------------- */
  /*                               Constructor                              */
  /* ---------------------------------------------------------------------- */

  /** Globally unique reference ID used internally/off-chain. */
  readonly id: string;

  private constructor(private readonly props: ShowPassProps) {
    this.id = uuid(); // Off-chain identifier (NOT the on-chain tokenId).
  }

  /* ---------------------------------------------------------------------- */
  /*                            Read-only getters                           */
  /* ---------------------------------------------------------------------- */

  get tokenId(): bigint {
    return this.props.tokenId;
  }

  get showId(): string {
    return this.props.showId;
  }

  get owner(): EthereumAddress {
    return this.props.owner;
  }

  get traits(): readonly PassTrait[] {
    // Expose an immutable snapshot
    return [...this.props.traits];
  }

  get governancePower(): number {
    return this.props.governancePower;
  }

  get isStaked(): boolean {
    return this.props.stakedAt > 0;
  }

  get isBurned(): boolean {
    return this.props.burned;
  }

  get metadataUri(): string {
    return this.props.metadataUri;
  }

  /* ---------------------------------------------------------------------- */
  /*                              Mutations                                 */
  /* ---------------------------------------------------------------------- */

  /**
   * Update or append trait(s). The previous value is overwritten and a new
   * `lastUpdated` timestamp is recorded.
   */
  evolve(traitUpdates: Record<string, string | number | boolean>): void {
    if (this.props.burned) throw new DomainError('Cannot evolve a burned pass');

    const nowIso = new Date().toISOString();

    Object.entries(traitUpdates).forEach(([key, value]) => {
      const existing = this.props.traits.find((t) => t.key === key);
      if (existing) {
        existing.value = value;
        existing.lastUpdated = nowIso;
      } else {
        this.props.traits.push({ key, value, lastUpdated: nowIso });
      }
    });

    this.touch();

    DomainEvents.publish({
      name: 'ShowPassEvolved',
      payload: { tokenId: this.props.tokenId, traitUpdates },
      occurredOn: new Date(),
    });
  }

  /**
   * Stake the pass. Throws if already staked or burned.
   */
  stake(): void {
    if (this.props.burned) throw new DomainError('Cannot stake a burned pass');
    if (this.isStaked) throw new DomainError('Pass already staked');

    this.props.stakedAt = Date.now();
    this.touch();

    DomainEvents.publish({
      name: 'ShowPassStaked',
      payload: { tokenId: this.props.tokenId, stakedAt: this.props.stakedAt },
      occurredOn: new Date(this.props.stakedAt),
    });
  }

  /**
   * Un-stake the pass, awarding governance power proportional to duration.
   */
  unstake(): void {
    if (!this.isStaked) throw new DomainError('Pass is not currently staked');

    const now = Date.now();
    const durationMs = now - this.props.stakedAt;
    const earnedPower = this.computeGovernancePower(durationMs);
    this.props.governancePower += earnedPower;

    this.props.stakedAt = 0;
    this.touch();

    DomainEvents.publish({
      name: 'ShowPassUnstaked',
      payload: { tokenId: this.props.tokenId, earnedPower },
      occurredOn: new Date(now),
    });
  }

  /**
   * Transfer pass ownership. Does NOT perform on-chain transfer—that is handled
   * elsewhere.  Domain validation ensures address format and non-burned state.
   */
  transfer(newOwner: EthereumAddress): void {
    assertValidAddress(newOwner);

    if (this.props.burned) throw new DomainError('Cannot transfer a burned pass');
    if (this.owner.toLowerCase() === newOwner.toLowerCase()) return; // no-op

    if (this.isStaked) {
      throw new DomainError('Cannot transfer a staked pass. Unstake first.');
    }

    const prevOwner = this.props.owner;
    this.props.owner = newOwner;
    this.touch();

    DomainEvents.publish({
      name: 'ShowPassTransferred',
      payload: {
        tokenId: this.props.tokenId,
        from: prevOwner,
        to: newOwner,
      },
      occurredOn: new Date(),
    });
  }

  /**
   * Burn (invalidate) the pass, preventing further interactions.  Once burned,
   * the token cannot be resurrected.
   */
  burn(reason?: string): void {
    if (this.props.burned) return;

    if (this.isStaked) {
      throw new DomainError('Cannot burn a staked pass. Unstake first.');
    }

    this.props.burned = true;
    this.touch();

    DomainEvents.publish({
      name: 'ShowPassBurned',
      payload: { tokenId: this.props.tokenId, reason },
      occurredOn: new Date(),
    });
  }

  /* ---------------------------------------------------------------------- */
  /*                               Internals                                */
  /* ---------------------------------------------------------------------- */

  private computeGovernancePower(durationMs: number): number {
    // Governance power is 1 point per full hour staked, capped at 1,000
    const hours = Math.floor(durationMs / 3_600_000);
    return Math.min(hours, 1_000);
  }

  private touch(): void {
    this.props.updatedAt = Date.now();
  }

  /* ---------------------------------------------------------------------- */
  /*                               Serialization                             */
  /* ---------------------------------------------------------------------- */

  /**
   * Convert the entity to a plain JSON-serializable object for persistence or
   * wire transport.  No functions or private state are leaked.
   */
  toJSON(): Readonly<ShowPassProps & { id: string }> {
    return Object.freeze({
      id: this.id,
      ...this.props,
      // Ensure we deep-clone nested arrays/objects for true immutability.
      traits: this.props.traits.map((t) => ({ ...t })),
    });
  }

  /**
   * Re-hydrate an entity from a persisted snapshot.  Only the Repository inside
   * the infrastructure layer should call this.
   */
  static fromPersistence(raw: ShowPassProps & { id: string }): ShowPass {
    const entity = new ShowPass({ ...raw });
    (entity as { id: string }).id = raw.id; // restore deterministic id
    return entity;
  }
}

```