```typescript
/**
 * StellarStage Carnival – Core Storage Port
 * -----------------------------------------
 * This port specifies the contract that any infrastructure‐level
 * storage adapter (IPFS, Arweave, S3, Filecoin, etc.) must fulfil
 * in order to be utilised by the application & domain layers.
 *
 * NOTHING in this file must import infrastructure-specific code.
 * Doing so would break Clean Architecture boundaries.
 */

import { Readable } from 'node:stream';
import { Observable } from 'rxjs';

/**
 * All valid URI schemes a storage adapter may return.
 * ipfs://, ar://, s3://, https://[…signed] etc.
 */
export type StorageUri = `${string}://${string}`;

/**
 * Standardised metadata that accompanies every object
 * persisted in distributed storage.
 */
export interface StorageObjectMetadata {
  /** Canonical URI for referencing this object (e.g. ipfs://CID) */
  uri: StorageUri;

  /** Content identifier (e.g. IPFS CID, Arweave TX hash, etc.) */
  cid: string;

  /** RFC 2046 media type – determines how data should be interpreted. */
  contentType: string;

  /** Size in bytes. */
  contentLength: number;

  /** Optional checksum (multihash, sha256, …) */
  checksum?: string;

  /** Timestamp of when the object was first persisted. */
  createdAt: Date;

  /** Arbitrary key/value tags for indexing and retrieval. */
  tags?: Record<string, string | number | boolean>;
}

/**
 * Options influencing how an object is stored.
 */
export interface PutOptions {
  /** Override contentType if auto-detection fails. */
  contentType?: string;

  /** Optional human-readable filename (used for HTTP gateways). */
  fileName?: string;

  /** Extra tags to persist along with the object. */
  tags?: Record<string, string | number | boolean>;

  /** If true the adapter should broadcast pinning/bundling events. */
  emitEvents?: boolean;
}

/**
 * Options influencing retrieval behaviour.
 */
export interface GetOptions {
  /** When true, the adapter MUST return a Node stream instead of Buffer. */
  asStream?: boolean;

  /** If the object is expected to be JSON, automatically parse it. */
  parseJson?: boolean;

  /** Timeout in milliseconds before the request should abort. */
  timeout?: number;
}

/**
 * Options for generating a signed, time-limited gateway URL
 * that can be exposed publicly (e.g. for a front-end download).
 */
export interface SignedUrlOptions {
  /** How long (in seconds) the URL should remain valid. */
  expiresIn: number;

  /** If true, force the link to download instead of preview. */
  forceDownload?: boolean;

  /** Optional filename users should see in download dialogue. */
  fileName?: string;
}

/**
 * Event types emitted by storage adapters. Used by the event bus
 * to propagate real-time status to the front-end.
 */
export enum StorageEventType {
  OBJECT_PINNED          = 'storage.object.pinned',
  OBJECT_UNPINNED        = 'storage.object.unpinned',
  OBJECT_ARCHIVED        = 'storage.object.archived',
  OBJECT_REHYDRATED      = 'storage.object.rehydrated',
  OBJECT_DELETED         = 'storage.object.deleted',
  PINNING_FAILED         = 'storage.pinning.failed',
  ARCHIVAL_FAILED        = 'storage.archival.failed',
}

/**
 * Generic storage event payload.
 */
export interface StorageEvent {
  type: StorageEventType;
  uri: StorageUri;
  timestamp: number;
  /** Additional provider-specific information */
  details?: Record<string, unknown>;
}

/**
 * Storage port to be used by application use-cases & domain entities.
 *
 * NOTE:
 *  - In Clean Architecture, this interface MUST be technology-agnostic.
 *  - No assumptions are made about the underlying storage mechanism.
 */
export interface IStorageService {
  /**
   * Persist a binary payload or stream.
   *
   * @param data     Buffer or Node stream containing raw bytes.
   * @param options  Behaviour overrides (see PutOptions).
   *
   * @throws StorageWriteError on irrecoverable failure.
   * @returns Metadata describing the newly persisted object.
   */
  put(
    data: Buffer | Readable,
    options?: PutOptions,
  ): Promise<StorageObjectMetadata>;

  /**
   * Retrieve an object previously stored by `put`.
   *
   * Returned type depends on GetOptions:
   *  - Buffer by default
   *  - Readable stream if `asStream === true`
   *  - Parsed JSON object if `parseJson === true`
   *
   * @throws StorageNotFoundError if uri cannot be resolved.
   * @throws StorageReadError on other read issues.
   */
  get(
    uri: StorageUri,
    options?: GetOptions & { asStream: true },
  ): Promise<Readable>;

  get(
    uri: StorageUri,
    options?: GetOptions & { parseJson: true },
  ): Promise<Record<string, unknown>>;

  get(
    uri: StorageUri,
    options?: GetOptions,
  ): Promise<Buffer>;

  /**
   * Check if an object exists without fetching it.
   */
  exists(uri: StorageUri): Promise<boolean>;

  /**
   * Delete an object from the storage provider.
   * Implementations must ensure idempotency.
   */
  delete(uri: StorageUri): Promise<void>;

  /**
   * Generates a time-limited signed URL that grants public read access.
   * Very useful when the front-end needs to download a large asset
   * straight from the storage provider instead of proxying through
   * the backend.
   */
  createSignedUrl(
    uri: StorageUri,
    options: SignedUrlOptions,
  ): Promise<URL>;

  /**
   * Obtain a cold observable that emits storage events in real time.
   * The underlying adapter can employ WebSockets, MQTT, long-polling,
   * or any other mechanism – the abstraction here is RxJS.
   */
  observeEvents(): Observable<StorageEvent>;

  /**
   * Gracefully release any open handles (DB connections,
   * sockets, background timers, etc.) before application shutdown.
   */
  dispose(): Promise<void>;
}

/* ---------- Domain-level error hierarchy ---------- */

/**
 * Marker interface for any storage-related error.
 */
export interface StorageError extends Error {
  uri?: StorageUri;
}

export class StorageWriteError extends Error implements StorageError {
  name = 'StorageWriteError' as const;
  constructor(
    public readonly message: string,
    public readonly uri?: StorageUri,
    public readonly cause?: unknown,
  ) {
    super(message);
  }
}

export class StorageReadError extends Error implements StorageError {
  name = 'StorageReadError' as const;
  constructor(
    public readonly message: string,
    public readonly uri?: StorageUri,
    public readonly cause?: unknown,
  ) {
    super(message);
  }
}

export class StorageNotFoundError extends Error implements StorageError {
  name = 'StorageNotFoundError' as const;
  constructor(
    public readonly uri: StorageUri,
    public readonly message = `Object with uri "${uri}" not found.`,
  ) {
    super(message);
  }
}
```