```typescript
/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * StellarStage Carnival – WebSocket Event Bus Adapter
 *
 * This adapter exposes a RFC-6455 compliant WebSocket endpoint that pushes
 * serialized DomainEvents to any authorised consumer – e.g. the React-Three
 * front-end, monitoring dashboards or 3rd-party bots.  Consumers can perform
 * fine-grained subscriptions at runtime, selecting by:
 *
 *   • eventType  – “ShowCreated”, “LootDropped”, …
 *   • aggregateId – concrete entity id (“show-0x123”, “pass-0xABC”, …)
 *
 * The adapter follows Clean-Architecture principles and *does not* contain
 * business logic; it merely translates events from the internal EventBusPort
 * into WebSocket frames and vice-versa.
 *
 * Implementation details
 * ──────────────────────
 * • ws                – ultra-light WebSocket server
 * • jsonwebtoken      – HMAC / RSA bearer token validation
 * • zod               – runtime schema validation for inbound frames
 * • winston logger    – structured logging
 */

import { Server as HttpServer } from 'http';
import { EventEmitter } from 'events';
import WebSocket, { WebSocketServer } from 'ws';
import jwt, { JwtPayload } from 'jsonwebtoken';
import { z } from 'zod';
import { v4 as uuid } from 'uuid';
import { logger } from '../../logger';

/* -------------------------------------------------------------------------- */
/*                                Configuration                               */
/* -------------------------------------------------------------------------- */

export interface WebSocketBusOptions {
  /**
   * URL path the WSS server will listen on, e.g. “/events”.
   */
  path?: string;
  /**
   * JWT secret or public key used to verify auth tokens. If omitted, the server
   * will run in *open* mode (❗ not recommended in production).
   */
  jwtSecret?: string | Buffer;
  /**
   * Time in milliseconds between heart-beat “ping” frames.
   * Pass 0 to disable pings.
   */
  heartbeatInterval?: number;
  /**
   * Whether raw errors should be forwarded to the client. Enabled in dev only.
   */
  exposeErrors?: boolean;
}

/* -------------------------------------------------------------------------- */
/*                                 Contracts                                  */
/* -------------------------------------------------------------------------- */

export interface DomainEvent<T = any> {
  id: string; // event id (uuid v4)
  type: string; // domain event name
  payload: T; // arbitrary serialisable payload
  meta: {
    aggregateId?: string;
    occurredAt: string; // ISO-timestamp
  };
}

export interface EventBusPort {
  // Called by hexagonal architecture adapters / use-cases
  publish(event: DomainEvent): void;
  subscribe(eventType: string, listener: (event: DomainEvent) => void): void;
}

/* -------------------------------------------------------------------------- */
/*                             Runtime Validators                             */
/* -------------------------------------------------------------------------- */

const clientRequestSchema = z.discriminatedUnion('action', [
  z.object({
    action: z.literal('SUBSCRIBE'),
    eventTypes: z.array(z.string()).optional(),
    aggregateIds: z.array(z.string()).optional(),
  }),
  z.object({
    action: z.literal('UNSUBSCRIBE'),
    eventTypes: z.array(z.string()).optional(),
    aggregateIds: z.array(z.string()).optional(),
  }),
]);

type ClientRequest = z.infer<typeof clientRequestSchema>;

/* -------------------------------------------------------------------------- */
/*                            WebSocket Bus Class                             */
/* -------------------------------------------------------------------------- */

export class WebSocketBus extends EventEmitter implements EventBusPort {
  private readonly wss: WebSocketServer;
  private readonly jwtSecret?: string | Buffer;
  private readonly clients: Map<
    string,
    {
      socket: WebSocket;
      subscriptions: {
        eventTypes: Set<string>;
        aggregateIds: Set<string>;
      };
    }
  > = new Map();

  private heartbeatIntervalId: NodeJS.Timer | null = null;
  private readonly opts: Required<WebSocketBusOptions>;

  constructor(server: HttpServer, opts: WebSocketBusOptions = {}) {
    super();
    this.opts = {
      path: '/events',
      jwtSecret: opts.jwtSecret,
      heartbeatInterval: 30_000,
      exposeErrors: false,
      ...opts,
    };
    this.jwtSecret = this.opts.jwtSecret;

    this.wss = new WebSocketServer({
      noServer: true,
      path: this.opts.path,
    });

    // Bind upgrader
    server.on('upgrade', (req, socket, head) => {
      if (req.url?.startsWith(this.opts.path)) {
        this.wss.handleUpgrade(req, socket, head, (ws) => {
          this.wss.emit('connection', ws, req);
        });
      } else {
        socket.destroy();
      }
    });

    this.wss.on('connection', (socket, req) =>
      this.handleConnection(socket, req)
    );

    if (this.opts.heartbeatInterval > 0) {
      this.heartbeatIntervalId = setInterval(
        () => this.pingAll(),
        this.opts.heartbeatInterval
      );
      this.heartbeatIntervalId.unref();
    }

    logger.info(
      `📡 WebSocketBus listening on path '${this.opts.path}', heartbeat ${
        this.opts.heartbeatInterval > 0
          ? `${this.opts.heartbeatInterval}ms`
          : 'disabled'
      }`
    );
  }

  /* -------------------------------------------------------------------------- */
  /*                         EventBusPort – publish()                           */
  /* -------------------------------------------------------------------------- */

  /**
   * Broadcasts a DomainEvent to all connected clients that expressed interest
   * in either its type or aggregateId (intersection is union-based).
   */
  publish(event: DomainEvent): void {
    if (!event?.type) return;

    const frame = JSON.stringify(event);

    for (const [, client] of this.clients) {
      const {
        socket,
        subscriptions: { eventTypes, aggregateIds },
      } = client;

      if (
        (eventTypes.size === 0 || eventTypes.has(event.type)) &&
        (aggregateIds.size === 0 ||
          (event.meta.aggregateId &&
            aggregateIds.has(event.meta.aggregateId)))
      ) {
        socket.send(frame);
      }
    }

    // Internal subscribers (i.e. other back-end components) may listen via
    // EventEmitter API.
    this.emit(event.type, event);
  }

  subscribe(eventType: string, listener: (event: DomainEvent) => void): void {
    this.on(eventType, listener);
  }

  /* -------------------------------------------------------------------------- */
  /*                             Connection Life-Cycle                          */
  /* -------------------------------------------------------------------------- */

  private handleConnection(socket: WebSocket, req: any): void {
    // Auth
    try {
      this.authenticate(socket, req);
    } catch (err) {
      logger.warn(`❌ WebSocket auth failed: ${(err as Error).message}`);
      socket.close(4001, 'unauthorised');
      return;
    }

    const clientId = uuid();
    this.clients.set(clientId, {
      socket,
      subscriptions: { eventTypes: new Set(), aggregateIds: new Set() },
    });
    logger.debug(`➕ Client connected (${clientId}), total ${this.clients.size}`);

    socket.on('message', (raw) => this.handleMessage(clientId, raw.toString()));
    socket.on('close', () => this.cleanupClient(clientId));
    socket.on('pong', () => {
      // Mark socket as alive (ws internal ping/pong)
      (socket as any).isAlive = true;
    });

    // Mark alive initially
    (socket as any).isAlive = true;
    // Inform client of successful connection
    socket.send(
      JSON.stringify({
        action: 'WELCOME',
        clientId,
      })
    );
  }

  private authenticate(socket: WebSocket, req: any): void {
    if (!this.jwtSecret) return; // open mode

    const authHeader =
      req.headers['sec-websocket-protocol'] ||
      req.headers['authorization'] ||
      '';

    const token = Array.isArray(authHeader)
      ? authHeader[0]
      : authHeader.replace(/^Bearer\s+/i, '');

    if (!token) throw new Error('missing auth token');

    let decoded: JwtPayload;
    try {
      decoded = jwt.verify(token, this.jwtSecret) as JwtPayload;
    } catch (err) {
      throw new Error('invalid token');
    }

    // Attach to socket for later usage if needed
    (socket as any).user = decoded.sub;
  }

  /* -------------------------------------------------------------------------- */
  /*                           Client Message Handling                          */
  /* -------------------------------------------------------------------------- */

  private handleMessage(clientId: string, raw: string): void {
    let msg: ClientRequest;
    try {
      msg = clientRequestSchema.parse(JSON.parse(raw));
    } catch (err) {
      logger.warn(
        `⚠️ invalid frame from client ${clientId}: ${(err as Error).message}`
      );
      if (this.opts.exposeErrors)
        this.clients.get(clientId)?.socket.send(
          JSON.stringify({
            action: 'ERROR',
            reason: 'invalid_payload',
            details: (err as Error).message,
          })
        );
      return;
    }

    const client = this.clients.get(clientId);
    if (!client) return; // ignore stale message

    switch (msg.action) {
      case 'SUBSCRIBE':
        this.updateSubscriptions(client, msg.eventTypes, msg.aggregateIds, true);
        break;
      case 'UNSUBSCRIBE':
        this.updateSubscriptions(
          client,
          msg.eventTypes,
          msg.aggregateIds,
          false
        );
        break;
      default:
        // Should be impossible thanks to Zod discrim union
        break;
    }
  }

  private updateSubscriptions(
    client: {
      socket: WebSocket;
      subscriptions: {
        eventTypes: Set<string>;
        aggregateIds: Set<string>;
      };
    },
    eventTypes: string[] | undefined,
    aggregateIds: string[] | undefined,
    add: boolean
  ): void {
    if (eventTypes) {
      eventTypes.forEach((et) =>
        add ? client.subscriptions.eventTypes.add(et) : client.subscriptions.eventTypes.delete(et)
      );
    }
    if (aggregateIds) {
      aggregateIds.forEach((id) =>
        add ? client.subscriptions.aggregateIds.add(id) : client.subscriptions.aggregateIds.delete(id)
      );
    }

    client.socket.send(
      JSON.stringify({
        action: 'ACK',
        eventTypes: Array.from(client.subscriptions.eventTypes),
        aggregateIds: Array.from(client.subscriptions.aggregateIds),
      })
    );
  }

  private cleanupClient(clientId: string): void {
    this.clients.delete(clientId);
    logger.debug(`➖ Client disconnected (${clientId}), total ${this.clients.size}`);
  }

  /* -------------------------------------------------------------------------- */
  /*                                Heart-Beats                                */
  /* -------------------------------------------------------------------------- */

  private pingAll(): void {
    for (const [, { socket }] of this.clients) {
      if ((socket as any).isAlive === false) {
        socket.terminate();
        continue;
      }

      (socket as any).isAlive = false;
      socket.ping();
    }
  }

  /* -------------------------------------------------------------------------- */
  /*                               Graceful Stop                               */
  /* -------------------------------------------------------------------------- */

  async shutdown(): Promise<void> {
    this.heartbeatIntervalId && clearInterval(this.heartbeatIntervalId);
    await new Promise<void>((resolve) => {
      this.wss.close(() => resolve());
    });
    logger.info('🛑 WebSocketBus shutdown complete');
  }
}

/* -------------------------------------------------------------------------- */
/*                                   Factory                                  */
/* -------------------------------------------------------------------------- */

/**
 * Helper factory that instantiates a WebSocketBus and wires it into an existing
 * Node.js HTTP/S server.
 */
export function createWebSocketBus(
  server: HttpServer,
  opts: WebSocketBusOptions = {}
): WebSocketBus {
  return new WebSocketBus(server, opts);
}
```