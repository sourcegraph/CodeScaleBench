```typescript
/* eslint-disable @typescript-eslint/no-unsafe-argument */
/* eslint-disable @typescript-eslint/no-unsafe-assignment */
/* eslint-disable @typescript-eslint/no-unsafe-member-access */
/* eslint-disable @typescript-eslint/no-unsafe-return */
/* eslint-disable @typescript-eslint/explicit-module-boundary-types */

/**
 * GraphQL resolver map for the `Pass` aggregate-root.
 *
 * Layer:     Presentation › GraphQL
 * Platform:  Apollo Server
 * Pattern:   Thin Resolver → Use-Case orchestration (Clean Architecture)
 *
 * Every resolver *only* performs:
 *   1. Minimal argument validation / coercion
 *   2. Delegation to a dedicated application use-case
 *   3. Mapping of domain models → DTOs
 *   4. Error translation into Apollo-compliant errors
 */

import { IResolvers } from '@graphql-tools/utils';
import { PubSub } from 'graphql-subscriptions';
import {
  ApolloError,
  AuthenticationError,
  ForbiddenError,
  UserInputError,
} from 'apollo-server-errors';

import { Logger } from '../../../shared/logger';
import { container } from '../../../infrastructure/ioc/container';

import {
  MintShowPassUseCase,
  StakePassUseCase,
  TransferPassUseCase,
  GetPassByIdUseCase,
  ListPassesUseCase,
} from '../../../application/use-cases/pass';
import { PassDTOMapper } from '../mappers/pass-dto.mapper';
import { DomainError } from '../../../domain/errors/domain-error';

/* -------------------------------------------------------------------------- */
/*                                Pub/Sub                                     */
/* -------------------------------------------------------------------------- */

const pubSub = new PubSub();

export const PASS_MINTED_EVENT = 'PASS_MINTED_EVENT';
export const PASS_UPDATED_EVENT = 'PASS_UPDATED_EVENT';
export const PASS_TRANSFERRED_EVENT = 'PASS_TRANSFERRED_EVENT';
export const PASS_STAKED_EVENT = 'PASS_STAKED_EVENT';

/* -------------------------------------------------------------------------- */
/*                              Helper Functions                              */
/* -------------------------------------------------------------------------- */

function mapDomainError(err: unknown): ApolloError {
  if (err instanceof DomainError) {
    // Domain errors are expected business-level errors → 4xx
    return new UserInputError(err.message, { code: err.code });
  }

  if (err instanceof AuthenticationError || err instanceof ForbiddenError) {
    return err;
  }

  // Anything else is an unexpected, server-side error → 5xx
  Logger.error({ msg: 'Unexpected resolver error', err });
  return new ApolloError('Internal server error');
}

interface GraphQLContext {
  user?: { id: string };
}

/* -------------------------------------------------------------------------- */
/*                                Resolvers                                   */
/* -------------------------------------------------------------------------- */

export const passResolver: IResolvers<unknown, GraphQLContext> = {
  /* ============================= Root Queries ============================= */

  Query: {
    /**
     * Pass(id): Fetch a single Pass by its unique ID.
     */
    async pass(_parent, { id }: { id: string }, _ctx) {
      try {
        const useCase = container.resolve<GetPassByIdUseCase>('GetPassByIdUseCase');
        const pass = await useCase.execute({ id });
        return PassDTOMapper.toDTO(pass);
      } catch (err) {
        throw mapDomainError(err);
      }
    },

    /**
     * passes(): List all passes with optional pagination / filtering.
     */
    async passes(
      _parent,
      args: { first?: number; after?: string; owner?: string },
      _ctx,
    ) {
      try {
        const useCase = container.resolve<ListPassesUseCase>('ListPassesUseCase');
        const result = await useCase.execute({
          first: args.first,
          after: args.after,
          owner: args.owner,
        });

        return {
          edges: result.items.map((p) => ({
            cursor: p.id,
            node: PassDTOMapper.toDTO(p),
          })),
          pageInfo: {
            hasNextPage: result.hasNextPage,
            endCursor: result.endCursor,
          },
          totalCount: result.totalCount,
        };
      } catch (err) {
        throw mapDomainError(err);
      }
    },
  },

  /* ============================ Root Mutations ============================ */

  Mutation: {
    /**
     * mintPass(): Mints a new show pass NFT.
     */
    async mintPass(
      _parent,
      args: {
        input: {
          showId: string;
          seat: string;
          tier: 'STANDARD' | 'VIP' | 'ULTRA';
        };
      },
      ctx,
    ) {
      if (!ctx.user) {
        throw new AuthenticationError('Not authenticated');
      }

      try {
        const useCase = container.resolve<MintShowPassUseCase>('MintShowPassUseCase');
        const pass = await useCase.execute({
          ownerId: ctx.user.id,
          showId: args.input.showId,
          seat: args.input.seat,
          tier: args.input.tier,
        });

        const dto = PassDTOMapper.toDTO(pass);
        void pubSub.publish(PASS_MINTED_EVENT, { passMinted: dto });
        return dto;
      } catch (err) {
        throw mapDomainError(err);
      }
    },

    /**
     * stakePass(): Stake a pass to earn governance rights / rewards.
     */
    async stakePass(
      _parent,
      args: { passId: string; amount: string },
      ctx,
    ) {
      if (!ctx.user) {
        throw new AuthenticationError('Not authenticated');
      }

      try {
        const useCase = container.resolve<StakePassUseCase>('StakePassUseCase');
        const pass = await useCase.execute({
          passId: args.passId,
          stakerId: ctx.user.id,
          amount: BigInt(args.amount),
        });

        const dto = PassDTOMapper.toDTO(pass);
        void pubSub.publish(PASS_STAKED_EVENT, { passStaked: dto });
        return dto;
      } catch (err) {
        throw mapDomainError(err);
      }
    },

    /**
     * transferPass(): Transfer ownership to another wallet.
     */
    async transferPass(
      _parent,
      args: { passId: string; to: string },
      ctx,
    ) {
      if (!ctx.user) {
        throw new AuthenticationError('Not authenticated');
      }

      try {
        const useCase = container.resolve<TransferPassUseCase>('TransferPassUseCase');
        const pass = await useCase.execute({
          passId: args.passId,
          fromOwnerId: ctx.user.id,
          toOwnerId: args.to,
        });

        const dto = PassDTOMapper.toDTO(pass);
        void pubSub.publish(PASS_TRANSFERRED_EVENT, { passTransferred: dto });
        return dto;
      } catch (err) {
        throw mapDomainError(err);
      }
    },
  },

  /* ========================== Root Subscriptions ========================= */

  Subscription: {
    passMinted: {
      subscribe: () => pubSub.asyncIterator(PASS_MINTED_EVENT),
    },
    passStaked: {
      subscribe: () => pubSub.asyncIterator(PASS_STAKED_EVENT),
    },
    passTransferred: {
      subscribe: () => pubSub.asyncIterator(PASS_TRANSFERRED_EVENT),
    },
  },

  /* ============================= Field-Level ============================== */

  /**
   * Field-level resolvers for `Pass` type.
   * The domain object already contains everything we need, but adding them
   * here allows us to evolve without touching the DB / domain.
   */
  Pass: {
    id: (pass) => pass.id,
    show: (pass, _args, _ctx) => ({
      __typename: 'Show',
      id: pass.showId,
    }),
    owner: (pass, _args, _ctx) => ({
      __typename: 'User',
      id: pass.ownerId,
    }),
    currentLevel: (pass) => pass.level,
    metadataUri: (pass) => pass.metadataUri,
    staked: (pass) => String(pass.staked),
  },
};

/* -------------------------------------------------------------------------- */
/*                             Module Augmentation                            */
/* -------------------------------------------------------------------------- */

export default passResolver;
```
