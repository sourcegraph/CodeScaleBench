```typescript
/**************************************************************************************************
 * StellarStage Carnival – Loot Entity
 * ------------------------------------------------------------
 * Domain entity that represents an on-chain “loot drop” earned
 * by show-pass holders while they interact with a live event.
 *
 *  • Immutable core identity (id, issuedAt)
 *  • Upgradable state (level, durability, traits)
 *  • Rich metadata for NFT rendering & royalty tracking
 *  • Emits domain events on critical life-cycle changes
 *
 * NOTE: Nothing in this file depends on infrastructure-specific
 *       details (e.g. web3, HTTP, DB). Adapters live elsewhere.
 *************************************************************************************************/

import { v4 as uuidV4 } from 'uuid';
import deepFreeze from 'deep-freeze';
import { Result, ok, err } from '../common/result';
import { AggregateRoot } from '../common/aggregate-root';
import { DomainEvent } from '../common/domain-event';

/* ============================================================================
 * Value Objects & Enumerations
 * ========================================================================== */

export enum LootCategory {
  SKIN        = 'SKIN',
  POWER_UP    = 'POWER_UP',
  ACCESS_PASS = 'ACCESS_PASS',
  TOKEN       = 'TOKEN',
}

export enum LootRarity {
  COMMON     = 'COMMON',
  RARE       = 'RARE',
  EPIC       = 'EPIC',
  LEGENDARY  = 'LEGENDARY',
}

export interface TraitModifier {
  key: string;
  value: string | number | boolean;
}

export type Immutable<T> = {
  readonly [K in keyof T]: Immutable<T[K]>;
};

/* ============================================================================
 * Domain-level DTO used to (de)serialize Loot state
 * ========================================================================== */
export interface LootProps {
  id?: string;
  name: string;
  description?: string;
  category: LootCategory;
  rarity: LootRarity;
  imageUrl?: string;
  totalSupply: number;    // total minted copies
  availableSupply: number; // how many are still claimable
  traits: TraitModifier[];
  issuedAt?: Date;
  updatedAt?: Date;
}

/* ============================================================================
 * Domain Events
 * ========================================================================== */
export class LootCreatedEvent implements DomainEvent {
  readonly occurredOn: Date = new Date();
  constructor(readonly lootId: string, readonly rarity: LootRarity) {}
}

export class LootSupplyDepletedEvent implements DomainEvent {
  readonly occurredOn: Date = new Date();
  constructor(readonly lootId: string) {}
}

export class LootClaimedEvent implements DomainEvent {
  readonly occurredOn: Date = new Date();
  constructor(readonly lootId: string, readonly claimantAddress: string) {}
}

/* ============================================================================
 * Aggregate Root
 * ========================================================================== */
export class Loot extends AggregateRoot<LootProps> {
  /* ------------------------------------------------------------------------
   * Factory
   * ---------------------------------------------------------------------- */
  static create(rawProps: LootProps): Result<Loot> {
    // --- Validation checks -------------------------------------------------
    if (!rawProps.name?.trim()) {
      return err('Loot must have a non-empty name.');
    }

    if (rawProps.totalSupply <= 0) {
      return err('totalSupply must be greater than zero.');
    }

    if (rawProps.availableSupply > rawProps.totalSupply) {
      return err('availableSupply cannot exceed totalSupply.');
    }

    const now = new Date();

    const props: LootProps = {
      ...rawProps,
      id: rawProps.id ?? uuidV4(),
      issuedAt: rawProps.issuedAt ?? now,
      updatedAt: rawProps.updatedAt ?? now,
      description: rawProps.description ?? '',
      imageUrl: rawProps.imageUrl ?? '',
      traits: rawProps.traits ?? [],
    };

    const loot = new Loot(props);

    // Emit creation event only on first instantiation (no id provided)
    if (!rawProps.id) {
      loot.addDomainEvent(new LootCreatedEvent(props.id!, props.rarity));
    }

    return ok(loot);
  }

  /* ------------------------------------------------------------------------
   * Business Logic
   * ---------------------------------------------------------------------- */

  /**
   * Claim a single copy of the loot. Will decrease availableSupply and
   * emit events if the supply reaches zero.
   */
  claim(claimantAddress: string): Result<void> {
    if (this.props.availableSupply <= 0) {
      return err('No more supply left to claim.');
    }

    this.props.availableSupply -= 1;
    this.touch();

    this.addDomainEvent(new LootClaimedEvent(this.id, claimantAddress));

    if (this.props.availableSupply === 0) {
      this.addDomainEvent(new LootSupplyDepletedEvent(this.id));
    }

    return ok(undefined);
  }

  /**
   * Admin-level operation used by DistributeLoot service when tokens are
   * airdropped from an external smart contract flow.
   */
  burn(quantity = 1): Result<void> {
    if (quantity <= 0) return err('Burn quantity must be positive.');
    if (quantity > this.props.availableSupply) {
      return err('Cannot burn more than the available supply.');
    }

    this.props.availableSupply -= quantity;
    this.touch();

    if (this.props.availableSupply === 0) {
      this.addDomainEvent(new LootSupplyDepletedEvent(this.id));
    }

    return ok(undefined);
  }

  /**
   * Fully immutable snapshot used by presenters / query handlers.
   */
  toDTO(): Immutable<LootProps> {
    // deep-freeze to guarantee external code cannot mutate the state
    return deepFreeze({ ...this.props });
  }

  /* ------------------------------------------------------------------------
   * Getters
   * ---------------------------------------------------------------------- */
  get id(): string {
    return this.props.id!;
  }

  get isDepleted(): boolean {
    return this.props.availableSupply === 0;
  }

  /* ------------------------------------------------------------------------
   * Private helpers
   * ---------------------------------------------------------------------- */
  private touch(): void {
    this.props.updatedAt = new Date();
  }

  /* ------------------------------------------------------------------------
   * Protected constructor forces creation via factory
   * ---------------------------------------------------------------------- */
  private constructor(props: LootProps) {
    super(props);
  }
}
```