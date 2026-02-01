```typescript
/****************************************************************************************
 * File: packages/backend/src/application/use-cases/governance/stake-pass.use-case.ts
 * Project: StellarStage Carnival – Interactive NFT Showrunner
 *
 * Description:
 *  Orchestrates the business flow for staking a Show-Pass NFT into the on–chain
 *  Governance Staking contract. This grants the pass-holder voting power over
 *  future line-ups while accruing protocol rewards.  Adheres to Clean Architecture:
 *   – Pure business logic, no framework / transport details
 *   – Depends only on domain models & ports (repositories, gateways, event bus)
 *
 *  High-level steps:
 *   1. Fetch pass, validate caller ownership & eligibility
 *   2. Ensure the pass is not already staked
 *   3. Delegate to blockchain gateway to execute the staking tx
 *   4. Persist staking aggregate & update pass state inside a single transaction
 *   5. Publish PassStaked domain event
 *
 * Author:  <your-team>
 ****************************************************************************************/

import { v4 as uuid } from 'uuid';

import { Pass } from '../../../domain/entities/pass.entity';
import { Stake } from '../../../domain/entities/stake.entity';
import { GovernancePower } from '../../../domain/value-objects/governance-power.vo';

import { IPassRepository } from '../../../domain/ports/repositories/pass.repository';
import { IStakeRepository } from '../../../domain/ports/repositories/stake.repository';
import { IStakingContractGateway } from '../../../domain/ports/gateways/staking-contract.gateway';
import { IEventBus } from '../../../domain/ports/event-bus/event-bus.port';
import { IUnitOfWork } from '../../../domain/ports/uow/unit-of-work.port';

import {
  PassAlreadyStakedError,
  PassNotFoundError,
  UnauthorizedPassOwnerError,
  BlockchainTransactionError
} from '../../../domain/errors';

import { PassStakedEvent } from '../../../domain/events/pass-staked.event';

/**
 * Request-payload for StakePassUseCase
 */
export interface StakePassCommand {
  readonly callerAddress: string;     // EOA performing the stake
  readonly passTokenId: string;       // ERC-721 tokenId (on-chain)
  readonly lockDurationDays?: number; // Optional – fixed lock increases power
}

/**
 * Result returned by StakePassUseCase
 */
export interface StakePassResult {
  readonly stakeId: string;
  readonly txHash: string;
  readonly governancePower: GovernancePower;
  readonly stakedAt: Date;
  readonly unlocksAt: Date;
}

/**
 * StakePassUseCase
 *
 * Pure application service orchestrating the staking flow.
 */
export class StakePassUseCase {
  constructor(
    private readonly passRepo: IPassRepository,
    private readonly stakeRepo: IStakeRepository,
    private readonly stakingGateway: IStakingContractGateway,
    private readonly eventBus: IEventBus,
    private readonly uow: IUnitOfWork
  ) {}

  /**
   * Executes the use-case
   */
  public async execute(cmd: StakePassCommand): Promise<StakePassResult> {
    // Step 1 ──────────────────────────────────────────────────────────────
    const pass = await this.passRepo.findByTokenId(cmd.passTokenId);
    if (!pass) {
      throw new PassNotFoundError(cmd.passTokenId);
    }

    if (!pass.isOwnedBy(cmd.callerAddress)) {
      throw new UnauthorizedPassOwnerError(cmd.callerAddress, cmd.passTokenId);
    }

    // Step 2 ──────────────────────────────────────────────────────────────
    const existingStake = await this.stakeRepo.findActiveByPassId(pass.id);
    if (existingStake) {
      throw new PassAlreadyStakedError(pass.id);
    }

    // Derive governance power (domain logic lives inside the VO)
    const lockDays = cmd.lockDurationDays ?? Stake.DEFAULT_LOCK_DAYS;
    const governancePower = GovernancePower.forLockDuration(lockDays);

    // Step 3 ──────────────────────────────────────────────────────────────
    let txHash: string;
    try {
      txHash = await this.stakingGateway.stakePass({
        owner: cmd.callerAddress,
        tokenId: cmd.passTokenId,
        lockDurationDays: lockDays,
        power: governancePower.amount
      });
    } catch (err) {
      throw new BlockchainTransactionError('Staking transaction failed', err);
    }

    // Step 4 ──────────────────────────────────────────────────────────────
    const stakeAggregate = Stake.create({
      id: uuid(),
      passId: pass.id,
      ownerAddress: cmd.callerAddress,
      governancePower,
      txHash,
      lockDurationDays: lockDays
    });

    // Persist atomically
    await this.uow.transaction(async (trx) => {
      await this.stakeRepo.save(stakeAggregate, trx);
      await this.passRepo.markAsStaked(pass.id, stakeAggregate.id, trx);
    });

    // Step 5 ──────────────────────────────────────────────────────────────
    await this.eventBus.publish(
      new PassStakedEvent({
        stakeId: stakeAggregate.id,
        passId: pass.id,
        owner: cmd.callerAddress,
        governancePower,
        txHash,
        stakedAt: stakeAggregate.stakedAt,
        unlocksAt: stakeAggregate.unlocksAt
      })
    );

    // ─────────────────────────────────────────────────────────────────────
    return {
      stakeId: stakeAggregate.id,
      txHash,
      governancePower,
      stakedAt: stakeAggregate.stakedAt,
      unlocksAt: stakeAggregate.unlocksAt
    };
  }
}
```