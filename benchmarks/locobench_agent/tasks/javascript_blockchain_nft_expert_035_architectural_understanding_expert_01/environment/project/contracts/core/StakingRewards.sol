```javascript
// File: StellarStageCarnival/contracts/core/StakingRewards.sol
// NOTE: Although the path uses a *.sol suffix for historical reasons,
// this is a JavaScript service that orchestrates the on-chain
// StakingRewards Solidity contract through ethers.js.
//
// The service respects Clean-Architecture boundaries: it lives in the
// “core” layer, exposes only pure domain behaviour, and delegates all
// blockchain IO to the injected ethers Provider / Signer.
//
// Author: StellarStage Carnival Core Team
// SPDX-License-Identifier: BUSL-1.1

/* eslint-disable max-classes-per-file */

import { EventEmitter } from 'node:events';
import { ethers } from 'ethers';
import pRetry from 'p-retry';

/**
 * Encapsulates a connection to the on-chain StakingRewards smart-contract
 * and provides a high-level, domain-specific API surface.
 *
 * Responsibilities:
 * 1. Aggregate read/write calls, adding retries, timeouts and gas-estimates.
 * 2. Transform low-level BigNumber values into native JS numbers/bigints.
 * 3. Emit observer events to the Event-Bus for reactive UI updates.
 * 4. Remain framework-agnostic so that other adapters (GraphQL, WS) may
 *    reuse its logic without coupling to UI or infra specifics.
 */
export default class StakingRewardsService extends EventEmitter {
  /**
   * @param {Object}   opts
   * @param {ethers.Signer} opts.signer  – an ethers.js Signer authorised to push txs
   * @param {string}   opts.address      – deployed StakingRewards proxy address
   * @param {Object[]} opts.abi          – contract ABI JSON
   * @param {number}   [opts.confirmations=2] – blocks to wait before emitting success
   * @param {number}   [opts.timeout=90_000] – tx timeout in ms
   */
  constructor({ signer, address, abi, confirmations = 2, timeout = 90_000 }) {
    super();

    if (!signer || !address || !abi) {
      throw new TypeError(
        'StakingRewardsService requires { signer, address, abi }',
      );
    }

    this._signer = signer;
    this._contract = new ethers.Contract(address, abi, signer);
    this._confirmations = confirmations;
    this._timeout = timeout;

    // Bind public methods to maintain `this` context when used as callbacks.
    [
      'stake',
      'unstake',
      'claimRewards',
      'pendingRewards',
      'stakedTokensOf',
    ].forEach((fn) => (this[fn] = this[fn].bind(this)));
  }

  /* -----------------------------------------------------------------------
   * Write operations
   * --------------------------------------------------------------------- */

  /**
   * Stake one or many Show-Pass NFT tokenIds.
   *
   * @param {bigint|number|string|Array<bigint|number|string>} tokenIds
   * @returns {Promise<ethers.TransactionReceipt>}
   */
  async stake(tokenIds) {
    const ids = Array.isArray(tokenIds) ? tokenIds : [tokenIds];

    if (!ids.length) throw new Error('stake() tokenIds list cannot be empty');

    const tx = await this._dispatchTx(
      () => this._contract.stake(ids),
      'Staked',
    );

    this.emit('stake:success', { tx, tokenIds: ids });
    return tx;
  }

  /**
   * Unstake previously staked Pass NFTs.
   *
   * @param {bigint|number|string|Array<bigint|number|string>} tokenIds
   * @returns {Promise<ethers.TransactionReceipt>}
   */
  async unstake(tokenIds) {
    const ids = Array.isArray(tokenIds) ? tokenIds : [tokenIds];

    if (!ids.length) throw new Error('unstake() tokenIds list cannot be empty');

    const tx = await this._dispatchTx(
      () => this._contract.unstake(ids),
      'Unstaked',
    );

    this.emit('unstake:success', { tx, tokenIds: ids });
    return tx;
  }

  /**
   * Claim ERC-20 reward tokens generated so far.
   *
   * @returns {Promise<ethers.TransactionReceipt>}
   */
  async claimRewards() {
    const tx = await this._dispatchTx(
      () => this._contract.claimRewards(),
      'RewardsClaimed',
    );

    this.emit('claim:success', { tx });
    return tx;
  }

  /* -----------------------------------------------------------------------
   * Read-only operations
   * --------------------------------------------------------------------- */

  /**
   * Returns the caller’s current reward balance that can be claimed.
   *
   * @returns {Promise<bigint>} pending reward amount (18 decimals)
   */
  async pendingRewards() {
    const address = await this._signer.getAddress();
    const rewards = await this._contract.pendingRewards(address);
    return rewards.toBigInt();
  }

  /**
   * List of tokenIds the caller has staked.
   *
   * @returns {Promise<bigint[]>}
   */
  async stakedTokensOf() {
    const address = await this._signer.getAddress();
    const ids = await this._contract.stakedTokensOf(address);
    return ids.map((n) => n.toBigInt());
  }

  /* -----------------------------------------------------------------------
   * Internal helpers
   * --------------------------------------------------------------------- */

  /**
   * Wrap a mutating on-chain call with retry, gas-estimation and timeout.
   *
   * @param {Function} txFn       – () => Promise<ethers.PopulatedTransaction>
   * @param {string}   eventName  – primary solidity event emitted by tx
   * @returns {Promise<ethers.TransactionReceipt>}
   * @private
   */
  async _dispatchTx(txFn, eventName) {
    // Use p-retry for transient RPC failures (e.g. “nonce too low”)
    return pRetry(
      async () => {
        const populated = await txFn();

        const gasEstimate =
          populated.gasLimit ||
          (await this._contract.provider.estimateGas(populated)).mul(110).div(100); // +10 %

        const txResponse = await this._signer.sendTransaction({
          ...populated,
          gasLimit: gasEstimate,
        });

        this.emit('tx:sent', { hash: txResponse.hash, eventName });

        // Wait for confirmations or timeout, whichever comes first.
        const receipt = await Promise.race([
          txResponse.wait(this._confirmations),
          this._timeoutAfter(this._timeout, txResponse.hash),
        ]);

        if (receipt.status !== 1) {
          const error = new Error(
            `Transaction reverted: ${txResponse.hash}`,
          );
          error.receipt = receipt;
          throw error;
        }

        return receipt;
      },
      {
        retries: 3,
        minTimeout: 1_000,
        maxTimeout: 4_000,
        onFailedAttempt: (err) =>
          this.emit('tx:retry', {
            attemptNumber: err.attemptNumber,
            retriesLeft: err.retriesLeft,
            message: err.message,
          }),
      },
    );
  }

  /**
   * Helper that rejects after ms, used to guard .wait() promises.
   *
   * @param {number} ms    – milliseconds
   * @param {string} hash  – tx hash for debugging
   * @returns {Promise<never>}
   * @private
   */
  _timeoutAfter(ms, hash) {
    return new Promise((_, reject) => {
      const id = setTimeout(() => {
        clearTimeout(id);
        reject(
          new Error(`Timed out waiting for tx confirmation: ${hash} (${ms} ms)`),
        );
      }, ms);
    });
  }
}

/* -----------------------------------------------------------------------
 * Event name reference:
 *
 *  - tx:sent            { hash, eventName }
 *  - tx:retry           { attemptNumber, retriesLeft, message }
 *  - stake:success      { tx, tokenIds }
 *  - unstake:success    { tx, tokenIds }
 *  - claim:success      { tx }
 *
 * Consumers should listen and react accordingly:
 *
 *    const staking = new StakingRewardsService(...);
 *    staking.on('stake:success', ({ tx, tokenIds }) => {
 *      console.log('Staked 🎟️  ', tokenIds, 'in tx', tx.transactionHash);
 *    });
 * --------------------------------------------------------------------- */
```