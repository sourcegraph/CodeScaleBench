```typescript
/**************************************************************************************************
 *  StellarStage Carnival – ParticipationBasedTraitStrategy
 *  --------------------------------------------------------
 *  Calculates dynamic NFT trait deltas driven by a fan’s real-time participation metrics.
 *
 *  – Follows the Strategy Pattern: interchangeable trait algorithms plug into the minting service
 *    through the common `TraitStrategy` port.
 *  – Isolates pure domain logic from blockchain / persistence concerns (Clean Architecture).
 *  – Uses a non-linear scoring curve with exponential decay to reward continuous engagement while
 *    preventing “whale” domination.
 **************************************************************************************************/

/* eslint-disable @typescript-eslint/no-magic-numbers */

import clamp from 'lodash/clamp';
import { Logger } from 'pino';

import { TraitStrategy } from './trait-strategy.port';
import { Clock } from '../ports/clock.port';
import { DomainError } from '../../domain/errors/domain.error';
import {
  ParticipationSnapshot,
  ParticipationType,
} from '../../domain/value-objects/participation.vo';
import {
  TraitMutation,
  TraitMutationMap,
} from '../../domain/value-objects/trait.vo';
import { ShowPass } from '../../domain/entities/show-pass.entity';

// ────────────────────────────────────────────────────────────────────────────────
//  CONFIGURATION
// ────────────────────────────────────────────────────────────────────────────────

/**
 * Configuration object injected from the DI container / env-specific module.
 * This keeps tunable parameters away from the algorithmic core.
 */
export interface ParticipationTraitConfig {
  readonly logger?: Logger;
  readonly maxAttendanceStreak: number; // clamp for loyalty trait
  readonly hypeHalfLifeDays: number; // exponential decay for hype
  readonly repHalfLifeDays: number; // exponential decay for reputation
  readonly nowFn?: () => Date; // test seam
}

/** Reasonable defaults for most environments. */
const DEFAULT_CONFIG: Readonly<ParticipationTraitConfig> = {
  maxAttendanceStreak: 90,
  hypeHalfLifeDays: 3,
  repHalfLifeDays: 28,
};

// ────────────────────────────────────────────────────────────────────────────────
//  STRATEGY IMPLEMENTATION
// ────────────────────────────────────────────────────────────────────────────────

/**
 * ParticipationBasedTraitStrategy
 *
 * Converts a participation snapshot into trait mutations (“Hype”, “Reputation”,
 * “Loyalty”). The algorithm is deterministic and side-effect free.
 */
export class ParticipationBasedTraitStrategy implements TraitStrategy {
  private readonly cfg: ParticipationTraitConfig;

  constructor(
    private readonly clock: Clock,
    cfg?: Partial<ParticipationTraitConfig>,
  ) {
    this.cfg = { ...DEFAULT_CONFIG, ...cfg };
    this.cfg.logger?.debug(
      { cfg: this.cfg },
      'ParticipationBasedTraitStrategy initialised.',
    );
  }

  /** Primary entry point expected by the TraitStrategy port. */
  public async generateTraitMutations(
    pass: ShowPass,
    snapshot: ParticipationSnapshot,
  ): Promise<TraitMutation[]> {
    this.guard(pass, snapshot);

    // Calculate each trait separately to keep complexity isolated.
    const hype = this.calculateHype(pass, snapshot);
    const reputation = this.calculateReputation(pass, snapshot);
    const loyalty = this.calculateLoyalty(snapshot);

    const mutations: TraitMutationMap = {
      HYPE: hype,
      REPUTATION: reputation,
      LOYALTY: loyalty,
    };

    this.cfg.logger?.info(
      {
        tokenId: pass.id.toString(),
        mutations,
        snapshot,
      },
      'Generated trait mutations from participation snapshot.',
    );

    return Object.entries(mutations).map(([traitType, value]) => ({
      traitType,
      value,
    }));
  }

  // ──────────────────────────────────────────────────────────────────────────
  //  GUARDS
  // ──────────────────────────────────────────────────────────────────────────

  /** Fails fast for obviously invalid data. */
  private guard(pass: ShowPass, snapshot: ParticipationSnapshot): void {
    if (!pass) {
      throw new DomainError('ShowPass is required.');
    }
    if (!snapshot) {
      throw new DomainError('ParticipationSnapshot is required.');
    }
    if (snapshot.timestamp > this.clock.now()) {
      throw new DomainError('Snapshot timestamp cannot be in the future.');
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  //  INDIVIDUAL TRAIT CALCULATIONS
  // ──────────────────────────────────────────────────────────────────────────

  /**
   * Hype – fast-moving indicator impacted by live votes, chat spam, social shares.
   * Uses a short half-life to encourage continuous hype-building.
   */
  private calculateHype(
    pass: ShowPass,
    snapshot: ParticipationSnapshot,
  ): number {
    const base = snapshot.metricSum([
      ParticipationType.LiveVoteWeight,
      ParticipationType.ChatActivity,
      ParticipationType.SocialShare,
    ]);

    const decayed = this.applyHalfLife(
      pass.traits.HYPE ?? 0,
      this.cfg.hypeHalfLifeDays,
    );

    const score = clamp(decayed + base, 0, 100);
    return Math.round(score);
  }

  /**
   * Reputation – slower moving, accumulative metric fed by mini-game scores,
   * bug reports, and community mods. Longer half-life than Hype.
   */
  private calculateReputation(
    pass: ShowPass,
    snapshot: ParticipationSnapshot,
  ): number {
    const positive =
      snapshot.get(ParticipationType.MiniGameScore) * 0.4 +
      snapshot.get(ParticipationType.BugReport) * 0.6;

    const decayed = this.applyHalfLife(
      pass.traits.REPUTATION ?? 0,
      this.cfg.repHalfLifeDays,
    );

    const score = clamp(decayed + positive, 0, 1000);
    return Math.round(score);
  }

  /**
   * Loyalty – purely streak-based. Capped by configuration.
   */
  private calculateLoyalty(snapshot: ParticipationSnapshot): number {
    const streak = clamp(
      snapshot.get(ParticipationType.AttendanceStreak),
      0,
      this.cfg.maxAttendanceStreak,
    );

    return streak;
  }

  // ──────────────────────────────────────────────────────────────────────────
  //  HELPERS
  // ──────────────────────────────────────────────────────────────────────────

  /**
   * Applies exponential decay using the half-life formula:
   *
   * remaining = current * 0.5 ^ (elapsedDays / halfLifeDays)
   */
  private applyHalfLife(current: number, halfLifeDays: number): number {
    const now = this.clock.now();
    const daysElapsed =
      (now.getTime() - this.clock.lastTick().getTime()) / 86_400_000; // ms → days
    const decayFactor = Math.pow(0.5, daysElapsed / halfLifeDays);

    return current * decayFactor;
  }
}
```
