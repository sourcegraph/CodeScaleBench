```typescript
/****************************************************************************************
 * File: packages/backend/src/application/use-cases/governance/create-proposal.use-case.ts
 *
 * Description:
 *  Use-case responsible for orchestrating the creation of a new on-chain governance
 *  proposal. In true Clean Architecture spirit, it wires together the domain layer,
 *  blockchain gateway & event bus without either of them knowing about each other.
 *
 *  High-level flow:
 *   1.  Validate caller’s governance power (staking, token balance, role, …)
 *   2.  Build a Proposal aggregate from incoming DTO
 *   3.  Persist aggregate in the (off-chain) repository
 *   4.  Send transaction to blockchain gateway to create proposal on-chain
 *   5.  Emit ProposalCreatedDomainEvent through the global EventBus
 *
 *  NOTE:
 *    ‑ The heavy blockchain interaction is delegated to the GovernanceContractGateway
 *    ‑ Domain events are immutable value objects that bubble up to interested adapters
 ****************************************************************************************/

import { v4 as uuid } from 'uuid';
import { Either, left, right } from 'fp-ts/Either';

import { Proposal } from '../../../domain/entities/governance/proposal.entity';
import {
  ProposalRepositoryPort,
  ProposalWriteModel,
} from '../../../domain/ports/repositories/proposal.repository.port';
import {
  GovernanceContractGatewayPort,
  OnChainProposalId,
} from '../../../domain/ports/blockchain/governance-contract.gateway.port';
import {
  EventBusPort,
  DomainEvent,
} from '../../../domain/ports/event-bus/event-bus.port';
import { ProposalCreatedDomainEvent } from '../../../domain/events/governance/proposal-created.event';
import {
  NotEnoughVotingPowerError,
  DuplicateDraftError,
  BlockchainTxFailedError,
} from '../../../domain/errors/governance.errors';

/**
 * Input data contract coming from the outer layer (controller / resolver).
 * Object form is preferred over positional params for long argument lists.
 */
export interface CreateProposalInput {
  creatorWallet: string;
  title: string;
  description: string;
  /**
   * List of JSON-serialisable contract calls the proposal should execute.
   * It mirrors the Governor’s encodedCalldata[] field.
   */
  actions: Array<{
    target: string;
    signature: string;
    calldata: unknown[];
  }>;
  /**
   * EVM block numbers. If omitted, default strategy will be used.
   */
  startBlock?: number;
  endBlock?: number;
}

/**
 * Output contract returned by the use-case. Keeps infrastructure concerns out.
 */
export interface CreateProposalOutput {
  readonly proposalId: string;
  readonly onChainProposalId: OnChainProposalId;
}

/**
 * Dedicated type for potential business errors
 */
export type CreateProposalResult = Either<
  | NotEnoughVotingPowerError
  | DuplicateDraftError
  | BlockchainTxFailedError,
  CreateProposalOutput
>;

/**
 * Use-case service. Because side-effects need to be injected, we rely on
 * dependency injection (constructor method) instead of static Fns.
 */
export class CreateProposalUseCase {
  constructor(
    private readonly proposalRepository: ProposalRepositoryPort,
    private readonly contractGateway: GovernanceContractGatewayPort,
    private readonly eventBus: EventBusPort
  ) {}

  /**
   * Execute business logic. Each step is small and testable.
   */
  async execute(input: CreateProposalInput): Promise<CreateProposalResult> {
    // Step 1 ‑ Check creator’s voting power
    const hasPower = await this.contractGateway.hasSufficientVotingPower(
      input.creatorWallet
    );
    if (!hasPower) {
      return left(new NotEnoughVotingPowerError(input.creatorWallet));
    }

    // Step 2 ‑ Prevent duplicate drafts while wallet is still editing
    const existingDraft = await this.proposalRepository.findDraftByCreator(
      input.creatorWallet
    );
    if (existingDraft) {
      return left(
        new DuplicateDraftError(existingDraft.id, input.creatorWallet)
      );
    }

    // Step 3 ‑ Build Proposal aggregate
    const aggregateId = uuid();
    const now = Date.now();
    const domainProposal = Proposal.create({
      id: aggregateId,
      creator: input.creatorWallet,
      title: input.title,
      description: input.description,
      actions: input.actions,
      startBlock:
        input.startBlock ?? (await this.contractGateway.getNextBlockNumber()),
      endBlock:
        input.endBlock ??
        (await this.contractGateway.getNextBlockNumber()) + 46080 /* ~1 week */,
      createdAt: now,
      updatedAt: now,
      state: 'PENDING',
    });

    // Step 4 ‑ Persist in write model before we touch the chain
    const writeModel: ProposalWriteModel = {
      ...domainProposal.snapshot(),
    };
    await this.proposalRepository.insert(writeModel);

    // Step 5 – Interact with blockchain
    let onChainProposalId: OnChainProposalId;
    try {
      onChainProposalId = await this.contractGateway.createOnChainProposal(
        domainProposal
      );
    } catch (err) {
      // Rollback DB insert if on-chain tx fails
      await this.proposalRepository.delete(writeModel.id);
      return left(new BlockchainTxFailedError(err));
    }

    // Step 6 – Finalise aggregate & persist state
    domainProposal.markCreated(onChainProposalId);
    await this.proposalRepository.update({
      ...domainProposal.snapshot(),
    });

    // Step 7 – Emit immutable domain event
    await this.emitDomainEvent(
      new ProposalCreatedDomainEvent({
        aggregateId,
        onChainProposalId,
        occurredAt: new Date(),
      })
    );

    // Return DTO to caller
    return right({ proposalId: aggregateId, onChainProposalId });
  }

  private async emitDomainEvent(event: DomainEvent): Promise<void> {
    try {
      await this.eventBus.publish(event);
    } catch (err) {
      /* eslint-disable-next-line no-console */
      console.error('Failed to publish ProposalCreatedDomainEvent', err);
      // Non-blocking: do NOT bubble error up to caller; proposal is created
    }
  }
}
```