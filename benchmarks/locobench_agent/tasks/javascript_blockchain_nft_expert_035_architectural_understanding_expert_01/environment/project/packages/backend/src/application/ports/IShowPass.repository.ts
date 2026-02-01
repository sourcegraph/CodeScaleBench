```typescript
/******************************************************************************************
 * File: packages/backend/src/application/ports/IShowPass.repository.ts
 * Project: StellarStage Carnival – Interactive NFT Showrunner
 * Description:
 *   Repository port (interface) for the ShowPass aggregate root. Concrete implementations
 *   live in the infrastructure layer and handle persistence across different substrates
 *   (PostgreSQL, redis-cache, IPFS, smart-contract calls, etc.). Infrastructure adapters
 *   MUST honour this contract so the application layer remains storage-agnostic.
 ******************************************************************************************/

import { ShowPass } from '../../domain/entities/ShowPass';
import { PassId } from '../../domain/valueObjects/PassId';
import { ShowId } from '../../domain/valueObjects/ShowId';
import { WalletAddress } from '../../domain/valueObjects/WalletAddress';
import { PaginationQuery } from '../../shared/pagination';
import { Result } from '../../shared/Result';
import { DomainError } from '../../shared/errors/DomainError';

/**
 * IShowPassRepository
 * ---------------------------------------------------------------------------
 * Clean-Architecture port for data access of ShowPass NFTs. Every method MUST
 * be idempotent and safe to retry because downstream infrastructure (e.g.
 * blockchain RPC) is eventually consistent and prone to transient failures.
 *
 * All returned Promises SHOULD resolve with a `Result<T, DomainError>` object
 * to make error paths explicit and remove the need for try/catch in the
 * calling application services.
 */
export interface IShowPassRepository {
  /**
   * Persists a freshly-minted ShowPass aggregate. If a record with the same
   * PassId already exists, the call MUST return a DomainError.DuplicateRecord.
   */
  save(showPass: ShowPass): Promise<Result<void, DomainError>>;

  /**
   * Retrieves a ShowPass by its unique PassId.
   * Returns Result.ok(null) when the record is not found.
   */
  findById(passId: PassId): Promise<Result<ShowPass | null, DomainError>>;

  /**
   * Streams all ShowPasses that belong to a given wallet address.
   * Large collections SHOULD be paginated lazily to avoid hot-spot queries.
   */
  findByOwner(
    owner: WalletAddress,
    pagination?: PaginationQuery
  ): Promise<Result<ShowPass[], DomainError>>;

  /**
   * Fetches every ShowPass issued for a specific show.
   * Implementation MAY use cursor-based pagination under the hood.
   */
  findByShow(
    showId: ShowId,
    pagination?: PaginationQuery
  ): Promise<Result<ShowPass[], DomainError>>;

  /**
   * Updates mutable traits on the ShowPass (e.g. level, cosmetics, staking
   * state). Implementations MUST perform optimistic concurrency control using
   * the aggregate's `version` property to prevent lost updates.
   */
  update(showPass: ShowPass): Promise<Result<void, DomainError>>;

  /**
   * Marks the ShowPass as staked in a governance or rewards contract.
   * The concrete repo SHOULD atomically:
   *  - record the staking tx hash
   *  - update staking metadata
   *  - emit a domain event
   */
  stake(
    passId: PassId,
    stakingPoolId: string,
    txHash: string
  ): Promise<Result<void, DomainError>>;

  /**
   * Transfers the ShowPass to a new owner.
   * Infra adapter is responsible for verifying that the provided `from`
   * address is indeed the current owner on-chain, otherwise must return
   * DomainError.UnauthorizedTransfer.
   */
  transfer(
    passId: PassId,
    from: WalletAddress,
    to: WalletAddress,
    txHash: string
  ): Promise<Result<void, DomainError>>;

  /**
   * Burns (irreversibly destroys) the ShowPass NFT. Depending on chain rules,
   * burning may be a two-step process (initiate & confirm).
   */
  burn(passId: PassId, txHash: string): Promise<Result<void, DomainError>>;

  /**
   * Locks the ShowPass, preventing any trait upgrades until unlocked. Used
   * during deterministic trait generation or contract migrations.
   */
  lock(passId: PassId): Promise<Result<void, DomainError>>;

  /**
   * Releases a previously-locked ShowPass.
   */
  unlock(passId: PassId): Promise<Result<void, DomainError>>;

  /**
   * Deletes every ShowPass of a particular show. Reserved for administrative
   * housekeeping (e.g. test nets or rehearsal envs). Implementation MUST be
   * transactional: either all passes are deleted or none.
   */
  purgeByShow(showId: ShowId): Promise<Result<number /* rows deleted */, DomainError>>;
}
```