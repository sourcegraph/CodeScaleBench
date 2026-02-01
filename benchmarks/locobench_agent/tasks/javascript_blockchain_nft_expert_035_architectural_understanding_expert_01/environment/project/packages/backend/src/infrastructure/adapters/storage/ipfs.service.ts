```typescript
/**
 * StellarStage Carnival – IPFS Storage Service
 *
 * This adapter implements the IContentAddressableStoragePort defined in the
 * application layer.  It is responsible for persisting off-chain JSON payloads,
 * assets (audio/video, images, metadata) and upgrade snapshots for dynamic NFTs.
 *
 * The implementation relies on the official `ipfs-http-client` package and
 * supports:
 *   • project-scoped authentication (Infura, Pinata, …)
 *   • automatic gateway URL resolution
 *   • content pinning / unpinning
 *   • robust retry-with-backoff semantics
 *   • basic in-memory caching to avoid redundant network round-trips
 *
 * NOTE: Do NOT import this class directly from business or presentation layers.
 *       Access it exclusively through the dependency-injected port interface.
 */

import { create as createIpfsClient, IPFSHTTPClient } from 'ipfs-http-client';
import pRetry, { AbortError } from 'p-retry';
import LRUCache from 'lru-cache';
import { Readable } from 'stream';

/* ========================================================================== */
/* Ports / Interfaces                                                         */
/* ========================================================================== */

/**
 * Unified port for content-addressable storage.
 * This lives in the application layer in the real code base, but is replicated
 * here to keep the file self-contained for the purpose of this exercise.
 */
export interface IContentAddressableStoragePort {
  /**
   * Persists an arbitrary JSON-serialisable value and returns its CID.
   */
  putJson<T extends object>(payload: T): Promise<string>;

  /**
   * Retrieves JSON content by CID.
   */
  getJson<T = unknown>(cid: string): Promise<T>;

  /**
   * Uploads an (optionally named) file / binary chunk and returns its CID.
   */
  putFile(
    data: Buffer | Readable | string,
    filename?: string,
  ): Promise<{
    cid: string;
    size: number;
  }>;

  /**
   * Generates a public HTTP(s) gateway URL for a CID.
   */
  toGatewayUrl(cid: string, filename?: string): string;

  /**
   * Pins a CID to ensure persistence on the remote pinning cluster.
   */
  pin(cid: string): Promise<void>;

  /**
   * Unpins a previously pinned CID.
   */
  unpin(cid: string): Promise<void>;
}

/* ========================================================================== */
/* Helper Types / Constants                                                   */
/* ========================================================================== */

interface IpfsServiceOptions {
  /** Multi-addr of IPFS endpoint (e.g. https://ipfs.infura.io:5001) */
  endpointUrl: string;

  /** Optional basic-auth credentials for provider-hosted gateways */
  projectId?: string;
  projectSecret?: string;

  /** Pre-defined public gateway base URL (read-only) */
  publicGateway?: string;

  /** Max entries in local LRU cache */
  cacheSize?: number;

  /** Logger instance (must minimally support .info/.warn/.error) */
  logger?: Pick<Console, 'info' | 'warn' | 'error'>;
}

const DEFAULT_GATEWAY = 'https://ipfs.io/ipfs';
const DEFAULT_CACHE_SIZE = 2048;

/* ========================================================================== */
/* Implementation                                                             */
/* ========================================================================== */

export class IpfsService implements IContentAddressableStoragePort {
  /** In-memory LRU cache to speed up hot CID lookups */
  private readonly cache: LRUCache<string, any>;

  /** ipfs-http-client instance  */
  private readonly client: IPFSHTTPClient;

  /** Wire-up logger */
  private readonly log: Pick<Console, 'info' | 'warn' | 'error'>;

  /** Public gateway base URL */
  private readonly gatewayBaseUrl: string;

  constructor(private readonly opts: IpfsServiceOptions) {
    this.gatewayBaseUrl = opts.publicGateway ?? DEFAULT_GATEWAY;

    const auth =
      opts.projectId && opts.projectSecret
        ? 'Basic ' +
          Buffer.from(`${opts.projectId}:${opts.projectSecret}`).toString(
            'base64',
          )
        : undefined;

    this.client = createIpfsClient({
      url: opts.endpointUrl,
      headers: auth ? { Authorization: auth } : undefined,
    });

    this.cache = new LRUCache({
      max: opts.cacheSize ?? DEFAULT_CACHE_SIZE,
      ttl: 1000 * 60 * 5, // 5 min
    });

    this.log = opts.logger ?? console;
  }

  /* ------------------------------------------------------------------------
   * Public API (Port implementation)
   * --------------------------------------------------------------------- */

  async putJson<T extends object>(payload: T): Promise<string> {
    return this.withRetry(async () => {
      const buffer = Buffer.from(JSON.stringify(payload));
      const { cid } = await this.client.add(buffer, { pin: true });
      this.cache.set(cid.toString(), payload);
      this.log.info(`[IPFS] JSON uploaded (${cid})`);
      return cid.toString();
    });
  }

  async getJson<T = unknown>(cid: string): Promise<T> {
    const hit = this.cache.get(cid);
    if (hit) return hit as T;

    return this.withRetry<T>(async () => {
      let data = Buffer.alloc(0);

      for await (const chunk of this.client.cat(cid)) {
        data = Buffer.concat([data, chunk]);
      }

      try {
        const parsed = JSON.parse(data.toString());
        this.cache.set(cid, parsed);
        return parsed;
      } catch (err) {
        this.log.error(`[IPFS] Failed to parse JSON for CID ${cid}`, err);
        throw new Error('Malformed JSON retrieved from IPFS');
      }
    });
  }

  async putFile(
    data: Buffer | Readable | string,
    filename?: string,
  ): Promise<{ cid: string; size: number }> {
    return this.withRetry(async () => {
      const source =
        typeof data === 'string' ? Readable.from(data) : data;
      const { cid, size } = await this.client.add(source, {
        pin: true,
        wrapWithDirectory: Boolean(filename),
        progress: (prog) =>
          this.log.info(`[IPFS] Upload progress ${prog} bytes`),
      });

      const finalCid = filename ? cid.toV1().toString() : cid.toString();
      this.log.info(
        `[IPFS] File uploaded (${finalCid})${filename ? ` as ${filename}` : ''}`,
      );
      return { cid: finalCid, size };
    });
  }

  toGatewayUrl(cid: string, filename?: string): string {
    // Remove potential protocol prefix
    const cleanCid = cid.replace(/^ipfs:\/\//, '');
    return filename
      ? `${this.gatewayBaseUrl}/${cleanCid}/${encodeURIComponent(filename)}`
      : `${this.gatewayBaseUrl}/${cleanCid}`;
  }

  async pin(cid: string): Promise<void> {
    await this.withRetry(async () => {
      await this.client.pin.add(cid);
      this.log.info(`[IPFS] Pinned CID ${cid}`);
    });
  }

  async unpin(cid: string): Promise<void> {
    await this.withRetry(async () => {
      await this.client.pin.rm(cid);
      this.log.info(`[IPFS] Unpinned CID ${cid}`);
    });
  }

  /* ------------------------------------------------------------------------
   * Internals
   * --------------------------------------------------------------------- */

  /**
   * Transparent retry (exponential back-off, max 3 attempts).
   */
  private async withRetry<T>(fn: () => Promise<T>): Promise<T> {
    return pRetry(fn, {
      retries: 3,
      factor: 2,
      onFailedAttempt: (err) => {
        const { attemptNumber, retriesLeft } = err as any;
        this.log.warn(
          `[IPFS] Attempt ${attemptNumber} failed. ${retriesLeft} retries left.`,
        );
      },
      abortOnError: (err) => err instanceof AbortError,
    });
  }
}

/* ========================================================================== */
/* Factory Helper (for DI frameworks)                                         */
/* ========================================================================== */

/**
 * Creates a default IpfsService instance by reading environment variables.
 * This helper is convenient for simple setups; more complex runtimes should
 * use their own IoC container or framework binding.
 */
export function createDefaultIpfsService(): IpfsService {
  const {
    IPFS_ENDPOINT,
    IPFS_PROJECT_ID,
    IPFS_PROJECT_SECRET,
    IPFS_PUBLIC_GATEWAY,
  } = process.env;

  if (!IPFS_ENDPOINT) {
    throw new Error(
      'Missing IPFS_ENDPOINT env variable. Unable to boot IpfsService.',
    );
  }

  return new IpfsService({
    endpointUrl: IPFS_ENDPOINT,
    projectId: IPFS_PROJECT_ID,
    projectSecret: IPFS_PROJECT_SECRET,
    publicGateway: IPFS_PUBLIC_GATEWAY,
  });
}

/* ========================================================================== */
/* Module Augmentation (Optional)                                             */
/* ========================================================================== */

/**
 * Extend the global namespace with a singleton for sporadic scripts /
 * migrations where full DI is overkill.
 *
 * IMPORTANT: This should *never* be imported in browser bundles.
 */
// eslint-disable-next-line @typescript-eslint/no-namespace
declare global {
  // eslint-disable-next-line no-var, vars-on-top
  var __stellarStageIpfs__: IpfsService | undefined;
  // eslint-disable-next-line no-redeclare
  interface Global {
    __stellarStageIpfs__?: IpfsService;
  }
}

/**
 * Lazily initialises a singleton IpfsService using default env config.
 * Useful for tests and stand-alone CLI utilities.
 */
export function getGlobalIpfsService(): IpfsService {
  if (!global.__stellarStageIpfs__) {
    global.__stellarStageIpfs__ = createDefaultIpfsService();
  }
  return global.__stellarStageIpfs__;
}
```