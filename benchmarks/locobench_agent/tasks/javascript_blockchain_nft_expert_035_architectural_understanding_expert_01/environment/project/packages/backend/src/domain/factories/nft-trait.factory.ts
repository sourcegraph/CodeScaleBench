```typescript
/***************************************************************************************************
 *  File: nft-trait.factory.ts
 *  Project: StellarStage Carnival ─ Interactive NFT Showrunner
 *  Description:
 *  Domain-layer factory responsible for producing the on-chain “traits” metadata that accompanies
 *  every Show-Pass (ERC-721).  Traits are composed at mint-time and subsequently recalculated when
 *  the underlying domain entities evolve (e.g. participation score goes up, an Act unlocks, etc.).
 *
 *  The factory employs:
 *    • Strategy Pattern – pluggable trait generators encapsulate discrete business rules
 *    • Functional-deterministic RNG – allows traits such as “rarity” to be reproduced off-chain
 *    • Clean Architecture – no external libs except Node crypto; all blockchain / persistence
 *      concerns live in infrastructure layer, not here.
 *
 *  NOTE: All imports that reference other domain entities (Show, Pass etc.) purposefully use the
 *  domain alias path so that this file remains framework-agnostic and 100 % unit-testable.
 ***************************************************************************************************/

import crypto from 'crypto';
import { uniqBy } from 'lodash-es';

/* Domain entities & value objects (defined elsewhere in domain layer) */
import type { Show } from '../entities/show.entity';
import type { Act } from '../entities/act.entity';
import type { Pass } from '../entities/pass.entity';

/* -------------------------------------------------------------------------------------------------
 * Shared Types
 * -----------------------------------------------------------------------------------------------*/

/**
 * A single ERC-721 metadata trait as per OpenSea & EIP-721 metadata standard.
 */
export interface NftTrait {
  trait_type: string;
  value: string | number;
  display_type?: 'number' | 'boost_number' | 'boost_percentage' | 'date';
  max_value?: number;
}

/**
 * Context object passed to every strategy.  Keeps domain objects loosely coupled from algorithm.
 */
export interface TraitGenerationContext {
  show: Show;
  currentAct: Act | null;
  pass: Pass;
  blockTimestamp: number;
  /** Deterministic random function seeded per token */
  rng: () => number;
}

/* -------------------------------------------------------------------------------------------------
 * Randomness Helper (deterministic, seed based)
 * -----------------------------------------------------------------------------------------------*/

/**
 * Functional-deterministic pseudo-random number generator based on HMAC-SHA256.
 * The RNG is *not* cryptographically secure against prediction, but it is:
 *   • deterministic – same inputs produce same outputs
 *   • side-effect-free – ideal for trait generation
 */
function createDeterministicRng(seed: string): () => number {
  let counter = 0;

  return () => {
    // Produce a 256-bit buffer derived from the seed + local counter
    const hash = crypto
      .createHmac('sha256', seed)
      .update(counter++ + '')
      .digest();

    // Convert first 4 bytes to little-endian unsigned int and normalise to [0, 1)
    const int = hash.readUInt32LE(0);
    return int / 0xffffffff;
  };
}

/* -------------------------------------------------------------------------------------------------
 * Strategy Interfaces
 * -----------------------------------------------------------------------------------------------*/

/**
 * Contract every trait generator must fulfil.
 */
export interface TraitGenerationStrategy {
  /**
   * Generate zero or more traits based on the provided context.
   * The returned traits *must not* contain duplicates with the same `trait_type`.
   */
  generate(ctx: TraitGenerationContext): NftTrait[];
}

/* -------------------------------------------------------------------------------------------------
 * Built-in Strategies
 * -----------------------------------------------------------------------------------------------*/

/**
 * Calculates a “Participation Level” trait derived from in-show interactions.
 */
class ParticipationStrategy implements TraitGenerationStrategy {
  generate({ pass }: TraitGenerationContext): NftTrait[] {
    // Guard-clause: defensive programming
    if (typeof pass.participationScore !== 'number') {
      return [];
    }

    const score = pass.participationScore;
    const level =
      score >= 1000 ? 'Legend'
      : score >= 500  ? 'Veteran'
      : score >= 100  ? 'Regular'
      :                 'Rookie';

    return [
      { trait_type: 'Participation Level', value: level },
      { trait_type: 'Participation Score', value: score, display_type: 'number' }
    ];
  }
}

/**
 * “Rarity Aura” is a cosmetic trait with three tiers.  Distribution is seeded per token.
 */
class RarityAuraStrategy implements TraitGenerationStrategy {
  generate({ rng }: TraitGenerationContext): NftTrait[] {
    const dice = rng();

    const aura =
      dice > 0.97 ? 'Mythic'
      : dice > 0.85 ? 'Epic'
      : dice > 0.60 ? 'Rare'
      :               'Common';

    return [{ trait_type: 'Rarity Aura', value: aura }];
  }
}

/**
 * Encodes staking information into NFT traits
 */
class StakingStrategy implements TraitGenerationStrategy {
  generate({ pass, blockTimestamp }: TraitGenerationContext): NftTrait[] {
    if (!pass.stakedAt) {
      return [{ trait_type: 'Staked', value: 'No' }];
    }

    const SECONDS_PER_DAY = 86_400;
    const daysStaked = Math.floor((blockTimestamp - pass.stakedAt) / SECONDS_PER_DAY);

    return [
      { trait_type: 'Staked', value: 'Yes' },
      {
        trait_type: 'Days Staked',
        value: daysStaked,
        display_type: 'boost_number',
        max_value: 365 /* 1 year cap shown in UI */
      }
    ];
  }
}

/**
 * Ties current Act (song, match, screening) into the NFT. Null-safe for show intermission.
 */
class ActProgressStrategy implements TraitGenerationStrategy {
  generate({ currentAct }: TraitGenerationContext): NftTrait[] {
    if (!currentAct) {
      return [{ trait_type: 'Current Act', value: 'Intermission' }];
    }

    return [
      { trait_type: 'Current Act', value: currentAct.title },
      { trait_type: 'Act Index', value: currentAct.index + 1, display_type: 'number' }
    ];
  }
}

/* -------------------------------------------------------------------------------------------------
 * The Factory
 * -----------------------------------------------------------------------------------------------*/

/**
 * Primary entry-point used by use-cases (MintShowPass, UpdateMetadata, …) to obtain traits.
 */
export class NftTraitFactory {
  private readonly strategies: TraitGenerationStrategy[];

  constructor(strategies: TraitGenerationStrategy[]) {
    if (!strategies.length) {
      throw new Error('NftTraitFactory requires at least one strategy');
    }
    this.strategies = strategies;
  }

  /**
   * Compose final trait array for a given Show-Pass.
   */
  public generate(options: {
    show: Show;
    act: Act | null;
    pass: Pass;
    blockTimestamp: number;
  }): NftTrait[] {
    const { pass } = options;

    // The seed must be unique and deterministic for the token
    const seed = `${options.show.id}:${pass.id}:${pass.ownerAddress}`;
    const rng = createDeterministicRng(seed);

    const ctx: TraitGenerationContext = {
      show: options.show,
      currentAct: options.act,
      pass,
      blockTimestamp: options.blockTimestamp,
      rng
    };

    // Collect and de-duplicate traits.  Later strategies may override earlier ones.
    const rawTraits = this.strategies.flatMap((strategy) => {
      try {
        return strategy.generate(ctx) || [];
      } catch (e) {
        // Log error via domain logger – replaced here by console for brevity
        console.error(
          `[TraitFactory] Strategy ${strategy.constructor.name} failed:`,
          (e as Error).message
        );
        return [];
      }
    });

    // `uniqBy` ensures each trait_type appears only once, later occurrences win.
    const traits = uniqBy(rawTraits.reverse(), 'trait_type').reverse();

    if (!traits.length) {
      throw new Error('No traits generated – at least one strategy must return data');
    }

    return traits;
  }

  /* ---------------------------------------------------------------------------
   * Factory helpers
   * -------------------------------------------------------------------------*/

  /**
   * Pre-packaged, opinionated factory with the default strategy set used across the project.
   */
  static createDefault(): NftTraitFactory {
    return new NftTraitFactory([
      new ParticipationStrategy(),
      new RarityAuraStrategy(),
      new StakingStrategy(),
      new ActProgressStrategy()
    ]);
  }
}

/* -------------------------------------------------------------------------------------------------
 * Convenience Re-Export
 * -----------------------------------------------------------------------------------------------*/

export default NftTraitFactory;
```