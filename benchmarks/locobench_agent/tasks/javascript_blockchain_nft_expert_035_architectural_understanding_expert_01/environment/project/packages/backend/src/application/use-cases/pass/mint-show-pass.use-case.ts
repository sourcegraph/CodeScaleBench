```typescript
/****************************************************************************************
 * File: mint-show-pass.use-case.ts
 * Project: StellarStage Carnival – Interactive NFT Showrunner
 * Layer: Application ‑ Use-Cases
 *
 * Description:
 *   Executes the business flow required to mint a new Show-Pass NFT for a given show.
 *   The use-case coordinates the domain factory, repositories, external ports (EVM,
 *   IPFS, Event-Bus) and returns the newly minted Pass aggregate root.
 *
 *   Clean Architecture rules:
 *     • Knows nothing about HTTP, CLI, GraphQL, etc.
 *     • Orchestrates domain & infrastructure by calling abstractions (ports).
 *     • Produces domain errors instead of infrastructure-specific ones.
 *
 * Author: StellarStage Carnival Core Team
 ****************************************************************************************/

import { v4 as uuid } from 'uuid';
import { Pass } from '../../../domain/entities/pass.entity';
import { Show } from '../../../domain/entities/show.entity';
import { PassTier } from '../../../domain/value-objects/pass-tier.vo';
import { PassFactory } from '../../../domain/factories/pass.factory';
import { IPassRepository } from '../../../domain/ports/repositories/pass.repository.port';
import { IShowRepository } from '../../../domain/ports/repositories/show.repository.port';
import { IBlockchainPort } from '../../../domain/ports/blockchain.port';
import { IStoragePort } from '../../../domain/ports/storage.port';
import { IEventBusPort } from '../../../domain/ports/event-bus.port';
import { DomainError } from '../../../shared/errors/domain.error';
import { Either, left, right } from '../../../shared/utils/either';

/* -------------------------------------------------------------------------- */
/*                              Command / DTOs                                */
/* -------------------------------------------------------------------------- */

export interface MintShowPassCommand {
  showId: string;
  ownerWallet: string;
  tier: PassTier;
  metadataOverrides?: Record<string, unknown>;
  txOptions?: Record<string, unknown>;
}

/* -------------------------------------------------------------------------- */
/*                               Use-Case Class                               */
/* -------------------------------------------------------------------------- */

export class MintShowPassUseCase {
  constructor(
    private readonly showRepo: IShowRepository,
    private readonly passRepo: IPassRepository,
    private readonly blockchain: IBlockchainPort,
    private readonly storage: IStoragePort,
    private readonly eventBus: IEventBusPort
  ) {}

  /**
   * Main entry – orchestrates the entire mint workflow.
   */
  public async execute(
    command: MintShowPassCommand
  ): Promise<Either<DomainError, Pass>> {
    /* ------------------------------- Validation -------------------------- */
    const validationError = this.validateCommand(command);
    if (validationError) return left(validationError);

    /* ----------------------------- Load Show ----------------------------- */
    const show: Show | undefined = await this.showRepo.findById(command.showId);
    if (!show)
      return left(
        new DomainError(
          'SHOW_NOT_FOUND',
          `Show with id "${command.showId}" does not exist`
        )
      );

    /* --------------------------- Factory Create -------------------------- */
    let pass: Pass;
    try {
      pass = PassFactory.create({
        id: uuid(),
        showId: show.id,
        ownerWallet: command.ownerWallet,
        tier: command.tier,
        metadataOverrides: command.metadataOverrides
      });
    } catch (err) {
      return left(
        new DomainError('PASS_CREATION_FAILED', (err as Error).message)
      );
    }

    /* -------------------------- Persist to DB --------------------------- */
    try {
      await this.passRepo.save(pass);
    } catch (err) {
      return left(
        new DomainError('PERSISTENCE_ERROR', 'Could not persist new pass')
      );
    }

    /* ----------------------- Pin metadata to IPFS ------------------------ */
    try {
      const ipfsHash = await this.storage.pinJSON(pass.toMetadataJSON());
      pass.setTokenURI(`ipfs://${ipfsHash}`);
      await this.passRepo.update(pass);
    } catch (err) {
      return left(
        new DomainError(
          'STORAGE_ERROR',
          'IPFS pinning failed: ' + (err as Error).message
        )
      );
    }

    /* ------------------ Smart-Contract / Blockchain ---------------------- */
    try {
      const txHash = await this.blockchain.mintNFT({
        to: pass.ownerWallet,
        tokenURI: pass.tokenURI,
        tier: pass.tier,
        txOptions: command.txOptions
      });

      pass.setMintTxHash(txHash);
      await this.passRepo.update(pass);
    } catch (err) {
      // Rollback DB on chain failure
      await this.passRepo.delete(pass.id).catch(() => void 0);
      return left(
        new DomainError(
          'BLOCKCHAIN_ERROR',
          'Mint transaction failed: ' + (err as Error).message
        )
      );
    }

    /* -------------------------- Domain Events --------------------------- */
    await this.eventBus.publish('pass.minted', {
      passId: pass.id,
      showId: pass.showId,
      owner: pass.ownerWallet,
      tier: pass.tier
    });

    return right(pass);
  }

  /* ---------------------------------------------------------------------- */
  /*                               Utilities                                */
  /* ---------------------------------------------------------------------- */

  private validateCommand(command: MintShowPassCommand): DomainError | null {
    if (!command.showId) {
      return new DomainError('VALIDATION_ERROR', 'showId is required');
    }
    if (!command.ownerWallet) {
      return new DomainError('VALIDATION_ERROR', 'ownerWallet is required');
    }
    if (!PassTier.isValid(command.tier)) {
      return new DomainError(
        'VALIDATION_ERROR',
        `tier "${command.tier}" is invalid`
      );
    }
    return null;
  }
}
```
