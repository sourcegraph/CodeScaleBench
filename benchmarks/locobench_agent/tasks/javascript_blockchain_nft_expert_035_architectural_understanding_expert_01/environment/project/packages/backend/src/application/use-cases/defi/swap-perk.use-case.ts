```typescript
/**
 * StellarStage Carnival
 * ---------------------
 * SwapPerkUseCase
 *
 * Fans barter the perks embedded in their Show-Pass NFTs through an automated
 * market making pool (a thin wrapper around an on-chain liquidity contract).
 *
 * The use-case validates ownership & allowance, inserts an escrow record, fires
 * a swap transaction through the defi adapter and persists the resulting state
 * changes atomically inside a unit-of-work.
 */

import { v4 as uuid } from 'uuid';
import { addMinutes, isBefore } from 'date-fns';

import { PassId, PerkId } from '../../../domain/value-objects';
import { Pass } from '../../../domain/entities/pass.entity';
import { SwapPerkCommand } from '../../dto/defi/swap-perk.command';
import { SwapPerkResponse } from '../../dto/defi/swap-perk.response';

import { IPassRepository } from '../../../domain/ports/repositories/pass.repository';
import { IPerkSwapDefiService } from '../../../domain/ports/services/defi/perk-swap-defi.service';
import { IUnitOfWork } from '../../../domain/ports/persistence/unit-of-work.port';
import { DomainEventBus } from '../../../domain/event-bus/domain-event-bus';
import { PerkSwapped } from '../../../domain/events/perk-swapped.event';

import {
  InvalidSwapError,
  OwnershipError,
  ResourceLockedError,
} from '../../errors';

export class SwapPerkUseCase {
  constructor(
    private readonly passRepo: IPassRepository,
    private readonly defiService: IPerkSwapDefiService,
    private readonly uow: IUnitOfWork,
    private readonly eventBus: DomainEventBus,
  ) {}

  /**
   * Executes the business flow for swapping perks between two Show-Pass NFTs.
   *
   * @throws InvalidSwapError    If anything in the request is malformed
   * @throws OwnershipError      If the caller does not own the offered pass
   * @throws ResourceLockedError If either perk is locked/staked
   */
  async execute(cmd: SwapPerkCommand): Promise<SwapPerkResponse> {
    this.validateCommand(cmd);

    const offeredPass = await this.passRepo.findById(
      PassId.from(cmd.offeredPassId),
    );
    const requestedPass = await this.passRepo.findById(
      PassId.from(cmd.requestedPassId),
    );

    // 1. Ownership & allowance checks
    this.assertOwnership(cmd.requesterAddress, offeredPass);
    this.assertPerkAvailability(offeredPass, cmd.offeredPerkId);
    this.assertPerkAvailability(requestedPass, cmd.requestedPerkId);

    // 2. Persist an escrow lock in a single transaction
    const escrowId = uuid();
    const now = new Date();
    const escrowExpiresAt = addMinutes(now, 10);
    await this.uow.transaction(async (trx) => {
      offeredPass.lockPerk(cmd.offeredPerkId, escrowId, escrowExpiresAt);
      requestedPass.lockPerk(cmd.requestedPerkId, escrowId, escrowExpiresAt);

      await this.passRepo.save(of­feredPass, trx);
      await this.passRepo.save(requestedPass, trx);
    });

    // 3. Call the on-chain swap adapter
    try {
      await this.defiService.swapPerks({
        escrowId,
        offeredPassTokenId: offeredPass.tokenId,
        offeredPerkId: cmd.offeredPerkId,
        requestedPassTokenId: requestedPass.tokenId,
        requestedPerkId: cmd.requestedPerkId,
        initiatorWallet: cmd.requesterAddress,
        signature: cmd.signature,
      });
    } catch (err) {
      // rollback locks if blockchain tx fails
      await this.uow.transaction(async (trx) => {
        offeredPass.unlockPerk(cmd.offeredPerkId, escrowId);
        requestedPass.unlockPerk(cmd.requestedPerkId, escrowId);
        await this.passRepo.save(of­feredPass, trx);
        await this.passRepo.save(requestedPass, trx);
      });
      throw err;
    }

    // 4. Finalise swap atomically
    await this.uow.transaction(async (trx) => {
      offeredPass.removePerk(cmd.offeredPerkId);
      requestedPass.removePerk(cmd.requestedPerkId);

      offeredPass.addPerk(cmd.requestedPerkId);
      requestedPass.addPerk(cmd.offeredPerkId);

      offeredPass.unlockPerk(cmd.requestedPerkId, escrowId);
      requestedPass.unlockPerk(cmd.offeredPerkId, escrowId);

      await this.passRepo.save(of­feredPass, trx);
      await this.passRepo.save(requestedPass, trx);
    });

    // 5. Emit domain event
    await this.eventBus.publish(
      new PerkSwapped({
        swapId: escrowId,
        offeredPassId: offeredPass.id.value,
        requestedPassId: requestedPass.id.value,
        offeredPerkId: cmd.offeredPerkId,
        requestedPerkId: cmd.requestedPerkId,
        executedAt: new Date(),
      }),
    );

    return SwapPerkResponse.success({
      swapId: escrowId,
      newPerks: {
        [offeredPass.id.value]: cmd.requestedPerkId,
        [requestedPass.id.value]: cmd.offeredPerkId,
      },
    });
  }

  /*
   * --------- Internal helpers ------------------------------------------------
   */

  private validateCommand(cmd: SwapPerkCommand): void {
    const expiryDate = new Date(cmd.expiryISO);
    if (!cmd.signature || isBefore(expiryDate, new Date())) {
      throw new InvalidSwapError('Swap request signature / expiry invalid.');
    }
  }

  private assertOwnership(address: string, pass: Pass): void {
    if (pass.owner.toLowerCase() !== address.toLowerCase()) {
      throw new OwnershipError(
        `Wallet ${address} does not own pass ${pass.id.value}`,
      );
    }
  }

  private assertPerkAvailability(pass: Pass, perkId: PerkId | string): void {
    const perk = pass.perks.find((p) => p.id.equals(perkId));
    if (!perk) {
      throw new InvalidSwapError(
        `Pass ${pass.id.value} does not contain perk ${perkId}`,
      );
    }
    if (perk.isLockedOrStaked()) {
      throw new ResourceLockedError(
        `Perk ${perkId} is currently locked or staked`,
      );
    }
  }
}
```