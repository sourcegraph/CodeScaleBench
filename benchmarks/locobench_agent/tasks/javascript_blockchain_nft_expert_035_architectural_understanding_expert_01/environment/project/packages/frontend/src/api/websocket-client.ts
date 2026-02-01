```typescript
/**
 * StellarStage Carnival – WebSocket Client
 *
 * A resilient, browser-friendly WebSocket wrapper that handles:
 *  • Automatic (exponential) reconnects
 *  • Auth token injection (e.g. wallet-signature/JWT)
 *  • Message queueing while offline
 *  • Typed publish/subscribe helpers
 *  • Heart-beat keep-alive
 *
 * The implementation purposefully keeps protocol-level concerns (serialization,
 * heart-beats, auth header) inside this adapter so that presentation layers
 * (React-Three front-end) only deal with domain events.
 */

import { EventEmitter } from 'events';

/* -------------------------------------------------------------------------- */
/*                                  Typings                                   */
/* -------------------------------------------------------------------------- */

export interface Logger {
  debug: (...args: unknown[]) => void;
  info: (...args: unknown[]) => void;
  warn: (...args: unknown[]) => void;
  error: (...args: unknown[]) => void;
}

export interface WebSocketClientOptions {
  /**
   * The WebSocket endpoint, **without** any auth / query params attached.
   */
  endpoint: string;

  /**
   * Async lazy getter for an auth token.
   * E.g. a JWT fetched from the API or a wallet-signature challenge.
   */
  getAuthToken?: () => Promise<string | undefined>;

  /**
   * Attempt to reconnect automatically when the connection drops.
   * @default true
   */
  reconnect?: boolean;

  /**
   * Maximum number of reconnect attempts.
   * `Infinity` = unlimited.
   * @default Infinity
   */
  maxRetries?: number;

  /**
   * Initial reconnect interval in milliseconds.
   * @default 1_000 (1s)
   */
  reconnectIntervalMs?: number;

  /**
   * Upper cap for exponential backoff.
   * @default 30_000 (30s)
   */
  maxReconnectIntervalMs?: number;

  /**
   * Exponential backoff multiplier.
   * @default 1.5
   */
  backoffMultiplier?: number;

  /**
   * If provided, internal logs are routed here instead of console.*.
   */
  logger?: Logger;

  /**
   * Custom WebSocket factory (useful for testing / Node.js).
   */
  WebSocketCtor?: typeof WebSocket;
}

export interface WireMessage<T = unknown> {
  /** Message type (domain-specific, e.g. `stage.update`). */
  t: string;
  /** Payload. */
  d: T;
  /** Sender-side timestamp (unix epoch ms; optional but encouraged). */
  ts?: number;
}

type EventListener<T> = (payload: T) => void;

/* -------------------------------------------------------------------------- */
/*                             Utility – Backoff                              */
/* -------------------------------------------------------------------------- */

const wait = (ms: number) => new Promise((res) => setTimeout(res, ms));

/* -------------------------------------------------------------------------- */
/*                           WebSocket Client Class                           */
/* -------------------------------------------------------------------------- */

export class WebSocketClient {
  private readonly options: Required<
    Pick<
      WebSocketClientOptions,
      | 'endpoint'
      | 'reconnect'
      | 'maxRetries'
      | 'reconnectIntervalMs'
      | 'maxReconnectIntervalMs'
      | 'backoffMultiplier'
      | 'logger'
    >
  > & {
    getAuthToken?: () => Promise<string | undefined>;
    WebSocketCtor: typeof WebSocket;
  };

  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private isManuallyClosed = false;
  private readonly emitter = new EventEmitter();
  private readonly outgoingQueue: string[] = [];
  private pingIntervalId: ReturnType<typeof setInterval> | null = null;

  /* ------------------------------- Constructor ---------------------------- */

  constructor(opts: WebSocketClientOptions) {
    // Normalise defaults
    this.options = {
      endpoint: opts.endpoint,
      getAuthToken: opts.getAuthToken,
      reconnect: opts.reconnect ?? true,
      maxRetries: opts.maxRetries ?? Infinity,
      reconnectIntervalMs: opts.reconnectIntervalMs ?? 1_000,
      maxReconnectIntervalMs: opts.maxReconnectIntervalMs ?? 30_000,
      backoffMultiplier: opts.backoffMultiplier ?? 1.5,
      logger: opts.logger ?? (console as Logger),
      WebSocketCtor: opts.WebSocketCtor ?? WebSocket,
    };
  }

  /* ----------------------------- Public  API ------------------------------ */

  /**
   * Connect to the WebSocket gateway.
   */
  async connect(): Promise<void> {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      this.options.logger.debug('[WS] Already connected/connecting');
      return;
    }

    this.isManuallyClosed = false;
    await this.openSocket();
  }

  /**
   * Send a message down the socket. If the socket is currently closed,
   * the message is queued and flushed upon re-connection.
   */
  send<T = unknown>(type: string, payload: T): void {
    const msg: WireMessage<T> = { t: type, d: payload, ts: Date.now() };
    const encoded = JSON.stringify(msg);

    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(encoded);
    } else {
      this.options.logger.debug(`[WS] Queueing message (${type}) – socket not open`);
      this.outgoingQueue.push(encoded);
    }
  }

  /**
   * Subscribe to a specific message type.
   * The returned function can be used to unsubscribe.
   */
  subscribe<T = unknown>(type: string, listener: EventListener<T>): () => void {
    const wrapped = (payload: T) => listener(payload);
    this.emitter.on(type, wrapped);
    return () => this.emitter.off(type, wrapped);
  }

  /**
   * Disconnect from the WebSocket gateway and **disable** automatic reconnect.
   */
  async disconnect(code?: number, reason?: string): Promise<void> {
    this.isManuallyClosed = true;
    this.cleanupPing();

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.close(code, reason);
    }

    this.ws = null;
  }

  /* --------------------------- Private helpers ---------------------------- */

  /**
   * Open a new WebSocket connection (with auth, if provided).
   */
  private async openSocket(): Promise<void> {
    const url = await this.constructEndpointWithAuth();
    this.options.logger.info('[WS] Connecting →', url);

    try {
      const ws = new this.options.WebSocketCtor(url);
      this.ws = ws;

      ws.addEventListener('open', this.handleOpen);
      ws.addEventListener('message', this.handleMessage);
      ws.addEventListener('close', this.handleClose);
      ws.addEventListener('error', this.handleError);
    } catch (err) {
      this.options.logger.error('[WS] Failed to construct WebSocket', err);
      this.scheduleReconnect();
    }
  }

  /**
   * Attach the bearer token (if any) as query param `token`.
   */
  private async constructEndpointWithAuth(): Promise<string> {
    let url = this.options.endpoint;

    if (this.options.getAuthToken) {
      try {
        const token = await this.options.getAuthToken();
        if (token) {
          const sep = url.includes('?') ? '&' : '?';
          url += `${sep}token=${encodeURIComponent(token)}`;
        }
      } catch (err) {
        this.options.logger.warn('[WS] Failed to obtain auth token', err);
      }
    }

    return url;
  }

  /**
   * Flush queued messages now that the socket is open.
   */
  private flushQueue(): void {
    while (this.outgoingQueue.length) {
      const payload = this.outgoingQueue.shift();
      if (payload && this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(payload);
      } else {
        break;
      }
    }
  }

  /* ------------------------------ Handlers -------------------------------- */

  private handleOpen = (): void => {
    this.options.logger.info('[WS] Connected');
    this.reconnectAttempts = 0;

    this.startPing();
    this.flushQueue();
    this.emitter.emit('ws.open'); // broadcast meta event
  };

  private handleMessage = (ev: MessageEvent<string>): void => {
    try {
      const msg: WireMessage = JSON.parse(ev.data);
      this.emitter.emit(msg.t, msg.d);
    } catch (err) {
      this.options.logger.warn('[WS] Malformed message', ev.data, err);
    }
  };

  private handleClose = (ev: CloseEvent): void => {
    this.options.logger.warn(`[WS] Closed – code=${ev.code} reason=${ev.reason}`);

    this.cleanupPing();
    this.emitter.emit('ws.close', { code: ev.code, reason: ev.reason });

    if (!this.isManuallyClosed && this.options.reconnect) {
      this.scheduleReconnect();
    }
  };

  private handleError = (ev: Event): void => {
    this.options.logger.error('[WS] Error', ev);
    // Let the close handler deal with reconnections.
  };

  /* ------------------------- Reconnection Logic -------------------------- */

  private async scheduleReconnect(): Promise<void> {
    if (this.reconnectAttempts >= this.options.maxRetries) {
      this.options.logger.error('[WS] Reconnect attempts exhausted');
      this.emitter.emit('ws.reconnect_failed');
      return;
    }

    const retryIn = Math.min(
      this.options.reconnectIntervalMs * Math.pow(this.options.backoffMultiplier, this.reconnectAttempts),
      this.options.maxReconnectIntervalMs,
    );

    this.reconnectAttempts += 1;
    this.options.logger.info(`[WS] Reconnecting in ${retryIn}ms (attempt ${this.reconnectAttempts})`);

    await wait(retryIn);
    if (!this.isManuallyClosed) {
      this.openSocket();
    }
  }

  /* ---------------------------- Heart-Beating ---------------------------- */

  /**
   * Some gateways require heartbeats to keep the connection alive.
   * Here we send a lightweight ping every 25s.
   * Adjust interval according to backend expectations.
   */
  private startPing(): void {
    this.cleanupPing();
    this.pingIntervalId = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ t: 'ping', ts: Date.now() }));
      }
    }, 25_000);
  }

  private cleanupPing(): void {
    if (this.pingIntervalId) {
      clearInterval(this.pingIntervalId);
      this.pingIntervalId = null;
    }
  }
}

/* -------------------------------------------------------------------------- */
/*                         Singleton (default export)                         */
/* -------------------------------------------------------------------------- */

/**
 * Applications can either instantiate their own client or use the shared
 * default export below.
 *
 * Example:
 *   import ws from '@/api/websocket-client';
 *
 *   ws.connect();
 *   const unsubscribe = ws.subscribe('stage.update', (data) => …);
 */

const defaultClient = new WebSocketClient({
  endpoint: `${process.env.NEXT_PUBLIC_WS_GATEWAY ?? ''}/ws`, // Example env
  reconnect: true,
  getAuthToken: async () => {
    // Example: read access token from localStorage or wallet handler
    return localStorage.getItem('access_token') ?? undefined;
  },
});

export default defaultClient;
```