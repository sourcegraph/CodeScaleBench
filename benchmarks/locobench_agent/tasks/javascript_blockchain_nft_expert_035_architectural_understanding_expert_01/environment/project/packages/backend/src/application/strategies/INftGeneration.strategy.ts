```typescript
/* --------------------------------------------------------------------------
 * StellarStage Carnival
 * File: packages/backend/src/application/strategies/INftGeneration.strategy.ts
 *
 * Contract + reference implementation for dynamic NFT generation strategies.
 * -------------------------------------------------------------------------- */

import { z } from 'zod';

import { Show } from '../../domain/entities/Show';
import { Pass } from '../../domain/entities/Pass';
import { StageSnapshot } from '../../domain/entities/StageSnapshot';
import { NFTMetadata } from '../../domain/valueObjects/NFTMetadata';
import { EvolutionResult } from '../../domain/valueObjects/EvolutionResult';

import { IIpfsUploader } from '../ports/IIpfsUploader.port';

/* -------------------------------------------------------------------------- */
/*                              Custom Error Types                            */
/* -------------------------------------------------------------------------- */

/**
 * Thrown whenever the produced metadata does not comply with the agreed-upon
 * ERC-721 / ERC-1155 JSON schema or fails extra business validations.
 */
export class InvalidMetadataError extends Error {
  public readonly issues?: unknown;

  constructor(message: string, issues?: unknown) {
    super(message);
    this.name = 'InvalidMetadataError';
    this.issues = issues;
  }
}

/* -------------------------------------------------------------------------- */
/*                         Strategy Interface Definition                      */
/* -------------------------------------------------------------------------- */

/**
 * Defines the behaviour any NFT generation algorithm must expose in order to be
 * consumed by the application layer use-cases (MintShowPass, StakePass, …).
 *
 * Different strategies may take wildly different approaches (AI-generated
 * visuals, deterministic rarity scores, oracle-based data feeds, etc.), yet
 * the rest of the system can remain unaware thanks to this contract.
 */
export interface INftGenerationStrategy {
  /**
   * Build the complete metadata object for the given Pass at the given Show
   * stage snapshot. Implementations should be side-effect free and pure; they
   * are allowed to call deterministic utilities (e.g. hashing, PRNG seeded by
   * on-chain entropy) but must avoid IO so they stay easily unit-testable.
   */
  generateMetadata(
    show: Show,
    pass: Pass,
    snapshot: StageSnapshot
  ): Promise<NFTMetadata>;

  /**
   * Turn the metadata into a canonical token URI (ipfs://, ar://, data:json, …)
   * ready to be passed to the underlying smart contract.
   */
  generateTokenUri(metadata: NFTMetadata): Promise<string>;

  /**
   * Apply evolution rules to an existing Pass. This may mutate the Pass entity
   * or return a separate value object describing the delta, depending on
   * domain preferences. It must never commit changes to persistence by itself.
   */
  applyEvolutionRules(
    pass: Pass,
    snapshot: StageSnapshot
  ): Promise<EvolutionResult>;

  /**
   * Validate a metadata object against both the ERC schema and business rules.
   * An implementation should throw an InvalidMetadataError if the object is
   * invalid. Returning void signals success.
   */
  validateMetadata(metadata: NFTMetadata): void | never;
}

/* -------------------------------------------------------------------------- */
/*                         Abstract Helper / Reference                        */
/* -------------------------------------------------------------------------- */

/**
 * Provides a handy base to reduce boilerplate for the most common behaviour
 * shared by NFT generation strategies (IPFS pinning + JSON schema validation).
 *
 * Concrete strategies may extend this class and only implement the specific
 * business logic. It can be swapped out for composition if multiple inheritance
 * becomes a problem.
 */
export abstract class BaseNftGenerationStrategy
  implements INftGenerationStrategy
{
  /* ---------------------------- Static Resources -------------------------- */

  // A permissive-yet-robust JSON schema for ERC-721 metadata, enforced by Zod.
  private static readonly metadataSchema = z.object({
    name: z.string().min(1).max(100),
    description: z.string().min(1).max(1000),
    image: z.string().url().optional(),
    animation_url: z.string().url().optional(),
    external_url: z.string().url().optional(),
    attributes: z
      .array(
        z.object({
          trait_type: z.string(),
          value: z.union([z.string(), z.number()]),
          display_type: z
            .enum([
              'number',
              'date',
              'boost_percentage',
              'boost_number',
              'string',
            ])
            .optional(),
        })
      )
      .optional(),
  });

  /* ------------------------------- Lifecycle ------------------------------ */

  constructor(private readonly ipfsUploader: IIpfsUploader) {}

  /* ------------------- INftGenerationStrategy Implementations ------------- */

  abstract generateMetadata(
    show: Show,
    pass: Pass,
    snapshot: StageSnapshot
  ): Promise<NFTMetadata>;

  /**
   * Default implementation uploads the metadata JSON blob to IPFS and returns
   * the resulting URI. Subclasses may override if they need custom handling.
   */
  async generateTokenUri(metadata: NFTMetadata): Promise<string> {
    // Use provided IPFS adapter – the infrastructure layer will delegate to
    // pinning services (Infura, Pinata, Filebase, self-hosted cluster, …).
    try {
      const cid = await this.ipfsUploader.pinJson(metadata);
      return `ipfs://${cid}`;
    } catch (err) {
      // Add contextual information before propagating the error up-stream.
      throw new Error(
        `Failed to pin NFT metadata to IPFS: ${(err as Error).message}`
      );
    }
  }

  abstract applyEvolutionRules(
    pass: Pass,
    snapshot: StageSnapshot
  ): Promise<EvolutionResult>;

  /**
   * Base validation delegates to a shared JSON schema. Extra validations
   * (e.g. uniqueness constraints, trait whitelists) belong in subclasses.
   */
  validateMetadata(metadata: NFTMetadata): void | never {
    const result = BaseNftGenerationStrategy.metadataSchema.safeParse(metadata);

    if (!result.success) {
      throw new InvalidMetadataError(
        'NFT metadata failed schema validation.',
        result.error.issues
      );
    }
  }
}
```