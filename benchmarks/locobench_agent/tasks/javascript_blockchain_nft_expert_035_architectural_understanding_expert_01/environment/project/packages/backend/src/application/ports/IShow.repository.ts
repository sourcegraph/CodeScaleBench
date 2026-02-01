```typescript
/* eslint-disable @typescript-eslint/no-unused-vars */

/**
 * StellarStage Carnival
 * packages/backend/src/application/ports/IShow.repository.ts
 *
 * Repository Port (Clean Architecture):
 * -------------------------------------
 * Defines all persistence-layer behaviours required by the
 * Show aggregate root.  Concrete adapters (PostgreSQL, IPFS,
 * Subgraph, Smart-Contract events, etc.) must implement this
 * interface and be wired in through dependency-injection.
 *
 * NOTE:  No infrastructure-specific details belong in here.
 */

import type { Show } from '../../domain/entities/Show';
import type { ShowId } from '../../domain/value-objects/ShowId';
import type { DateRange } from '../../domain/value-objects/DateRange';
import type { DomainEvent } from '../../domain/events/DomainEvent';

/**
 * Lightweight pagination helpers used by many repository ports.
 * Kept intentionally minimal to avoid pulling an external dep.
 */
export interface PaginationOptions {
  /**
   * Zero-based page index.  0 === first page.
   */
  readonly page?: number;

  /**
   * How many records per page?
   * A sane default should be enforced by the implementation.
   */
  readonly limit?: number;

  /**
   * Optional column / field to order by.
   */
  readonly sortBy?: string;

  /**
   * ASC | DESC
   */
  readonly direction?: 'ASC' | 'DESC';
}

export interface PaginatedResult<T> {
  readonly data: readonly T[];
  readonly total: number;
  readonly page: number;
  readonly pages: number;
}

/**
 * Custom error types surfaced by repository implementations
 * so the application layer can handle gracefully.
 */
export class RepositoryError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'RepositoryError';
  }
}

export class OptimisticLockError extends RepositoryError {
  constructor(readonly id: ShowId) {
    super(`Optimistic-lock failed for Show<${id.value}>`);
    this.name = 'OptimisticLockError';
  }
}

/**
 * Show Repository Port.
 * Implementations must be transactional and thread-safe.
 */
export interface IShowRepository {
  /**
   * Persist a brand-new Show aggregate.
   * Should throw RepositoryError on failure, or OptimisticLockError
   * if concurrent writes are detected on the same record.
   *
   * @param show Aggregate to persist
   */
  create(show: Show): Promise<void>;

  /**
   * Update an existing Show aggregate.
   *
   * Implementations SHOULD perform optimistic concurrency checks
   * using Show.version (or equivalent) to guarantee no lost updates.
   *
   * @param show Aggregate to update
   * @throws OptimisticLockError
   */
  update(show: Show): Promise<void>;

  /**
   * Retrieve a Show by its unique identifier.
   *
   * @param id Aggregate identifier
   * @returns Null if no Show exists with given id
   */
  findById(id: ShowId): Promise<Show | null>;

  /**
   * Retrieve Shows that fall inside a provided date range
   * (intersects either startDate or endDate).
   *
   * @param range Arbitrary date range filter
   * @param pagination Standard pagination options
   */
  findByDateRange(
    range: DateRange,
    pagination?: PaginationOptions
  ): Promise<PaginatedResult<Show>>;

  /**
   * Convenience helpers adopted by a number of use-cases.
   * These are intentionally left in the port as they encode business
   * vocabulary (Active / Upcoming / Past) not storage concerns.
   */

  findActive(
    pagination?: PaginationOptions
  ): Promise<PaginatedResult<Show>>;

  findUpcoming(
    pagination?: PaginationOptions
  ): Promise<PaginatedResult<Show>>;

  findPast(
    pagination?: PaginationOptions
  ): Promise<PaginatedResult<Show>>;

  /**
   * Mark the show as archived (soft-delete) without removing
   * historical data.  Auditable systems can rely on this.
   *
   * @param id Aggregate identifier
   * @param reason Optional human-readable reason
   */
  archive(id: ShowId, reason?: string): Promise<void>;

  /**
   * Publish DomainEvents accumulated within the Show aggregate.
   * A common pattern is to commit the aggregate and enqueue its
   * outbox events atomically (Transactional-Outbox).
   *
   * Implementations may choose to:
   *  ‑ Push to a message broker (Kafka, NATS, RabbitMQ, etc.)
   *  ‑ Invoke in-process EventBus for local projections
   *  ‑ Write to an `outbox` table to be fanned-out asynchronously
   *
   * @param events Domain events to propagate
   */
  publishEvents?(...events: DomainEvent[]): Promise<void>;

  /**
   * Reactive stream of aggregate updates.
   *
   * The backend’s Event-Driven architecture leverages database
   * NOTIFY/LISTEN, Postgres logical replication, or Subgraph
   * websocket feeds to push live updates to subscribers.
   *
   * Consumers (e.g. GraphQL resolvers, WebSocket gateways) can
   * iterate over the AsyncIterable to relay real-time data to
   * front-end clients without polling the repository.
   *
   * @example
   *    const stream = repo.watchById(showId);
   *    for await (const updatedShow of stream) {
   *       websocket.send(JSON.stringify(updatedShow));
   *    }
   *
   * @param id Aggregate identifier
   */
  watchById?(id: ShowId): AsyncIterable<Show>;

  /**
   * Utility to execute multiple operations inside a transaction
   * boundary.  Several use-cases save Show + MintPass + Loot in a
   * single atomic unit.  The application service can request a
   * transaction from the repository without leaking ORM details.
   *
   * Implementations should roll back automatically if the callback
   * rejects or an error is thrown.
   *
   * @param work Callback that receives a *scoped* repository and
   *             returns an arbitrary result.
   */
  withTransaction<R>(
    work: (repo: IShowRepository) => Promise<R>
  ): Promise<R>;
}
```