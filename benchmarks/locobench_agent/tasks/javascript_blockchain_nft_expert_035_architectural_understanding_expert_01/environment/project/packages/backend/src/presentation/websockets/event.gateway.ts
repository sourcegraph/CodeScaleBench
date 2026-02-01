```typescript
/**************************************************************************************************
 *  File:        packages/backend/src/presentation/websockets/event.gateway.ts
 *  Project:     StellarStage Carnival – Interactive NFT Showrunner
 *  Author:      (c) 2024 StellarStage Labs – All Rights Reserved
 *
 *  Description:
 *  ------------
 *  The WebSocket‐Gateway is the single, bidirectional transport channel between the
 *  real-time event-driven backend and the 3-D front-end / wallet clients. It converts
 *  high-level domain events published on the internal EventBus into consumable socket.io
 *  events while routing user intents (votes, stakes, etc.) back into the application layer
 *  through the CommandBus.
 *
 *  Architectural notes:
 *  *   Follows Clean Architecture – this file lives in the “presentation” layer.
 *  *   Observer Pattern: subscribes to the global EventEmitter2 bus.
 *  *   Strategy Pattern: dynamic event-to-socket mapping via a configurable registry.
 **************************************************************************************************/

import {
  WebSocketGateway,
  WebSocketServer,
  SubscribeMessage,
  ConnectedSocket,
  MessageBody,
  OnGatewayConnection,
  OnGatewayDisconnect,
} from '@nestjs/websockets';
import { Inject, Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Server, Socket } from 'socket.io';
import { EventEmitter2, OnEvent } from '@nestjs/event-emitter';
import { CommandBus } from '@nestjs/cqrs';

import { CastLiveVoteCommand } from '../../application/commands/cast-live-vote.command';
import { StakePassCommand } from '../../application/commands/stake-pass.command';
import { DOMAIN_EVENT_TOKEN } from '../../domain/events/_tokens';
import { DomainEvent } from '../../domain/events/domain-event.interface';
import { JsonWebTokenService } from '../auth/jwt.service';

interface ClientAuthPayload {
  wallet: string;
  jwt: string;
}

/**
 * WebSocketGateway configuration:
 *  – namespace:   /events
 *  – transports:  websocket / polling fallback
 *  – cors:        allow all origins (should be restricted in prod behind API-Gateway)
 */
@WebSocketGateway({
  namespace: '/events',
  transports: ['websocket', 'polling'],
  cors: { origin: '*' },
})
@Injectable()
export class EventGateway implements OnGatewayConnection, OnGatewayDisconnect {
  @WebSocketServer()
  private readonly server!: Server;

  private readonly logger = new Logger(EventGateway.name);

  /**
   * Registry that maps internal domain-event classes to outward-facing socket event names.
   * This lets the front-end subscribe to semantically meaningful messages without leaking
   * private backend implementation details.
   */
  private readonly outboundEventMap: Map<string, string> = new Map([
    ['ShowStarted', 'show.started'],
    ['ShowEnded', 'show.ended'],
    ['ActChanged', 'act.changed'],
    ['LootDropped', 'loot.dropped'],
    ['VoteTallied', 'vote.tallied'],
    // add new events here as the domain grows
  ]);

  constructor(
    private readonly eventBus: EventEmitter2,
    private readonly commandBus: CommandBus,
    private readonly jwt: JsonWebTokenService,
    @Inject(DOMAIN_EVENT_TOKEN) private readonly domainEvents: DomainEvent[],
  ) {
    this.logger.log('EventGateway initialized');
  }

  /******************************** Lifecycle hooks ********************************/

  async handleConnection(client: Socket): Promise<void> {
    try {
      this.logger.log(`Incoming socket connection: ${client.id}`);

      // Optional lightweight authentication – expects {wallet, jwt} in the handshake
      const auth: ClientAuthPayload | undefined = client.handshake.query?.auth
        ? JSON.parse(client.handshake.query.auth as string)
        : undefined;

      if (!auth || !(await this.jwt.verify(auth.jwt, auth.wallet))) {
        this.logger.warn(`Unauthenticated socket connection: ${client.id}`);
        client.emit('error', { message: 'UNAUTHORIZED' });
        client.disconnect();
        return;
      }

      client.data.wallet = auth.wallet;
      this.logger.debug(`Socket authenticated for wallet: ${auth.wallet}`);
    } catch (error) {
      this.logger.error(`Socket connection error: ${error?.message ?? error}`);
      client.disconnect();
    }
  }

  handleDisconnect(client: Socket): void {
    this.logger.log(`Socket disconnected: ${client.id}`);
  }

  /******************************** Domain → Socket ********************************/

  /**
   * Generic listener for all DomainEvents that should be propagated to the front-end.
   * Uses @OnEvent wildcard subscription to pick up any event that implements DomainEvent.
   */
  @OnEvent('*')
  protected async onDomainEvent(event: DomainEvent): Promise<void> {
    const socketEvent = this.outboundEventMap.get(event.constructor.name);
    if (!socketEvent) return; // Not every domain event is meant for the client.

    try {
      this.logger.debug(`Broadcasting ${socketEvent}: ${JSON.stringify(event)}`);
      this.server.emit(socketEvent, this.sanitize(event));
    } catch (err) {
      this.logger.error(
        `Failed to broadcast event ${socketEvent}: ${err?.message ?? err}`,
      );
    }
  }

  /**
   * Remove non-serializable or sensitive fields before emitting to clients.
   */
  private sanitize(event: DomainEvent): Record<string, unknown> {
    const { metadata, ...payload } = event as Record<string, unknown>;
    return payload;
  }

  /******************************** Socket → CommandBus ********************************/

  /**
   * Client intent: Cast a vote in a live poll.
   * Front-end emits `vote.cast` with payload CastLiveVoteCommand parameters.
   */
  @SubscribeMessage('vote.cast')
  async onVoteCast(
    @MessageBody() body: CastLiveVoteCommand,
    @ConnectedSocket() client: Socket,
  ): Promise<void> {
    await this.guardAuthenticated(client);

    try {
      await this.commandBus.execute(
        new CastLiveVoteCommand({
          ...body,
          voterWallet: client.data.wallet,
        }),
      );
      client.emit('vote.cast.ack', { success: true });
    } catch (e) {
      this.logger.error(`Error casting vote: ${e?.message ?? e}`);
      client.emit('vote.cast.ack', { success: false, error: e?.message ?? e });
    }
  }

  /**
   * Client intent: Stake their show-pass NFT.
   * Front-end emits `pass.stake` with payload StakePassCommand parameters.
   */
  @SubscribeMessage('pass.stake')
  async onPassStake(
    @MessageBody() body: StakePassCommand,
    @ConnectedSocket() client: Socket,
  ): Promise<void> {
    await this.guardAuthenticated(client);

    try {
      await this.commandBus.execute(
        new StakePassCommand({
          ...body,
          stakerWallet: client.data.wallet,
        }),
      );
      client.emit('pass.stake.ack', { success: true });
    } catch (e) {
      this.logger.error(`Error staking pass: ${e?.message ?? e}`);
      client.emit('pass.stake.ack', { success: false, error: e?.message ?? e });
    }
  }

  /******************************** Helpers ********************************/

  /**
   * Ensures a socket is authenticated before processing privileged messages.
   * Throws UnauthorizedException to abort the pipeline.
   */
  private async guardAuthenticated(client: Socket): Promise<void> {
    if (!client?.data?.wallet) {
      client.emit('error', { message: 'UNAUTHORIZED' });
      throw new UnauthorizedException('Socket not authenticated');
    }
  }
}
```