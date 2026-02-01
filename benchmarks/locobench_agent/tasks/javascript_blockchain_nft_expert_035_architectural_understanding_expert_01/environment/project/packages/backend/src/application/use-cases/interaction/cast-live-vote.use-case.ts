```typescript
/***************************************************************************************************
 *  File: cast-live-vote.use-case.ts
 *  Project: StellarStage Carnival – Interactive NFT Showrunner
 *  Layer:  Application / Use-Cases
 *
 *  Description:
 *  ------------------------------------------------------------------------------
 *  Orchestrates the business flow for casting a live vote during an active show.
 *  The use-case validates the fan’s show-pass, ensures the poll is open, persists
 *  the vote, emits a domain event for real-time updates and finally records the
 *  vote on-chain through the configured smart-contract gateway.
 *
 *  Clean-Architecture Ports Utilised:
 *  ───────────────────────────────────────────────────────────────────────────────
 *   • LivePollRepositoryPort        – CRUD access to poll aggregates
 *   • PassRepositoryPort            – Read-only access to staked show-passes
 *   • BlockchainVoteGatewayPort     – Records vote on chain (EVM or L2 rollup)
 *   • DomainEventBusPort            – Publishes VoteCastDomainEvent
 *
 *  Notes:
 *  ------
 *   • The code purposefully keeps all external dependencies behind ports/
 *     abstractions, ensuring the core logic remains testable and framework-agnostic.
 ***************************************************************************************************/

import { v4 as uuid } from 'uuid';
import { inject, injectable } from 'inversify';

import { TYPES } from '../../ioc/types';
import {
  LivePollRepositoryPort,
  PassRepositoryPort,
  BlockchainVoteGatewayPort,
  DomainEventBusPort,
} from '../../ports';

import {
  CastLiveVoteCommand,
  CastLiveVoteResult,
  VoteAlreadyCastError,
  PollClosedError,
  InvalidPassError,
  LivePollNotFoundError,
} from './dtos';

import {
  Vote,
  VoteChoice,
  VoteId,
} from '../../../domain/entities/vote';

import { VoteCastDomainEvent } from '../../../domain/events/vote-cast.event';

/***************************************************************************************************
 * CastLiveVoteUseCase
 ***************************************************************************************************/
@injectable()
export class CastLiveVoteUseCase {
  constructor(
    @inject(TYPES.LivePollRepositoryPort)
    private readonly livePollRepo: LivePollRepositoryPort,

    @inject(TYPES.PassRepositoryPort)
    private readonly passRepo: PassRepositoryPort,

    @inject(TYPES.BlockchainVoteGatewayPort)
    private readonly blockchainGateway: BlockchainVoteGatewayPort,

    @inject(TYPES.DomainEventBusPort)
    private readonly eventBus: DomainEventBusPort,
  ) {}

  /**
   * Execute the use-case
   * ---------------------------------------------------------
   * @throws LivePollNotFoundError
   * @throws PollClosedError
   * @throws InvalidPassError
   * @throws VoteAlreadyCastError
   */
  public async execute(
    command: CastLiveVoteCommand,
  ): Promise<CastLiveVoteResult> {
    const {
      pollId,
      choiceId,
      passTokenId,
      voterWallet,
      blockNumberHint,
    } = command;

    /* -----------------------------------------------------------------------
     * Step 1: Load & validate domain aggregates
     * --------------------------------------------------------------------- */

    // 1a. Live poll must exist
    const poll = await this.livePollRepo.findById(pollId);
    if (!poll) {
      throw new LivePollNotFoundError(pollId);
    }

    // 1b. Poll must be open for votes
    if (!poll.isOpen()) {
      throw new PollClosedError(pollId);
    }

    // 1c. Validate the fan’s show-pass
    const pass = await this.passRepo.findStakedByTokenId(passTokenId);
    if (!pass || pass.owner.toLowerCase() !== voterWallet.toLowerCase()) {
      throw new InvalidPassError(passTokenId);
    }

    // 1d. Enforce “one vote per wallet” rule
    if (poll.hasVoted(voterWallet)) {
      throw new VoteAlreadyCastError(voterWallet, pollId);
    }

    /* -----------------------------------------------------------------------
     * Step 2: Create domain entity & persist
     * --------------------------------------------------------------------- */

    const voteId: VoteId = uuid();
    const choice = poll.getChoice(choiceId);

    if (!choice) {
      throw new Error(`Choice ${choiceId} not found in poll ${pollId}.`); // Should never happen
    }

    const vote = new Vote({
      id: voteId,
      pollId,
      voterWallet,
      passTokenId,
      choice: new VoteChoice(choice.id, choice.label),
      timestamp: Date.now(),
    });

    // Mutate poll aggregate
    poll.registerVote(vote);

    // Persist within a transaction (if underlying adapter supports it)
    await this.livePollRepo.save(poll);

    /* -----------------------------------------------------------------------
     * Step 3: Emit domain event for real-time front-end & micro-services
     * --------------------------------------------------------------------- */
    const domainEvent = new VoteCastDomainEvent({
      voteId,
      pollId,
      voterWallet,
      choiceId,
      emittedAt: new Date(),
    });

    await this.eventBus.publish(domainEvent);

    /* -----------------------------------------------------------------------
     * Step 4: Record vote on-chain (fire-and-forget / transactional-outbox)
     * --------------------------------------------------------------------- */
    let txHash: string | undefined;

    try {
      txHash = await this.blockchainGateway.castVote({
        pollId,
        choiceId,
        voterWallet,
        passTokenId,
        blockNumberHint,
      });
    } catch (err) {
      /*  Non-fatal: The optimistic UI is already updated.  We log and push the
          failed message to an outbox for retry to guarantee eventual consistency.
      */
      console.error(
        `[CastLiveVoteUseCase] Failed to write on-chain vote for poll ${pollId}.`,
        err,
      );
      await this.blockchainGateway.enqueueRetry({
        pollId,
        choiceId,
        voterWallet,
        passTokenId,
        blockNumberHint,
      });
    }

    /* -----------------------------------------------------------------------
     * Step 5: Return use-case result
     * --------------------------------------------------------------------- */
    const result: CastLiveVoteResult = {
      voteId,
      pollId,
      choiceId,
      voterWallet,
      txHash, // may be undefined when blockchain write queued
    };

    return result;
  }
}
```

