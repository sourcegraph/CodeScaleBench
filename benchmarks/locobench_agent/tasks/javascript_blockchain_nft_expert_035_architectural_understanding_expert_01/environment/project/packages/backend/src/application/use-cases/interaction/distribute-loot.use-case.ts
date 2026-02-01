```typescript
/**************************************************************************************************
 *  Project:  StellarStage Carnival
 *  File:     packages/backend/src/application/use-cases/interaction/distribute-loot.use-case.ts
 *
 *  Description:
 *  ------------
 *  “DistributeLootUseCase” orchestrates the post-performance airdrop that sends freshly-minted
 *  on-chain Loot to every eligible Show Pass holder.  The flow is:
 *
 *     1.  Validate that the Show (and optional Act) exists and is in a distributable state.
 *     2.  Acquire an idempotency lock so multiple nodes can’t double-airdrop the same loot.
 *     3.  Fetch all eligible Passes and determine their individual loot share via the
 *         IDistributionStrategy plugged in for the Show.
 *     4.  Ask the IBlockchainGateway to batch-mint ERC-1155 (or similar) loot tokens and return
 *         the on-chain transaction hash.
 *     5.  Persist the Loot entity and mark Passes as “rewarded” via their respective repositories.
 *     6.  Publish a LootDistributedDomainEvent on the global event bus for projections, websocket
 *         relays, and analytics.
 *
 *  Clean-architecture wise, this file lives in the “application” layer and depends only on ports/
 *  interfaces — never on concrete infrastructure.
 **************************************************************************************************/

import { injectable, inject } from 'inversify';
import { v4 as uuid } from 'uuid';

import { TYPES } from '../../../ioc/types'; // central DI token map

/* ───────────────────────────────────────────────────────────────  P O R T S  ────────────────── */

import {
  IShowRepository,
  IShowReadOnlyRepository,
} from '../../../domain/entertainment/ports/show.repository';
import { IPassRepository } from '../../../domain/entertainment/ports/pass.repository';
import { ILootRepository } from '../../../domain/entertainment/ports/loot.repository';
import { IBlockchainGateway } from '../../../domain/blockchain/ports/blockchain.gateway';
import { IEventBus } from '../../../domain/shared/ports/event-bus';
import { IDistributedLock } from '../../../domain/shared/ports/distributed-lock';
import { IClock } from '../../../domain/shared/ports/clock';
import {
  IDistributionStrategy,
  DistributionStrategyFactory,
} from '../../../domain/entertainment/strategy/distribution.strategy';

/* ───────────────────────────────────────────────────────────────  E R R O R S  ──────────────── */

export class ShowNotFoundError extends Error {
  constructor(showId: string) {
    super(`Show with id "${showId}" not found.`);
    this.name = ShowNotFoundError.name;
  }
}

export class LootAlreadyDistributedError extends Error {
  constructor(showId: string, actId?: string) {
    super(
      `Loot has already been distributed for show "${showId}"${
        actId ? ` / act "${actId}"` : ''
      }.`,
    );
    this.name = LootAlreadyDistributedError.name;
  }
}

/* ────────────────────────────────────────────  I/O  D T O  S  ──────────────────────────────── */

export interface DistributeLootInput {
  /** Unique show identifier (ULID/UUID/slug). */
  showId: string;
  /** Optional Act; if undefined, distribute for the whole show. */
  actId?: string;
  /**
   * Wallet address of the performer or backend hot-wallet that will appear as
   * the “from” address on chain.  (Route-level auth should guarantee this). */
  performerWallet: string;
  /** Correlation id for tracing across micro-services. */
  correlationId?: string;
}

export interface DistributeLootOutput {
  lootId: string;
  showId: string;
  actId?: string;
  txHash: string;
  totalRecipients: number;
  timestamp: Date;
}

/* ──────────────────────────────────────────────────────────  U S E   C A S E  ──────────────── */

@injectable()
export class DistributeLootUseCase {
  constructor(
    @inject(TYPES.ShowRepository) private readonly showRepo: IShowRepository & IShowReadOnlyRepository,
    @inject(TYPES.PassRepository) private readonly passRepo: IPassRepository,
    @inject(TYPES.LootRepository) private readonly lootRepo: ILootRepository,
    @inject(TYPES.BlockchainGateway) private readonly chain: IBlockchainGateway,
    @inject(TYPES.EventBus) private readonly eventBus: IEventBus,
    @inject(TYPES.DistributedLock) private readonly lock: IDistributedLock,
    @inject(TYPES.Clock) private readonly clock: IClock,
  ) {}

  /**
   * Entrypoint to distribute loot for a show/act.  Idempotent and safe to retry.
   */
  public async execute(input: DistributeLootInput): Promise<DistributeLootOutput> {
    const { showId, actId } = input;

    /* -------- 0. Concurrency guard – one distribution per show/act ---------- */
    const lockKey = `distribute-loot:${showId}:${actId ?? '*'}`;
    const releaseLock = await this.lock.acquire(lockKey, 10_000); // 10s TTL
    try {
      /* ---------------------- 1. Validation & invariants ------------------- */
      const show = await this.showRepo.findById(showId);
      if (!show) throw new ShowNotFoundError(showId);

      if (await this.lootRepo.existsFor(showId, actId)) {
        throw new LootAlreadyDistributedError(showId, actId);
      }

      /* ---------------------- 2. Retrieve eligible passes ------------------ */
      const eligiblePasses = await this.passRepo.findEligibleForLoot(showId, actId);
      if (!eligiblePasses.length) {
        // Nothing to do – silently skip; still record audit event
        return {
          lootId: '',
          showId,
          actId,
          txHash: '',
          totalRecipients: 0,
          timestamp: this.clock.now(),
        };
      }

      /* ---------------------- 3. Determine distribution -------------------- */
      const strategy: IDistributionStrategy =
        DistributionStrategyFactory.forShow(show.distributionModel);
      const distributionPlan = strategy.buildPlan(eligiblePasses);

      /* ---------------------- 4. Mint & distribute on-chain ---------------- */
      const lootId = uuid();
      const txHash = await this.chain.batchMintLoot({
        lootId,
        recipients: distributionPlan.recipients,
        metadataUri: distributionPlan.metadataUri,
        performerWallet: input.performerWallet,
        correlationId: input.correlationId,
      });

      /* ---------------------- 5. Persist to DB & update passes ------------- */
      await this.lootRepo.create({
        id: lootId,
        showId,
        actId,
        txHash,
        distributionModel: show.distributionModel,
        metadataUri: distributionPlan.metadataUri,
        totalRecipients: distributionPlan.recipients.length,
        createdAt: this.clock.now(),
      });

      await this.passRepo.markRewarded(
        distributionPlan.recipients.map((r) => r.passId),
        lootId,
      );

      /* ---------------------- 6. Publish domain event --------------------- */
      await this.eventBus.publish({
        type: 'loot.distributed',
        payload: {
          lootId,
          showId,
          actId,
          txHash,
          performerWallet: input.performerWallet,
          totalRecipients: distributionPlan.recipients.length,
        },
        occurredAt: this.clock.now(),
        correlationId: input.correlationId,
      });

      /* ---------------------- 7. Return DTO ------------------------------- */
      return {
        lootId,
        showId,
        actId,
        txHash,
        totalRecipients: distributionPlan.recipients.length,
        timestamp: this.clock.now(),
      };
    } finally {
      /* Always release lock even if we throw */
      await releaseLock();
    }
  }
}
```
