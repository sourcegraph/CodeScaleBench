```typescript
/**************************************************************************************************
 *  StellarStage Carnival – Backend Entrypoint
 *  -----------------------------------------------------------
 *  This file bootstraps the entire backend stack:
 *    • Environment + configuration hydration
 *    • Dependency-Injection container wiring
 *    • Infrastructure adapter instantiation (EVM, IPFS, Streaming, etc.)
 *    • Express HTTP server
 *    • Apollo GraphQL server
 *    • WebSocket relay for real-time stage events
 *    • Graceful shutdown & error boundaries
 *
 *  NOTE:  This file purposefully keeps infrastructure details at arm’s length by deferring
 *         to Clean-Architecture adapters resolved from the IoC container.
 **************************************************************************************************/

import 'reflect-metadata';                        // Required by tsyringe / inversify-like DI libs
import dotenv from 'dotenv';
import http from 'http';
import path from 'path';
import express, { Application, Request, Response, NextFunction } from 'express';
import { ApolloServer } from 'apollo-server-express';
import { WebSocketServer } from 'ws';
import cors from 'cors';
import helmet from 'helmet';
import morgan from 'morgan';
import pino from 'pino';
import { container, inject, injectable, singleton } from 'tsyringe';
import { EventEmitter } from 'events';

/* ---------------------------------------------------------------------------------------------- */
/* 1. Environment                                                                                 */
/* ---------------------------------------------------------------------------------------------- */
dotenv.config({ path: path.resolve(__dirname, '../../../../.env') });

/* ---------------------------------------------------------------------------------------------- */
/* 2. Shared Types & Interfaces                                                                   */
/* ---------------------------------------------------------------------------------------------- */

interface Config {
  env:        string;
  port:       number;
  graphql:    { path: string };
  websocket:  { path: string };
  ipfs:       { gatewayUrl: string };
  ethereum:   { rpcUrl: string; chainId: number };
}

interface Shutdownable {
  shutdown(): Promise<void>;
}

/* ---------------------------------------------------------------------------------------------- */
/* 3. Logger (Pino)                                                                               */
/* ---------------------------------------------------------------------------------------------- */
const logger = pino({
  name: 'StellarStageCarnival',
  level: process.env.LOG_LEVEL || 'info',
  transport: process.env.NODE_ENV !== 'production'
    ? { target: 'pino-pretty', options: { colorize: true } }
    : undefined,
});

/* ---------------------------------------------------------------------------------------------- */
/* 4. Event Bus                                                                                   */
/* ---------------------------------------------------------------------------------------------- */
@singleton()
class EventBus extends EventEmitter {
  /* Wraps NodeJS EventEmitter so we can decorate @inject('EventBus') elsewhere */
}

/* ---------------------------------------------------------------------------------------------- */
/* 5. Configuration Provider                                                                      */
/* ---------------------------------------------------------------------------------------------- */
@singleton()
class ConfigProvider implements Config {
  public readonly env        = process.env.NODE_ENV || 'development';
  public readonly port       = Number(process.env.PORT || 4000);
  public readonly graphql    = { path: '/graphql' };
  public readonly websocket  = { path: '/ws' };
  public readonly ipfs       = { gatewayUrl: process.env.IPFS_GATEWAY_URL || 'https://ipfs.io/ipfs/' };
  public readonly ethereum   = {
    rpcUrl:  process.env.ETH_RPC_URL  || 'https://mainnet.infura.io/v3',
    chainId: Number(process.env.ETH_CHAIN_ID || 1),
  };
}

/* ---------------------------------------------------------------------------------------------- */
/* 6. Infrastructure Adapters (Stubs)                                                             */
/* ---------------------------------------------------------------------------------------------- */
@injectable()
class EthereumAdapter implements Shutdownable {
  constructor(
    @inject('ConfigProvider') private readonly cfg: Config,
    @inject('EventBus') private readonly bus: EventBus,
  ) {}

  public async init() {
    logger.info({ rpc: this.cfg.ethereum.rpcUrl, chain: this.cfg.ethereum.chainId },
      'EthereumAdapter connected');
    // Wire up block listeners, contract proxies & strategies here.
  }

  public async shutdown() {
    logger.info('EthereumAdapter shutting down');
    // Terminate provider connections, websocket subscriptions, etc.
  }
}

@injectable()
class IpfsAdapter implements Shutdownable {
  constructor(@inject('ConfigProvider') private readonly cfg: Config) {}

  public async init() {
    logger.info({ gateway: this.cfg.ipfs.gatewayUrl }, 'IPFS adapter ready');
  }

  public async shutdown() {
    logger.info('IPFS adapter shutting down');
  }
}

/* ---------------------------------------------------------------------------------------------- */
/* 7. GraphQL Schema & Resolvers (Placeholder)                                                    */
/* ---------------------------------------------------------------------------------------------- */
import { makeExecutableSchema } from '@graphql-tools/schema';

const typeDefs = /* GraphQL */ `
  type Query {
    _health: String!
  }
  type Mutation {
    _noop: Boolean
  }
  type Subscription {
    stageEvent: String!
  }
