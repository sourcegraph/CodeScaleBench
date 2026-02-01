```typescript
/* ============================================================================
 * File: packages/backend/src/application/ports/IBlockchain.service.ts
 * Project: StellarStage Carnival – Interactive NFT Showrunner
 * Description:
 *   Clean-Architecture “Port” that abstracts every interaction with an underlying
 *   blockchain (Ethereum, Polygon, Optimism, Arbitrum, etc.).  The domain- and
 *   application-layers depend on this contract only, never on concrete SDKs such
 *   as ethers.js/web3.js or chain-specific RPC quirks.
 *
 *   Infrastructure adapters are expected to implement this interface and can swap
 *   in/out at runtime (or via DI) without touching business logic.
 * ========================================================================== */

import { BigNumber, BytesLike } from 'ethers';
import { EventEmitter } from 'events';

/**
 * Canonical on-chain address string.
 * Checksums, bech32, etc. are implementer-specific.
 */
export type Address = string;

/**
 * Minimal subset of a transaction receipt we care about on the
 * application-layer.  Concrete adapters MAY extend this.
 */
export interface TxReceipt {
  txHash: string;
  blockNumber: number;
  status: 'success' | 'reverted' | 'dropped';
  gasUsed: BigNumber;
  events?: Record<string, unknown>;
}

/**
 * Parameters required when minting a show-pass NFT.
 */
export interface MintParams {
  to: Address;
  showId: string;               // UUID of the Show aggregate root
  metadataUri: string;          // IPFS or Arweave URL
  traits: Record<string, any>;  // Initial dynamic trait bag
  nonce?: number;               // Optional for meta-txs
  value?: BigNumber;            // ETH/Token cost of the mint
}

/**
 * Governance vote payload.
 */
export interface GovernanceVote {
  proposalId: string;
  support: 0 | 1 | 2;           // EIP-712 Governor Bravo style
  voter: Address;
  weight: BigNumber;
}

/**
 * Domain-level representation of a chain event.
 */
export interface ChainEvent<T = unknown> {
  /** e.g. `ShowPassUpgraded`, `VoteCast`, `Transfer` */
  name: string;
  /** Raw log args decoded by the concrete adapter */
  payload: T;
  /** Block timestamp in seconds */
  timestamp: number;
}

/**
 * Runtime environment / network.
 */
export enum Chain {
  ETHEREUM_MAINNET   = 1,
  ETHEREUM_GOERLI    = 5,
  POLYGON            = 137,
  POLYGON_MUMBAI     = 80001,
  OPTIMISM_MAINNET   = 10,
  OPTIMISM_GOERLI    = 420,
  ARBITRUM_ONE       = 42161,
  ARBITRUM_GOERLI    = 421613,
}

/**
 * All blockchain adapters MUST throw one of these errors so the application
 * layer can map them to user-friendly domain errors.
 */
export class BlockchainError extends Error {
  public readonly cause?: unknown;

  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'BlockchainError';
    this.cause = cause;
  }
}

export class ConnectionError extends BlockchainError {
  constructor(message = 'Unable to connect to RPC provider', cause?: unknown) {
    super(message, cause);
    this.name = 'ConnectionError';
  }
}

export class TransactionError extends BlockchainError {
  public readonly txHash?: string;

  constructor(message = 'Transaction failed', txHash?: string, cause?: unknown) {
    super(message, cause);
    this.name = 'TransactionError';
    this.txHash = txHash;
  }
}

/* ========================================================================== */
/*                                  INTERFACE                                 */
/* ========================================================================== */

/**
 * The single source of truth for _all_ blockchain side-effects in the backend.
 * No other service may directly touch RPC endpoints, wallet providers, or
 * client-side SDKs.
 */
export interface IBlockchainService {
  /**
   * Returns an event emitter that pipes real-time chain events (logs, heads,
   * pending txs) so higher layers can subscribe via Observer pattern.
   *
   * Implementers SHOULD:
   *  - Prefix event names with the contract alias (e.g. `ShowPass.Transfer`)
   *  - Emit a `connected` / `disconnected` control event
   */
  readonly eventBus: EventEmitter;

  /* ------------------------------- Accounts -------------------------------- */

  /**
   * Resolve the native token (ETH, MATIC, etc.) balance of an address.
   * Throws ConnectionError.
   */
  getNativeBalance(address: Address): Promise<BigNumber>;

  /**
   * Fetch ERC-20 balance; token symbol/decimals abstraction stays in infra.
   */
  getTokenBalance(tokenAddress: Address, holder: Address): Promise<BigNumber>;

  /* ------------------------------ NFT / Passes ----------------------------- */

  /**
   * Mints a show-pass ERC-721/1155 token with dynamic trait anchors.
   * Returns transaction receipt on fulfillment, or throws TransactionError.
   */
  mintShowPass(params: MintParams): Promise<TxReceipt>;

  /**
   * Burns an existing pass (e.g. for artist-initiated supply control).
   */
  burnShowPass(tokenId: string, caller: Address): Promise<TxReceipt>;

  /**
   * Upgrades on-chain traits through a signature-based meta-transaction flow.
   */
  evolvePass(
    tokenId: string,
    patch: Partial<Record<string, any>>,
    signer: Address,
  ): Promise<TxReceipt>;

  /* -------------------------- Transaction Helpers -------------------------- */

  /**
   * Execute an arbitrary contract write.
   * Internal usage for exotic show mechanics while keeping the Port surface
   * reasonably stable.
   */
  sendContractTx(
    to: Address,
    data: BytesLike,
    value?: BigNumber,
  ): Promise<TxReceipt>;

  /**
   * Reads storage slot or view function, returning opaque data for the caller
   * to parse.  Infrastructure decides best RPC method (call, eth_getProof, etc.).
   */
  readContract(
    to: Address,
    data: BytesLike,
  ): Promise<BytesLike>;

  /**
   * Wait for transaction confirmation with an optional timeout (ms).
   */
  waitForTx(txHash: string, confirmations?: number, timeoutMs?: number): Promise<TxReceipt>;

  /* ------------------------------ Governance ------------------------------- */

  /**
   * Cast a vote on a snapshot or on-chain governance proposal.
   */
  castGovernanceVote(vote: GovernanceVote): Promise<TxReceipt>;

  /**
   * Query current voting power for an address.
   */
  getVotingPower(delegate: Address, blockTag?: number | 'latest'): Promise<BigNumber>;

  /* ----------------------------- Staking / DeFi ---------------------------- */

  stakePass(tokenId: string, staker: Address, durationDays: number): Promise<TxReceipt>;

  unstakePass(tokenId: string, staker: Address): Promise<TxReceipt>;

  claimStakingRewards(tokenId: string, staker: Address): Promise<TxReceipt>;

  /* ------------------------------ Chain Utils ------------------------------ */

  /**
   * Converts human-readable ether units into Wei BigNumber.
   */
  parseUnits(amount: string, decimals?: number): BigNumber;

  /**
   * Converts Wei BigNumber into human-readable format.
   */
  formatUnits(amount: BigNumber, decimals?: number): string;

  /**
   * Detect the current chain/network id the service is connected to.
   */
  getChainId(): Promise<Chain>;

  /**
   * Health-check endpoint for liveness/readiness probes.
   */
  ping(): Promise<'pong'>;
}
```