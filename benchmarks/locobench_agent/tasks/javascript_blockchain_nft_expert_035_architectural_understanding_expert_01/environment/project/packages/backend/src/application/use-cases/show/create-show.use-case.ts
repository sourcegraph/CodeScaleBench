```typescript
/****************************************************************************************
 * File:        packages/backend/src/application/use-cases/show/create-show.use-case.ts *
 * Project:     StellarStage Carnival                                                   *
 * Description: Orchestrates the creation of a new Show and its corresponding NFT pass  *
 *              collection following Clean Architecture guidelines.                     *
 ****************************************************************************************/

import { v4 as uuidv4 } from 'uuid';
import { differenceInMinutes, isAfter } from 'date-fns';

//////////////////////////////////////////////////////////////////////////////////////////
// Domain & Port Imports – kept minimal here; in the real repo they live in /domain/... //
//////////////////////////////////////////////////////////////////////////////////////////

/**
 * Represents a concert or event inside the StellarStage Carnival universe.
 * Real implementation is richer (state-machine, acts, loot tables, etc.).
 */
export interface ShowProps {
  id: string;
  title: string;
  slug: string;
  description?: string;
  startsAt: Date;
  endsAt: Date;
  performerIds: string[];
  metadataUri: string;
  contractAddress?: string; // set after NFT collection is minted
  createdAt: Date;
  updatedAt: Date;
}

export class Show {
  private props: ShowProps;

  private constructor(props: ShowProps) {
    this.props = props;
  }

  static create(props: Omit<ShowProps, 'createdAt' | 'updatedAt'>): Show {
    const now = new Date();
    return new Show({ ...props, createdAt: now, updatedAt: now });
  }

  updateContractAddress(address: string): void {
    this.props.contractAddress = address;
    this.props.updatedAt = new Date();
  }

  toPrimitive(): ShowProps {
    return { ...this.props };
  }
}

/**
 * Persistence port for Shows.
 */
export interface IShowRepository {
  findBySlug(slug: string): Promise<Show | null>;
  save(show: Show): Promise<void>;
  update(show: Show): Promise<void>;
}

/**
 * Event bus abstraction; implementations: RabbitMQ, NATS, in-process, etc.
 */
export interface IEventBus {
  publish<T extends DomainEvent>(event: T): Promise<void>;
}

/**
 * Base interface for domain events.
 */
export interface DomainEvent {
  readonly name: string;
  readonly occurredOn: Date;
  readonly payload: unknown;
}

/**
 * NFT minter port; hides smart-contract deployments, proxy patterns, etc.
 */
export interface INFTMinter {
  /**
   * Creates an ERC-721/1155 proxy collection for the show’s passes.
   * Returns the on-chain contract address.
   */
  mintShowPassCollection(args: {
    showId: string;
    name: string;
    symbol: string;
    metadataUri: string;
  }): Promise<string>;
}

/**
 * Logger abstraction. Could be Winston, Pino, or a custom adapter.
 */
export interface ILogger {
  debug(message: string, meta?: unknown): void;
  info(message: string, meta?: unknown): void;
  warn(message: string, meta?: unknown): void;
  error(message: string, meta?: unknown): void;
}

/**
 * Functional Result/Either helpers for consistent error handling.
 */
export type Result<T, E = Error> = Success<T> | Failure<E>;

export class Success<T> {
  readonly isSuccess = true as const;
  readonly isFailure = false as const;
  constructor(public readonly value: T) {}
}

export class Failure<E extends Error> {
  readonly isSuccess = false as const;
  readonly isFailure = true as const;
  constructor(public readonly error: E) {}
}

export const ok = <T>(value: T): Success<T> => new Success(value);
export const err = <E extends Error>(error: E): Failure<E> => new Failure(error);

//////////////////////////////////////////////////////////////////////////////////////////
// Use-Case Command & Response DTOs                                                     //
//////////////////////////////////////////////////////////////////////////////////////////

export interface CreateShowCommand {
  title: string;
  slug: string;
  description?: string;
  startsAt: Date | string;
  endsAt: Date | string;
  performerIds: string[];
  metadataUri: string; // IPFS CID or HTTP URL pointing to off-chain JSON
}

export interface ShowDTO {
  id: string;
  slug: string;
  title: string;
  startsAt: string;
  endsAt: string;
  performerIds: string[];
  metadataUri: string;
  contractAddress: string;
}

//////////////////////////////////////////////////////////////////////////////////////////
// Domain Errors                                                                        //
//////////////////////////////////////////////////////////////////////////////////////////

export class ValidationError extends Error {}
export class DuplicateSlugError extends Error {}
export class NFTMintingError extends Error {}
export class PersistenceError extends Error {}

//////////////////////////////////////////////////////////////////////////////////////////
// Event Definitions                                                                     //
//////////////////////////////////////////////////////////////////////////////////////////

export class ShowCreatedEvent implements DomainEvent {
  readonly name = 'show.created';
  readonly occurredOn = new Date();
  constructor(public readonly payload: ShowDTO) {}
}

//////////////////////////////////////////////////////////////////////////////////////////
// CreateShowUseCase                                                                     //
//////////////////////////////////////////////////////////////////////////////////////////

export class CreateShowUseCase {
  constructor(
    private readonly showRepo: IShowRepository,
    private readonly nftMinter: INFTMinter,
    private readonly eventBus: IEventBus,
    private readonly logger: ILogger
  ) {}

  /**
   * Executes the business flow:
   * 1. Validate input & business rules.
   * 2. Persist initial Show record.
   * 3. Deploy NFT collection contract.
   * 4. Update Show with contract address.
   * 5. Publish ShowCreated event.
   */
  public async execute(
    command: CreateShowCommand
  ): Promise<Result<ShowDTO, ValidationError | DuplicateSlugError | NFTMintingError | PersistenceError>> {
    try {
      // 1. Guard Clauses & Validation --------------------------------------------------
      const validationErr = this.validate(command);
      if (validationErr) {
        return err(validationErr);
      }

      // Ensure slug is unique
      const existing = await this.showRepo.findBySlug(command.slug);
      if (existing) {
        return err(new DuplicateSlugError(`Slug "${command.slug}" is already taken.`));
      }

      // 2. Instantiate Domain Entity ---------------------------------------------------
      const id = uuidv4();
      const show = Show.create({
        id,
        title: command.title,
        slug: command.slug,
        description: command.description,
        startsAt: new Date(command.startsAt),
        endsAt: new Date(command.endsAt),
        performerIds: command.performerIds,
        metadataUri: command.metadataUri,
        contractAddress: undefined,
      });

      // 3. Persist initial show (without contractAddress) ------------------------------
      await this.showRepo.save(show);

      // 4. Mint NFT collection ---------------------------------------------------------
      let contractAddress: string;
      try {
        contractAddress = await this.nftMinter.mintShowPassCollection({
          showId: id,
          name: command.title,
          symbol: this.buildSymbol(command.title),
          metadataUri: command.metadataUri,
        });
      } catch (e: unknown) {
        this.logger.error('Failed to mint NFT collection', { showId: id, error: e });
        // Attempt to roll back (idempotent delete could be implemented in repo)
        throw new NFTMintingError('Failed to create NFT collection for show.');
      }

      // 5. Update Show with contract address ------------------------------------------
      show.updateContractAddress(contractAddress);
      await this.showRepo.update(show);

      // 6. Build DTO & publish domain event -------------------------------------------
      const dto = this.toDTO(show);

      await this.eventBus.publish(new ShowCreatedEvent(dto));

      this.logger.info(`Show "${dto.title}" created`, { id: dto.id, slug: dto.slug });

      return ok(dto);
    } catch (e: unknown) {
      this.logger.error('Unexpected error while creating show', { error: e });
      return err(
        e instanceof ValidationError ||
        e instanceof DuplicateSlugError ||
        e instanceof NFTMintingError
          ? e
          : new PersistenceError('Unexpected failure during show creation.')
      );
    }
  }

  //////////////////////////////////////////////////////////////////////////////////////
  // Helpers                                                                           //
  //////////////////////////////////////////////////////////////////////////////////////

  /**
   * Business-rule validation.
   */
  private validate(cmd: CreateShowCommand): ValidationError | null {
    if (!cmd.title?.trim()) {
      return new ValidationError('Title is required.');
    }

    if (!cmd.slug?.trim()) {
      return new ValidationError('Slug is required.');
    }

    const startsAt = new Date(cmd.startsAt);
    const endsAt = new Date(cmd.endsAt);

    if (isAfter(startsAt, endsAt)) {
      return new ValidationError('Start date must be before end date.');
    }

    if (differenceInMinutes(endsAt, startsAt) < 30) {
      return new ValidationError('Show must last at least 30 minutes.');
    }

    if (!Array.isArray(cmd.performerIds) || cmd.performerIds.length === 0) {
      return new ValidationError('At least one performer is required.');
    }

    if (!cmd.metadataUri?.trim()) {
      return new ValidationError('metadataUri is required.');
    }

    return null;
  }

  /**
   * Generates an uppercase ticker symbol from the show title.
   * E.g. "Summer Jam" -> "SJAM".
   */
  private buildSymbol(title: string): string {
    return title
      .split(/\s+/)
      .map((word) => word[0])
      .join('')
      .toUpperCase()
      .slice(0, 4); // ERC-20 style limit
  }

  /**
   * Converts domain entity to DTO for external layers.
   */
  private toDTO(show: Show): ShowDTO {
    const primitive = show.toPrimitive();
    return {
      id: primitive.id,
      slug: primitive.slug,
      title: primitive.title,
      startsAt: primitive.startsAt.toISOString(),
      endsAt: primitive.endsAt.toISOString(),
      performerIds: primitive.performerIds,
      metadataUri: primitive.metadataUri,
      contractAddress: primitive.contractAddress!,
    };
  }
}
```