```typescript
/**********************************************************************************************
 * File: packages/backend/src/presentation/graphql/resolvers/governance.resolver.ts
 * Project: StellarStage Carnival – Interactive NFT Showrunner
 *
 * Description:
 *  GraphQL resolver map for all governance-related operations (queries, mutations, subscriptions)
 *  exposed to the front-end. This layer is intentionally thin: it performs argument validation,
 *  authentication / authorization checks and forwards the call to the correct use-case service
 *  which lives in the application layer. All dependencies are injected through an IoC container
 *  (tsyringe) attached to the GraphQL context.
 *
 *  Clean-Architecture boundaries:
 *    presentation (this file)  →  use-case services  →  domain entities / ports
 *
 *  The resolver demonstrates:
 *    • Proper TypeScript typings
 *    • Robust error handling (Apollo-compliant)
 *    • Logging
 *    • Real-time vote broadcasts via PubSub (Observer/Event-Driven pattern)
 *********************************************************************************************/

import { ApolloError, AuthenticationError, ForbiddenError } from 'apollo-server-errors';
import { IResolvers } from '@graphql-tools/utils';
import { PubSub } from 'graphql-subscriptions';
import { container, DependencyContainer } from 'tsyringe';

import { Logger } from '../../../infrastructure/logging/logger';
import {
  CastLiveVoteUseCase,
  CreateProposalUseCase,
  DelegateVotesUseCase,
  GetProposalUseCase,
  ListProposalsUseCase,
  StakePassUseCase,
  UnstakePassUseCase,
} from '../../../application/use-cases/governance';
import {
  CastVoteInput,
  CreateProposalInput,
  DelegateVotesInput,
  StakePassInput,
  UnstakePassInput,
} from '../types/governance.inputs';
import { GraphQLContext } from '../types/graphql-context';
import { VoteDTO, ProposalDTO } from '../types/governance.dtos';

/**
 * EVENTS
 * Keys used by the PubSub engine so that subscriptions & mutations communicate
 */
export const GOVERNANCE_EVENTS = {
  VOTE_CASTED: 'GOVERNANCE.VOTE_CASTED',
  PROPOSAL_CREATED: 'GOVERNANCE.PROPOSAL_CREATED',
} as const;

/**
 * Utility wrapper so every resolver can execute a use-case, catch errors,
 * log them once and re-throw a properly formatted Apollo error.
 */
const executeSafely =
  <I, O>(uc: (input: I) => Promise<O>, container: DependencyContainer, log: Logger) =>
  async (input: I): Promise<O> => {
    try {
      return await uc(input);
    } catch (err: any) {
      log.error({ err, layer: 'presentation.graphql', input }, 'Unhandled exception');
      // Default to `INTERNAL_SERVER_ERROR` if error is not already an ApolloError
      if (err instanceof ApolloError) throw err;
      throw new ApolloError('Unexpected error while processing request');
    }
  };

/**
 * Governance Resolver Map
 *  NOTE: All functions are bound at runtime; they access services through the context’s container
 */
export const governanceResolver: IResolvers<any, GraphQLContext> = {
  /********************************
   * QUERIES
   *******************************/
  Query: {
    // ---------------------------------------------------------
    // query proposal(id: ID!): Proposal!
    // ---------------------------------------------------------
    proposal: async (
      _,
      { id }: { id: string },
      { injector, logger }: GraphQLContext
    ): Promise<ProposalDTO> => {
      const getProposal = injector.resolve<GetProposalUseCase>('GetProposalUseCase');
      const safeExecute = executeSafely(getProposal.execute.bind(getProposal), injector, logger);
      return safeExecute({ proposalId: id });
    },

    // ---------------------------------------------------------
    // query proposals(limit: Int, cursor: ID): ProposalConnection!
    // ---------------------------------------------------------
    proposals: async (
      _,
      args: { limit?: number; cursor?: string },
      { injector, logger }: GraphQLContext
    ) => {
      const listProposals = injector.resolve<ListProposalsUseCase>('ListProposalsUseCase');
      const safeExecute = executeSafely(listProposals.execute.bind(listProposals), injector, logger);
      return safeExecute({ ...args });
    },
  },

  /********************************
   * MUTATIONS
   *******************************/
  Mutation: {
    // ---------------------------------------------------------
    // mutation createProposal(input: CreateProposalInput!): Proposal!
    // ---------------------------------------------------------
    createProposal: async (
      _,
      { input }: { input: CreateProposalInput },
      { injector, user, logger, pubsub }: GraphQLContext
    ): Promise<ProposalDTO> => {
      if (!user) throw new AuthenticationError('You must be signed in');

      const createProposal = injector.resolve<CreateProposalUseCase>('CreateProposalUseCase');
      const safeExecute = executeSafely(createProposal.execute.bind(createProposal), injector, logger);
      const proposal = await safeExecute({ ...input, proposerWallet: user.walletAddress });

      await pubsub.publish(GOVERNANCE_EVENTS.PROPOSAL_CREATED, { proposalCreated: proposal });

      return proposal;
    },

    // ---------------------------------------------------------
    // mutation castVote(input: CastVoteInput!): Vote!
    // ---------------------------------------------------------
    castVote: async (
      _,
      { input }: { input: CastVoteInput },
      { injector, user, logger, pubsub }: GraphQLContext
    ): Promise<VoteDTO> => {
      if (!user) throw new AuthenticationError('You must be signed in');

      const castVote = injector.resolve<CastLiveVoteUseCase>('CastLiveVoteUseCase');
      const safeExecute = executeSafely(castVote.execute.bind(castVote), injector, logger);
      const vote = await safeExecute({
        ...input,
        voterWallet: user.walletAddress,
      });

      // Broadcast to subscribers
      await pubsub.publish(GOVERNANCE_EVENTS.VOTE_CASTED, { voteCasted: vote });

      return vote;
    },

    // ---------------------------------------------------------
    // mutation stakePass(input: StakePassInput!): StakingResult!
    // ---------------------------------------------------------
    stakePass: async (
      _,
      { input }: { input: StakePassInput },
      { injector, user, logger }: GraphQLContext
    ) => {
      if (!user) throw new AuthenticationError('You must be signed in');
      if (user.walletAddress.toLowerCase() !== input.ownerWallet.toLowerCase())
        throw new ForbiddenError('Wallet mismatch');

      const stakePass = injector.resolve<StakePassUseCase>('StakePassUseCase');
      const safeExecute = executeSafely(stakePass.execute.bind(stakePass), injector, logger);
      return safeExecute(input);
    },

    // ---------------------------------------------------------
    // mutation unstakePass(input: UnstakePassInput!): StakingResult!
    // ---------------------------------------------------------
    unstakePass: async (
      _,
      { input }: { input: UnstakePassInput },
      { injector, user, logger }: GraphQLContext
    ) => {
      if (!user) throw new AuthenticationError('You must be signed in');
      if (user.walletAddress.toLowerCase() !== input.ownerWallet.toLowerCase())
        throw new ForbiddenError('Wallet mismatch');

      const unstakePass = injector.resolve<UnstakePassUseCase>('UnstakePassUseCase');
      const safeExecute = executeSafely(unstakePass.execute.bind(unstakePass), injector, logger);
      return safeExecute(input);
    },

    // ---------------------------------------------------------
    // mutation delegateVotes(input: DelegateVotesInput!): Delegation!
    // ---------------------------------------------------------
    delegateVotes: async (
      _,
      { input }: { input: DelegateVotesInput },
      { injector, user, logger }: GraphQLContext
    ) => {
      if (!user) throw new AuthenticationError('You must be signed in');
      if (user.walletAddress.toLowerCase() !== input.delegatorWallet.toLowerCase())
        throw new ForbiddenError('Wallet mismatch');

      const delegateVotes = injector.resolve<DelegateVotesUseCase>('DelegateVotesUseCase');
      const safeExecute = executeSafely(delegateVotes.execute.bind(delegateVotes), injector, logger);
      return safeExecute(input);
    },
  },

  /********************************
   * SUBSCRIPTIONS
   *******************************/
  Subscription: {
    // ---------------------------------------------------------
    // subscription voteCasted(proposalId: ID): Vote!
    // ---------------------------------------------------------
    voteCasted: {
      subscribe: (_: unknown, args: { proposalId?: string }, { pubsub }: GraphQLContext) => {
        if (args.proposalId)
          // Filter by proposalId when provided
          return pubsub.asyncIterator(GOVERNANCE_EVENTS.VOTE_CASTED).map((payload: any) => {
            return payload.voteCasted.proposalId === args.proposalId ? payload : undefined;
          });
        return pubsub.asyncIterator(GOVERNANCE_EVENTS.VOTE_CASTED);
      },
    },

    // ---------------------------------------------------------
    // subscription proposalCreated: Proposal!
    // ---------------------------------------------------------
    proposalCreated: {
      subscribe: (_: unknown, __: unknown, { pubsub }: GraphQLContext) =>
        pubsub.asyncIterator(GOVERNANCE_EVENTS.PROPOSAL_CREATED),
    },
  },

  /********************************
   * FIELD-LEVEL RESOLVERS
   *******************************/
  Proposal: {
    // Resolve high-cost computed fields lazily
    async tally(
      parent: ProposalDTO,
      _args: unknown,
      { injector, logger }: GraphQLContext
    ): Promise<{ for: bigint; against: bigint; abstain: bigint }> {
      const getProposal = injector.resolve<GetProposalUseCase>('GetProposalUseCase');
      const safeExecute = executeSafely(getProposal.getTally.bind(getProposal), injector, logger);
      return safeExecute({ proposalId: parent.id });
    },
  },
};

/**
 * Registers the resolver with any ApolloServer builder.
 * Keep the export separate so tests can import the raw object.
 */
export default governanceResolver;

/**********************************************************************************************
 * INTERNAL MODULE AUGMENTATIONS
 * Extend AsyncIterator so that .map exists (helper from `it-map` package).
 *********************************************************************************************/

declare module 'graphql-subscriptions' {
  interface PubSub {
    asyncIterator<T>(triggers: string | string[]): AsyncIterator<T>;
  }
}
```
