```typescript
/**
 * StellarStage Carnival – GraphQL resolver for `Show` aggregate.
 *
 * This resolver is the gateway between the GraphQL layer and the
 * show-related application use-cases that live inside the “services”
 * (or “application”) layer.  It is intentionally kept *thin*:
 * –  Validation & authorisation
 * –  Mapping of GraphQL arguments → DTOs expected by the use-cases
 * –  Publishing of pub/sub events for subscribers
 *
 * Business logic MUST stay inside the use-cases so we do not violate
 * Clean Architecture boundaries.
 */

import { ApolloError, ForbiddenError, UserInputError } from 'apollo-server-express';
import { PubSubEngine, withFilter } from 'graphql-subscriptions';
import { Container } from 'typedi';

import { Logger } from '../../../infrastructure/logging/Logger';
import { GraphQLContext } from '../types/GraphQLContext';

import {
  CreateShowCommand,
  UpdateShowCommand,
  OpenShowCommand,
  CloseShowCommand,
  GetShowByIdQuery,
  ListShowsQuery,
} from '../../../../application/usecases/show';

import { ListActsByShowIdUseCase } from '../../../../application/usecases/act';
import { ListPassesByShowIdUseCase } from '../../../../application/usecases/pass';
import { GetRemainingSeatsUseCase } from '../../../../application/usecases/seating';

import { Show } from '../../../../domain/entities/Show';
import { Act } from '../../../../domain/entities/Act';

/* -------------------------------------------------------------------------- */
/*                                  Typings                                   */
/* -------------------------------------------------------------------------- */

interface CreateShowInput {
  title: string;
  description?: string;
  startAt: string;        // ISO-8601
  endAt: string;          // ISO-8601
  performerAddress: string;
}

interface UpdateShowInput {
  id: string;
  title?: string;
  description?: string;
  startAt?: string;
  endAt?: string;
}

/* -------------------------------------------------------------------------- */
/*                               Pub/Sub events                               */
/* -------------------------------------------------------------------------- */

const SHOW_UPDATED = 'SHOW_UPDATED'; // broadcasted on create / update / state-change

/* -------------------------------------------------------------------------- */
/*                                   Query                                    */
/* -------------------------------------------------------------------------- */

async function show(
  _: unknown,
  { id }: { id: string },
  _ctx: GraphQLContext,
): Promise<Show> {
  const logger = Container.get(Logger);

  try {
    const query = Container.get(GetShowByIdQuery);
    return await query.execute({ id });
  } catch (err) {
    logger.error(`Unable to fetch show ${id}`, err);
    throw new ApolloError('Unable to fetch show');
  }
}

async function shows(
  _: unknown,
  args: { performerAddress?: string; upcomingOnly?: boolean },
  _ctx: GraphQLContext,
): Promise<Show[]> {
  const logger = Container.get(Logger);

  try {
    const list = Container.get(ListShowsQuery);
    return await list.execute({
      performerAddress: args.performerAddress,
      upcomingOnly: args.upcomingOnly,
    });
  } catch (err) {
    logger.error('Unable to list shows', err);
    throw new ApolloError('Unable to list shows');
  }
}

/* -------------------------------------------------------------------------- */
/*                                 Mutations                                  */
/* -------------------------------------------------------------------------- */

async function createShow(
  _: unknown,
  { input }: { input: CreateShowInput },
  { user, pubSub }: GraphQLContext & { pubSub: PubSubEngine },
): Promise<Show> {
  const logger = Container.get(Logger);

  if (!user?.isCreator) {
    throw new ForbiddenError('Only verified creators may create shows.');
  }

  try {
    const command = Container.get(CreateShowCommand);
    const show = await command.execute({ ...input, creatorId: user.id });

    await pubSub.publish(SHOW_UPDATED, { showUpdated: show });
    return show;
  } catch (err) {
    logger.error('Unable to create show', { err, input });
    throw new ApolloError('Unable to create show');
  }
}

async function updateShow(
  _: unknown,
  { input }: { input: UpdateShowInput },
  { user, pubSub }: GraphQLContext & { pubSub: PubSubEngine },
): Promise<Show> {
  const logger = Container.get(Logger);

  const getShow = Container.get(GetShowByIdQuery);
  const existing = await getShow.execute({ id: input.id });

  if (existing.creatorId !== user?.id) {
    throw new ForbiddenError('You are not authorised to edit this show.');
  }

  try {
    const command = Container.get(UpdateShowCommand);
    const show = await command.execute(input);

    await pubSub.publish(SHOW_UPDATED, { showUpdated: show });
    return show;
  } catch (err) {
    logger.error('Unable to update show', { err, input });
    throw new ApolloError('Unable to update show');
  }
}

async function openShow(
  _: unknown,
  { id }: { id: string },
  { user, pubSub }: GraphQLContext & { pubSub: PubSubEngine },
): Promise<Show> {
  const logger = Container.get(Logger);

  const getShow = Container.get(GetShowByIdQuery);
  const show = await getShow.execute({ id });

  if (show.creatorId !== user?.id) {
    throw new ForbiddenError('You are not authorised to open this show.');
  }

  if (show.state !== 'SCHEDULED') {
    throw new UserInputError('Only “SCHEDULED” shows may be opened.');
  }

  try {
    const command = Container.get(OpenShowCommand);
    const opened = await command.execute({ id });

    await pubSub.publish(SHOW_UPDATED, { showUpdated: opened });
    return opened;
  } catch (err) {
    logger.error('Unable to open show', { err, id });
    throw new ApolloError('Unable to open show');
  }
}

async function closeShow(
  _: unknown,
  { id }: { id: string },
  { user, pubSub }: GraphQLContext & { pubSub: PubSubEngine },
): Promise<Show> {
  const logger = Container.get(Logger);

  const getShow = Container.get(GetShowByIdQuery);
  const show = await getShow.execute({ id });

  if (show.creatorId !== user?.id) {
    throw new ForbiddenError('You are not authorised to close this show.');
  }

  try {
    const command = Container.get(CloseShowCommand);
    const closed = await command.execute({ id });

    await pubSub.publish(SHOW_UPDATED, { showUpdated: closed });
    return closed;
  } catch (err) {
    logger.error('Unable to close show', { err, id });
    throw new ApolloError('Unable to close show');
  }
}

/* -------------------------------------------------------------------------- */
/*                                Subscription                                */
/* -------------------------------------------------------------------------- */

const showUpdated = {
  subscribe: withFilter(
    (_: unknown, __: unknown, { pubSub }: GraphQLContext & { pubSub: PubSubEngine }) =>
      pubSub.asyncIterator([SHOW_UPDATED]),
    (payload: { showUpdated: Show }, variables: { id?: string }) =>
      // If the client provided an `id` variable, only push updates
      // matching that show; otherwise push all.
      variables.id ? payload.showUpdated.id === variables.id : true,
  ),
};

/* -------------------------------------------------------------------------- */
/*                               Field Resolvers                              */
/* -------------------------------------------------------------------------- */

async function acts(parent: Show): Promise<Act[]> {
  const listActs = Container.get(ListActsByShowIdUseCase);
  return listActs.execute({ showId: parent.id });
}

async function passes(parent: Show) {
  const listPasses = Container.get(ListPassesByShowIdUseCase);
  return listPasses.execute({ showId: parent.id });
}

async function remainingSeats(parent: Show) {
  const useCase = Container.get(GetRemainingSeatsUseCase);
  return useCase.execute({ showId: parent.id });
}

/* -------------------------------------------------------------------------- */
/*                                Export blob                                 */
/* -------------------------------------------------------------------------- */

export const showResolver = {
  Query: {
    show,
    shows,
  },
  Mutation: {
    createShow,
    updateShow,
    openShow,
    closeShow,
  },
  Subscription: {
    showUpdated,
  },
  Show: {
    acts,
    passes,
    remainingSeats,
  },
};

export default showResolver;
```