`;

const resolvers = {
  Query: {
    _health: () => 'ok',
  },
  Subscription: {
    stageEvent: {
      subscribe: (_parent: unknown, _args: unknown, { bus }: { bus: EventBus }) =>
        bus.asyncIterator(['STAGE_EVENT']),
      resolve: (payload: string) => payload,
    },
  },
};

const schema = makeExecutableSchema({ typeDefs, resolvers });

/* ---------------------------------------------------------------------------------------------- */
/* 8. Utility: EventEmitter to AsyncIterator bridge                                               */
/* ---------------------------------------------------------------------------------------------- */
import { AsyncIterator } from 'iterall';

(EventEmitter.prototype as any).asyncIterator = function <T>(events: string[]): AsyncIterator<T> {
  const emitter = this;
  let pullQueue: Array<(value: IteratorResult<T>) => void> = [];
  let pushQueue: T[] = [];
  let listening = true;

  const pushValue = (event: T) => {
    if (pullQueue.length) {
      pullQueue.shift()!({ value: event, done: false });
    } else {
      pushQueue.push(event);
    }
  };

  const eventHandlers = events.map(event => {
    const handler = (payload: T) => listening && pushValue(payload);
    emitter.on(event, handler);
    return { event, handler };
  });

  return {
    next() {
      return new Promise<IteratorResult<T>>(resolve => {
        if (pushQueue.length) {
          resolve({ value: pushQueue.shift()!, done: false });
        } else {
          pullQueue.push(resolve);
        }
      });
    },
    return() {
      listening = false;
      eventHandlers.forEach(({ event, handler }) => emitter.removeListener(event, handler));
      pullQueue.forEach(res => res({ value: undefined as any, done: true }));
      return Promise.resolve({ value: undefined as any, done: true });
    },
    throw(error: unknown) {
      listening = false;
      pullQueue.forEach(res => res(Promise.reject(error) as any));
      return Promise.reject(error);
    },
    [Symbol.asyncIterator]() {
      return this;
    },
  };
};

/* ---------------------------------------------------------------------------------------------- */
/* 9. Server Bootstrap                                                                            */
/* ---------------------------------------------------------------------------------------------- */
@singleton()
class Server implements Shutdownable {
  private app: Application;
  private httpServer!: http.Server;
  private wsServer!: WebSocketServer;
  private readonly shutdownables: Shutdownable[] = [];

  constructor(
    @inject('ConfigProvider') private readonly cfg: Config,
    @inject('EventBus') private readonly bus: EventBus,
    @inject(EthereumAdapter) private readonly eth: EthereumAdapter,
    @inject(IpfsAdapter) private readonly ipfs: IpfsAdapter,
  ) {
    this.app = express();
  }

  public async init(): Promise<void> {
    /* --- 1. Core adapters --------------------------------------------------------------------- */
    await Promise.all([this.eth.init(), this.ipfs.init()]);
    this.shutdownables.push(this.eth, this.ipfs);

    /* --- 2. HTTP middleware ------------------------------------------------------------------- */
    this.app.use(cors());
    this.app.use(helmet());
    this.app.use(express.json({ limit: '5mb' }));
    this.app.use(express.urlencoded({ extended: true }));
    this.app.use(
      morgan('dev', {
        stream: { write: (message) => logger.debug(message.trim()) },
        skip: () => this.cfg.env === 'test',
      }),
    );

    /* --- 3. Health-check ---------------------------------------------------------------------- */
    this.app.get('/health', (_req: Request, res: Response) => res.status(200).send('OK'));

    /* --- 4. Apollo GraphQL -------------------------------------------------------------------- */
    const apollo = new ApolloServer({
      schema,
      context: () => ({ bus: this.bus }),
      introspection: this.cfg.env !== 'production',
      plugins: [
        {
          async serverWillStart() {
            return {
              async drainServer() {
                await apollo.stop();
              },
            };
          },
        },
      ],
    });
    await apollo.start();
    apollo.applyMiddleware({ app: this.app, path: this.cfg.graphql.path });

    /* --- 5. HTTP & WebSocket Servers ----------------------------------------------------------- */
    this.httpServer = http.createServer(this.app);

    this.wsServer = new WebSocketServer({ server: this.httpServer, path: this.cfg.websocket.path });
    this.wsServer.on('connection', (socket) => {
      logger.debug('WebSocket client connected');

      const onStageEvent = (payload: string) => socket.send(payload);
      this.bus.on('STAGE_EVENT', onStageEvent);

      socket.on('close', () => {
        this.bus.off('STAGE_EVENT', onStageEvent);
      });
    });

    /* --- 6. Error-handling middleware --------------------------------------------------------- */
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    this.app.use((err: Error, _req: Request, res: Response, _next: NextFunction) => {
      logger.error(err);
      res.status(500).json({ message: 'Internal Server Error' });
    });

    /* --- 7. Start listening ------------------------------------------------------------------- */
    await new Promise<void>((resolve) => {
      this.httpServer.listen(this.cfg.port, () => {
        logger.info(`HTTP  Server ready at http://localhost:${this.cfg.port}`);
        logger.info(`GraphQL endpoint   at http://localhost:${this.cfg.port}${this.cfg.graphql.path}`);
        logger.info(`WebSocket endpoint at ws://localhost:${this.cfg.port}${this.cfg.websocket.path}`);
        resolve();
      });
    });
  }

  public async shutdown(): Promise<void> {
    logger.info('Gracefully shutting down server…');

    await Promise.all(this.shutdownables.map((s) => s.shutdown().catch(logger.error)));

    this.wsServer?.clients.forEach((client) => client.terminate());
    await new Promise<void>((resolve) => this.wsServer?.close(() => resolve()));

    await new Promise<void>((resolve, reject) =>
      this.httpServer?.close((err) => (err ? reject(err) : resolve())),
    );

    logger.info('Shutdown complete');
  }
}

/* ---------------------------------------------------------------------------------------------- */
/* 10. DI Container Wiring                                                                        */
/* ---------------------------------------------------------------------------------------------- */
container.register('ConfigProvider', { useClass: ConfigProvider });
container.register('EventBus', { useClass: EventBus });
container.registerSingleton(EthereumAdapter);
container.registerSingleton(IpfsAdapter);
container.registerSingleton(Server);

const server = container.resolve(Server);

/* ---------------------------------------------------------------------------------------------- */
/* 11. Bootstrap + Graceful Shutdown                                                              */
/* ---------------------------------------------------------------------------------------------- */
server
  .init()
  .catch((err) => {
    logger.fatal(err, 'Failed to start application');
    process.exit(1);
  });

const graceful = async (signal: string) => {
  logger.info({ signal }, 'Received shutdown signal');
  await server.shutdown();
  process.exit(0);
};

process.on('SIGTERM', graceful);
process.on('SIGINT', graceful);

/* eslint-disable no-console */
process.on('unhandledRejection', (reason) => {
  logger.error({ reason }, 'Unhandled Promise rejection');
});
process.on('uncaughtException', (err) => {
  logger.error(err, 'Uncaught exception');
});
```