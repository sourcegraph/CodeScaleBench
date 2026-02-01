```typescript
/* File: packages/backend/src/application/use-cases/pass/upgrade-pass-by-event.use-case.ts */

import { PassRepositoryPort } from '../../ports/out/pass-repository.port';
import { ShowEventRepositoryPort } from '../../ports/out/show-event-repository.port';
import { TraitFactoryPort } from '../../ports/in/trait-factory.port';
import { NFTGatewayPort, UpdateTokenMetadataInput } from '../../ports/out/nft-gateway.port';
import { EventBusPort } from '../../ports/out/event-bus.port';
import { Pass } from '../../../domain/entities/pass.entity';
import { ShowEvent } from '../../../domain/entities/show-event.entity';
import { PassUpgradedDomainEvent } from '../../../domain/events/pass-upgraded.event';
import { Logger } from '../../../shared/logger';

/**
 * Encapsulates a domain-specific error that can be mapped to an HTTP status
 * or a user-facing message at the controller layer.
 */
export class DomainError extends Error {
  public readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
    Error.captureStackTrace(this, DomainError);
  }
}

export interface UpgradePassByEventCommand {
  /** Unique identifier of the Pass aggregate (UUID, DB id, etc.) */
  passId: string;

  /** Identifier of the ShowEvent that triggered the potential upgrade. */
  eventId: string;

  /** Performer’s ETH address. Used to validate provenance. */
  performer?: string;
}

export interface UpgradePassByEventResult {
  passId: string;
  newLevel: number;
  /** Transaction hash of the on-chain metadata update. */
  txHash: string;
}

/**
 * Application-layer use-case that upgrades a Pass NFT when an in-show event
 * qualifies for a trait evolution.
 *
 * The class follows the Clean Architecture rule of having no dependencies on
 * framework code and relies solely on ports for I/O.
 */
export class UpgradePassByEventUseCase {
  constructor(
    private readonly passRepository: PassRepositoryPort,
    private readonly eventRepository: ShowEventRepositoryPort,
    private readonly traitFactory: TraitFactoryPort,
    private readonly nftGateway: NFTGatewayPort,
    private readonly eventBus: EventBusPort,
    private readonly logger: Logger
  ) {}

  /**
   * Executes the upgrade business flow.
   */
  public async execute(
    command: UpgradePassByEventCommand
  ): Promise<UpgradePassByEventResult> {
    this.logger.debug(
      `[upgrade-pass] Received command: pass=${command.passId}, event=${command.eventId}`
    );

    /* ---------------------------------------------------------------------- */
    /* 1. Fetch aggregates                                                    */
    /* ---------------------------------------------------------------------- */
    const [pass, event] = await Promise.all([
      this.passRepository.findById(command.passId),
      this.eventRepository.findById(command.eventId)
    ]);

    if (!pass) {
      this.logger.warn(`[upgrade-pass] Pass ${command.passId} not found`);
      throw new DomainError('PASS_NOT_FOUND', 'Pass does not exist');
    }

    if (!event) {
      this.logger.warn(`[upgrade-pass] Event ${command.eventId} not found`);
      throw new DomainError('EVENT_NOT_FOUND', 'Event does not exist');
    }

    /* ---------------------------------------------------------------------- */
    /* 2. Domain validation                                                   */
    /* ---------------------------------------------------------------------- */
    if (!event.qualifiesForUpgrade()) {
      throw new DomainError(
        'EVENT_NOT_ELIGIBLE',
        `Event ${event.id} does not qualify for upgrades`
      );
    }

    if (pass.isOnCooldown()) {
      throw new DomainError(
        'PASS_ON_COOLDOWN',
        `Pass is on cooldown until ${pass.cooldownEndsAt?.toISOString()}`
      );
    }

    if (command.performer && command.performer !== event.performerAddress) {
      throw new DomainError(
        'PERFORMER_MISMATCH',
        'Provided performer address does not match event details'
      );
    }

    /* ---------------------------------------------------------------------- */
    /* 3. Trait generation                                                    */
    /* ---------------------------------------------------------------------- */
    const traitComputation = await this.traitFactory.buildTraitsFromEvent({
      pass,
      event
    });

    if (!traitComputation.updated) {
      // Nothing to upgrade; return early.
      this.logger.info(`[upgrade-pass] No new traits for pass ${pass.id}`);
      return {
        passId: pass.id,
        newLevel: pass.level,
        txHash: ''
      };
    }

    /* ---------------------------------------------------------------------- */
    /* 4. Mutate aggregate & persist                                          */
    /* ---------------------------------------------------------------------- */
    pass.applyTraitUpdate(traitComputation);
    pass.bumpLevel();
    pass.markCooldown();

    await this.passRepository.save(pass);

    /* ---------------------------------------------------------------------- */
    /* 5. Push metadata on-chain                                              */
    /* ---------------------------------------------------------------------- */
    let txHash = '';
    try {
      const input: UpdateTokenMetadataInput = {
        tokenId: pass.tokenId,
        metadata: pass.toMetadata()
      };

      txHash = await this.nftGateway.updateTokenMetadata(input);
    } catch (error) {
      this.logger.error(
        `[upgrade-pass] Blockchain update failed for pass ${pass.id}. Rolling back.`,
        error as Error
      );
      await this.passRepository.rollback(pass.id);
      throw new DomainError(
        'BLOCKCHAIN_TX_FAILED',
        'Unable to broadcast metadata update to blockchain'
      );
    }

    /* ---------------------------------------------------------------------- */
    /* 6. Publish domain event                                                */
    /* ---------------------------------------------------------------------- */
    const domainEvent = new PassUpgradedDomainEvent({
      passId: pass.id,
      eventId: event.id,
      newLevel: pass.level,
      traits: pass.traits,
      txHash
    });

    await this.eventBus.publish(domainEvent);

    this.logger.info(
      `[upgrade-pass] Pass ${pass.id} upgraded to level ${pass.level}. Tx=${txHash}`
    );

    return {
      passId: pass.id,
      newLevel: pass.level,
      txHash
    };
  }
}
```