```typescript
/****************************************************************************************
 * StellarStage Carnival (backend)
 * File:    packages/backend/src/infrastructure/adapters/blockchain/contract.mapper.ts
 * Author:  StellerStage Core Team
 *
 * Purpose:
 *   Bridges domain-layer entities/event objects with low-level EVM smart–contract calls.
 *   All “knowledge” about on-chain ABI encodings, contract addresses and network IDs
 *   lives here, keeping the rest of the codebase completely blockchain-agnostic.
 *
 *   – Maps domain commands to contract write-transactions (mint, stake, distribute…)
 *   – Hydrates ethers.js Contract instances from a runtime registry
 *   – Translates on-chain events back into strongly-typed domain events
 *
 * Usage example (inside a Use-Case service):
 *   const { contract, data } = contractMapper.toMintShowPassTx(pass);
 *   const tx = await signer.sendTransaction({ ...data, to: contract.address });
 *
 ****************************************************************************************/

import { ethers, Contract, ContractInterface, Event } from 'ethers';
import path from 'path';
import fs from 'fs';
import { z } from 'zod';

import { ShowPass } from '../../../domain/entities/ShowPass';
import { Loot } from '../../../domain/entities/Loot';
import { LiveVoteCast } from '../../../domain/events/LiveVoteCast';
import { DomainEvent } from '../../../domain/events/DomainEvent';

import { BlockchainConfig, NetworkId } from '../config/blockchain.config';
import logger from '../../logger';
import { InfrastructureError } from '../../errors';

/**
 * Type guards & runtime validators (zod) — make absolutely sure we’re never sending
 * malformed data to the chain. These schemas travel with compiled JS (no TS only).
 */
const MintPassParamsSchema = z.object({
  to: z.string().startsWith('0x').length(42),
  tokenId: z.bigint().nonnegative(),
  metadataURI: z.string().url(),
});

export type MintPassParams = z.infer<typeof MintPassParamsSchema>;

/**
 * Minimal subset of contract ABI fragments we care about for mappings
 * (we don’t want to load the entire, heavyweight ABI if not needed).
 */
const ABI_FRAGMENT: Record<
  'ShowPass' | 'Loot' | 'Governance',
  ContractInterface
> = {
  ShowPass: [
    'function safeMint(address to, uint256 tokenId, string memory uri) public',
    'event Transfer(address indexed from, address indexed to, uint256 indexed tokenId)',
  ],
  Loot: [
    'function distribute(address to, uint256 lootId, uint256 qty) external',
    'event LootDistributed(address indexed to, uint256 indexed lootId, uint256 qty)',
  ],
  Governance: [
    'function castVote(uint256 proposalId, uint8 option) external',
    'event VoteCast(address voter, uint256 indexed proposalId, uint8 option)',
  ],
};

/**
 * Simple, in-memory contract registry built from BlockchainConfig.
 * Could be easily replaced with a dynamic (e.g., ENS) lookup later.
 */
class ContractRegistry {
  private readonly registry: Map<
    NetworkId,
    Record<'ShowPass' | 'Loot' | 'Governance', string>
  > = new Map();

  constructor(private readonly cfg: BlockchainConfig) {
    this.bootstrap(cfg);
  }

  getAddress(
    network: NetworkId,
    contractType: 'ShowPass' | 'Loot' | 'Governance',
  ): string {
    const map = this.registry.get(network);
    if (!map || !map[contractType]) {
      throw new InfrastructureError(
        `Unknown contract address for ${contractType} on ${network}`,
      );
    }
    return map[contractType];
  }

  private bootstrap(cfg: BlockchainConfig): void {
    Object.entries(cfg.contracts).forEach(([network, contracts]) => {
      this.registry.set(network as NetworkId, contracts);
    });
  }
}

/**
 * Main mapper — all mapping logic lives here, centralising blockchain concerns.
 */
export class ContractMapper {
  private readonly provider: ethers.JsonRpcProvider;
  private readonly registry: ContractRegistry;

  constructor(private readonly cfg: BlockchainConfig) {
    this.provider = new ethers.JsonRpcProvider(cfg.rpcUrl);
    this.registry = new ContractRegistry(cfg);
  }

  /**************************************************************************
   *                               WRITES                                  *
   **************************************************************************/

  /**
   * Translates domain ShowPass entity to low-level tx data for safeMint().
   * Returns the prepared Contract instance as well so caller can easily
   * connect a signer and send the transaction.
   */
  public toMintShowPassTx(
    pass: ShowPass,
  ): { contract: Contract; data: ethers.TransactionRequest } {
    // Build and validate params
    const params: MintPassParams = {
      to: pass.ownerAddress,
      tokenId: BigInt(pass.id),
      metadataURI: pass.metadataURI,
    };
    MintPassParamsSchema.parse(params);

    const contract = this.getContract('ShowPass');
    const data = contract.interface.encodeFunctionData('safeMint', [
      params.to,
      params.tokenId,
      params.metadataURI,
    ]);

    return {
      contract,
      data: {
        to: contract.address,
        data,
        // gasLimit/gasPrice left undefined; caller (service) or wallet picks values.
      },
    };
  }

  public toDistributeLootTx(
    loot: Loot,
    recipient: string,
  ): { contract: Contract; data: ethers.TransactionRequest } {
    if (!ethers.isAddress(recipient))
      throw new InfrastructureError('Recipient must be a valid EVM address');

    const contract = this.getContract('Loot');
    const encoded = contract.interface.encodeFunctionData('distribute', [
      recipient,
      loot.id,
      loot.quantity,
    ]);

    return {
      contract,
      data: {
        to: contract.address,
        data: encoded,
      },
    };
  }

  /**************************************************************************
   *                               READS                                   *
   **************************************************************************/

  /**
   * Parses raw on-chain Event object into strongly typed domain event.
   * Add new pattern matches here whenever a new event is added on-chain.
   */
  public toDomainEvent(event: Event): DomainEvent | null {
    const { fragment } = event;
    try {
      switch (fragment?.name) {
        case 'Transfer': {
          // Transfer event is used to mint as well (from = 0x0)
          const [from, to, tokenId] = event.args as [string, string, bigint];
          return new LiveVoteCast(
            'passTransfer',
            {
              from,
              to,
              tokenId: Number(tokenId),
            },
            event.blockNumber,
          );
        }

        case 'LootDistributed': {
          const [to, lootId, qty] = event.args as [string, bigint, bigint];
          return {
            type: 'LootDistributed',
            payload: {
              to,
              lootId: Number(lootId),
              qty: Number(qty),
            },
            occurredAtBlock: event.blockNumber,
          } as DomainEvent;
        }

        case 'VoteCast': {
          const [voter, proposalId, option] = event.args as [
            string,
            bigint,
            number,
          ];
          return new LiveVoteCast(
            'governanceVote',
            {
              voter,
              proposalId: Number(proposalId),
              option,
            },
            event.blockNumber,
          );
        }

        default:
          return null; // Unrecognised event; ignore
      }
    } catch (err) {
      // Never let an event crash the stream; just log & skip
      logger.warn(
        { err, txHash: event.transactionHash, event: fragment?.name },
        'Failed to map blockchain event',
      );
      return null;
    }
  }

  /**************************************************************************
   *                             INTERNAL                                  *
   **************************************************************************/

  /**
   * Resolves a Contract connected to read-only provider.
   * (Use contract.connect(signer) before doing writes.)
   */
  private getContract(
    type: 'ShowPass' | 'Loot' | 'Governance',
  ): ethers.Contract {
    const address = this.registry.getAddress(this.cfg.networkId, type);
    const abi = ABI_FRAGMENT[type];

    return new ethers.Contract(address, abi, this.provider);
  }
}

/******************************************************************************
 *                                TYPES & EXPORTS                             *
 ******************************************************************************/

export default ContractMapper;

/******************************************************************************
 *                                   EOF                                      *
 ******************************************************************************/
```