```typescript
/****************************************************************************************
 * File: packages/backend/src/application/observers/stage-event.observer.ts
 * Project: StellarStage Carnival ⭑ Interactive NFT Showrunner
 *
 * Description:
 *   Listens to high-level StageDomainEvents fired from the core domain layer and
 *   broadcasts them to external delivery mechanisms (WebSockets, GraphQL
 *   subscriptions, Push notifications, etc.). The observer lives in the
 *   “application” layer (Clean Architecture) and therefore:
 *
 *     • Depends only on abstractions (EventBus, RealtimeGateway, LoggerPort, …)
 *     • Translates domain-centric data into DTOs optimised for front-end clients
 *     • Calls application-level use-cases when cascading workflows are needed
 *
 *   The observer is registered once at application bootstrap.
 ****************************************************************************************/

import { injectable, inject } from 'tsyringe';

import type { DomainEvent } from '../../domain/events/domain-event.interface';
import { ActStartedEvent } from '../../domain/events/act-started.event';
import { ActEndedEvent } from '../../domain/events/act-ended.event';
import { VoteCastEvent } from '../../domain/events/vote-cast.event';
import { LootDistributedEvent } from '../../domain/events/loot-distributed.event';
import { PassStakedEvent } from '../../domain/events/pass-staked.event';

import type { EventObserver } from '../ports/event-observer.port';
import type { EventBus } from '../ports/event-bus.port';
import type { RealtimeGateway } from '../ports/realtime-gateway.port';
import type { LoggerPort } from '../ports/logger.port';
import { MINT_LOOT_ON_ACT_END } from '../config/constants';

@injectable()
export class StageEventObserver implements EventObserver {
  constructor(
    @inject('EventBus') private readonly eventBus: EventBus,
    @inject('RealtimeGateway') private readonly realtime: RealtimeGateway,
    @inject('Logger') private readonly logger: LoggerPort
  ) {
    this.register();
  }

  /*****************************************************************************
   * Public API
   ****************************************************************************/

  /**
   * on
   * ----
   * The single entry-point required by the EventObserver interface.
   */
  async on(event: DomainEvent): Promise<void> {
    // Every handler runs in its own try/catch block
    // so one failure does not break other observers.
    try {
      switch (event.constructor) {
        case ActStartedEvent:
          await this.handleActStarted(event as ActStartedEvent);
          break;

        case ActEndedEvent:
          await this.handleActEnded(event as ActEndedEvent);
          break;

        case VoteCastEvent:
          await this.handleVoteCast(event as VoteCastEvent);
          break;

        case LootDistributedEvent:
          await this.handleLootDistributed(event as LootDistributedEvent);
          break;

        case PassStakedEvent:
          await this.handlePassStaked(event as PassStakedEvent);
          break;

        default:
          // Unknown or unhandled event – just ignore for now.
          this.logger.debug(
            `[StageEventObserver] Ignored event "${event.name}" (${event.id})`
          );
      }
    } catch (err) {
      this.logger.error(
        `[StageEventObserver] Failed while processing ${event.name}: ${err}`,
        err as Error
      );
    }
  }

  /*****************************************************************************
   * Private helpers
   ****************************************************************************/

  private register(): void {
    this.eventBus.subscribe(this);
    this.logger.info('[StageEventObserver] Registered with EventBus');
  }

  /**
   * handleActStarted
   * ----------------
   * Broadcasts “actStarted” payloads to every connected stage channel.
   */
  private async handleActStarted(event: ActStartedEvent): Promise<void> {
    const payload = {
      actId: event.actId.value,
      showId: event.showId.value,
      startsAt: event.startedAt.toISOString(),
      metadata: event.metadata
    };

    await this.realtime.broadcast({
      channel: `show:${payload.showId}`,
      event: 'actStarted',
      payload
    });

    this.logger.info(
      `[StageEventObserver] Act "${payload.actId}" started – broadcasted`
    );
  }

  /**
   * handleActEnded
   * --------------
   * When an act ends we optionally trigger on-chain loot minting in
   * addition to pushing the event downstream.
   */
  private async handleActEnded(event: ActEndedEvent): Promise<void> {
    const payload = {
      actId: event.actId.value,
      showId: event.showId.value,
      endedAt: event.endedAt.toISOString()
    };

    await this.realtime.broadcast({
      channel: `show:${payload.showId}`,
      event: 'actEnded',
      payload
    });

    this.logger.info(
      `[StageEventObserver] Act "${payload.actId}" ended – broadcasted`
    );

    if (MINT_LOOT_ON_ACT_END) {
      await this.eventBus.publish(
        new LootDistributedEvent(
          event.showId,
          event.actId,
          /* synthetic loot-drop id */ undefined
        )
      );
      this.logger.debug(
        `[StageEventObserver] Triggered LootDistributedEvent for act ${payload.actId}`
      );
    }
  }

  /**
   * handleVoteCast
   * --------------
   * Pushes real-time vote tallies so the front-end can display live results.
   */
  private async handleVoteCast(event: VoteCastEvent): Promise<void> {
    const payload = {
      voter: event.walletAddress.toChecksumAddress(),
      proposalId: event.proposalId.value,
      choice: event.choice,
      weight: event.weight.toString()
    };

    await this.realtime.broadcast({
      channel: `proposal:${payload.proposalId}`,
      event: 'voteCast',
      payload
    });

    this.logger.debug(
      `[StageEventObserver] Vote received for proposal "${payload.proposalId}"`
    );
  }

  /**
   * handleLootDistributed
   * ---------------------
   * After loot drops we update audiences so their wallets refresh metadata.
   */
  private async handleLootDistributed(
    event: LootDistributedEvent
  ): Promise<void> {
    const payload = {
      dropId: event.dropId.value,
      showId: event.showId.value,
      actId: event.actId?.value,
      totalItems: event.totalItems
    };

    await this.realtime.broadcast({
      channel: `show:${payload.showId}`,
      event: 'lootDistributed',
      payload
    });

    this.logger.info(
      `[StageEventObserver] Loot drop "${payload.dropId}" sent to show ${payload.showId}`
    );
  }

  /**
   * handlePassStaked
   * ----------------
   * Notifies governance dashboards of stake changes.
   */
  private async handlePassStaked(event: PassStakedEvent): Promise<void> {
    const payload = {
      passTokenId: event.passTokenId.value,
      wallet: event.staker.toChecksumAddress(),
      stakedAt: event.stakedAt.toISOString()
    };

    await this.realtime.broadcast({
      channel: `wallet:${payload.wallet}`,
      event: 'passStaked',
      payload
    });

    this.logger.debug(
      `[StageEventObserver] Pass ${payload.passTokenId} staked by ${payload.wallet}`
    );
  }
}

/****************************************************************************************
 * Bootstrap helper
 * ----------------
 * Called from the application’s IoC root.  Keeps wiring separate from the class
 * definition, allowing the observer to be tree-shaken when unused (e.g. tests).
 ****************************************************************************************/

/**
 * registerStageEventObserver
 * --------------------------
 * Attaches the observer to the EventBus through the dependency container.
 */
export const registerStageEventObserver = (): void => {
  // The container will resolve dependencies declared in the constructor.
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { container } = require('tsyringe');
  container.resolve(StageEventObserver);
};
```