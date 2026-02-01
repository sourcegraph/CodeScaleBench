```typescript
/***************************************************************************************************
 *  StellarStage Carnival – Poll Domain Entity
 *  ------------------------------------------------
 *  This entity encapsulates a real-time, in-show poll that can be backed by an on-chain snapshot.
 *  A poll belongs to a Show (showId) and can be voted on by holders of Pass NFTs (passId).
 *
 *  Design notes
 *  • Immutable value objects are preferred; mutable collections are hidden behind methods.
 *  • clean-architecture compliant: no dependencies on infra / persistence / web.
 *  • Merkle root can be produced for on-chain anchoring of the final vote state.
 ***************************************************************************************************/

import { randomUUID } from 'crypto';
import crypto from 'crypto';

/* ========================================================================= *\
|*                                                                            *|
|*  Types & Value Objects                                                     *|
|*                                                                            *|
\* ========================================================================= */

export type PollId   = string; // UUID v4
export type OptionId = string; // UUID v4
export type PassId   = string; // EVM address or NFT id string

export enum PollStatus {
  DRAFT      = 'DRAFT',
  OPEN       = 'OPEN',
  CLOSED     = 'CLOSED',
  CANCELLED  = 'CANCELLED',
}

export interface PollOptionProps {
  id: OptionId;
  text: string;
}

/**
 * A single answer the user can vote for.
 * The entity is *not* aware of votes; Poll manages that to keep invariants local.
 */
export class PollOption {
  public readonly id: OptionId;
  public readonly text: string;

  constructor(props: PollOptionProps) {
    if (!props.text || props.text.trim().length === 0) {
      throw new Error('PollOption: text must not be empty.');
    }
    this.id   = props.id ?? randomUUID();
    this.text = props.text.trim();
  }

  public toPrimitives(): PollOptionProps {
    return { id: this.id, text: this.text };
  }
}

export interface PollProps {
  id?: PollId;
  showId: string;           // foreign key to Show aggregate
  question: string;
  options: PollOptionProps[] | PollOption[];
  createdAt?: Date;
  expiresAt?: Date;
}

/* ========================================================================= *\
|*                                                                            *|
|*  Poll Entity                                                                *|
|*                                                                            *|
\* ========================================================================= */

export class Poll {
  /* --------------------------------------------------------------------- */
  /*  Construction                                                          */
  /* --------------------------------------------------------------------- */
  public readonly id: PollId;
  public readonly showId: string;
  public readonly question: string;
  public readonly createdAt: Date;
  public readonly expiresAt?: Date;

  private _status: PollStatus = PollStatus.DRAFT;

  /** optionId ➜ set(passId) */
  private readonly _votes: Map<OptionId, Set<PassId>> = new Map();

  /** list of answer choices */
  private readonly _options: PollOption[];

  constructor(props: PollProps) {
    /* ------- validation ------------------------------------------------- */
    if (!props.showId) {
      throw new Error('Poll: showId must be provided.');
    }
    if (!props.question || props.question.trim().length === 0) {
      throw new Error('Poll: question must be provided.');
    }
    const options = props.options.map(
      (o) => (o instanceof PollOption ? o : new PollOption(o)),
    );

    if (options.length < 2 || options.length > 10) {
      throw new Error('Poll: must have between 2 and 10 options.');
    }

    // ensure distinct option text
    const duplicates = new Set<string>();
    options.forEach((opt) => {
      const key = opt.text.toLowerCase();
      if (duplicates.has(key)) {
        throw new Error(`Poll: duplicate option "${opt.text}".`);
      }
      duplicates.add(key);
    });

    /* ------- assign ----------------------------------------------------- */
    this.id        = props.id ?? randomUUID();
    this.showId    = props.showId;
    this.question  = props.question.trim();
    this.createdAt = props.createdAt ?? new Date();
    this.expiresAt = props.expiresAt;

    if (
      this.expiresAt &&
      this.expiresAt.getTime() <= this.createdAt.getTime()
    ) {
      throw new Error('Poll: expiresAt must be in the future.');
    }

    this._options = options;
    this._status  = PollStatus.DRAFT;

    // initialise vote map
    this._options.forEach((opt) => this._votes.set(opt.id, new Set()));
  }

  /* --------------------------------------------------------------------- */
  /*  Public getters                                                        */
  /* --------------------------------------------------------------------- */
  public get status(): PollStatus {
    return this._status;
  }

  public get options(): readonly PollOption[] {
    return this._options;
  }

  /**
   * Returns a snapshot of current vote tally.
   * @returns Map<optionId, number>
   */
  public tally(): Map<OptionId, number> {
    const results = new Map<OptionId, number>();
    this._votes.forEach((set, optionId) => results.set(optionId, set.size));
    return results;
  }

  /**
   * Determine the winning option(s) – can be called only when CLOSED.
   */
  public winners(): PollOption[] {
    if (this._status !== PollStatus.CLOSED) {
      throw new Error('Poll: winners can only be determined when poll is CLOSED.');
    }
    const maxVotes = Math.max(...Array.from(this._votes.values()).map((s) => s.size));
    return this._options.filter((opt) => this._votes.get(opt.id)!.size === maxVotes);
  }

  /* --------------------------------------------------------------------- */
  /*  Lifecycle commands                                                    */
  /* --------------------------------------------------------------------- */

  /**
   * Moves poll from DRAFT → OPEN.
   */
  public open(): void {
    if (this._status !== PollStatus.DRAFT) {
      throw new Error(`Poll: cannot open poll in status ${this._status}.`);
    }
    if (this.expiresAt && this.expiresAt.getTime() <= Date.now()) {
      throw new Error('Poll: cannot open an already expired poll.');
    }
    this._status = PollStatus.OPEN;
  }

  /**
   * Cast or update a vote.
   * • Throws if poll not OPEN or expired.
   * • Pass holder can update their vote until poll closes.
   */
  public castVote(passId: PassId, optionId: OptionId): void {
    if (this._status !== PollStatus.OPEN) {
      throw new Error('Poll: votes can only be cast while poll is OPEN.');
    }
    if (this.expiresAt && this.expiresAt.getTime() <= Date.now()) {
      this._status = PollStatus.CLOSED;
      throw new Error('Poll: voting period has expired.');
    }
    if (!this._votes.has(optionId)) {
      throw new Error(`Poll: optionId ${optionId} does not exist.`);
    }

    // Remove vote from any previously selected option
    for (const [optId, voters] of this._votes.entries()) {
      if (voters.delete(passId)) {
        break; // pass vote found & removed
      }
    }
    // Add vote to chosen option
    this._votes.get(optionId)!.add(passId);
  }

  /**
   * Finalises the poll. No further votes allowed.
   */
  public close(): void {
    if (this._status !== PollStatus.OPEN) {
      throw new Error(`Poll: cannot close poll in status ${this._status}.`);
    }
    this._status = PollStatus.CLOSED;
  }

  /**
   * Cancels the poll; votes are wiped.
   */
  public cancel(): void {
    if (this._status === PollStatus.CANCELLED) return;
    this._status = PollStatus.CANCELLED;
    this._votes.clear();
  }

  /* --------------------------------------------------------------------- */
  /*  On-chain snapshot helpers                                             */
  /* --------------------------------------------------------------------- */

  /**
   * Compute a SHA-256 merkle root of all current votes.
   * Each leaf is <passId>::<optionId>
   * This root can be stored on-chain for immutability.
   */
  public merkleRoot(): string {
    // Flatten votes into leaf hash strings
    const leaves: string[] = [];
    this._votes.forEach((voters, optionId) => {
      voters.forEach((passId) => {
        leaves.push(`${passId}::${optionId}`);
      });
    });

    // If no votes yet, commit to empty string for deterministic root
    if (leaves.length === 0) {
      return this.hash('');
    }

    // Hash each leaf
    let level: Buffer[] = leaves.map((data) => this.hashBuffer(data));

    // Build tree
    while (level.length > 1) {
      const next: Buffer[] = [];
      for (let i = 0; i < level.length; i += 2) {
        const left = level[i];
        const right = level[i + 1] ?? left; // duplicate last node if uneven
        next.push(this.hashBuffer(Buffer.concat([left, right])));
      }
      level = next;
    }
    return level[0].toString('hex');
  }

  /* --------------------------------------------------------------------- */
  /*  Persistence helpers                                                   */
  /* --------------------------------------------------------------------- */
  public toPrimitives(): Record<string, any> {
    return {
      id: this.id,
      showId: this.showId,
      question: this.question,
      status: this._status,
      createdAt: this.createdAt.toISOString(),
      expiresAt: this.expiresAt?.toISOString() ?? null,
      options: this._options.map((o) => o.toPrimitives()),
      votes: Array.from(this._votes.entries()).map(([optId, voters]) => ({
        optionId: optId,
        voterIds: Array.from(voters),
      })),
    };
  }

  /* --------------------------------------------------------------------- */
  /*  Utilities                                                             */
  /* --------------------------------------------------------------------- */
  private hashBuffer(data: Buffer | string): Buffer {
    return crypto.createHash('sha256').update(data).digest();
  }

  private hash(data: Buffer | string): string {
    return this.hashBuffer(data).toString('hex');
  }
}
```