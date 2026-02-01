```typescript
/*******************************************************************************************
 * StellarStage Carnival
 * File: packages/backend/src/domain/state-machines/pass-state.machine.ts
 *
 * Description:
 * State-machine that governs the lifecycle of a Show-Pass NFT.  Lives entirely in the
 * domain layer and therefore has NO direct blockchain / database dependencies.  All
 * side-effects (minting, staking, burning, event-stream notifications, etc.) are injected
 * by the application layer through callback options, keeping the machine portable,
 * test-friendly and fully compliant with Clean Architecture.
 *
 * State Diagram:
 *
 * ┌──────────┐   MINT    ┌────────┐  ACTIVATE  ┌──────────┐   STAKE   ┌─────────┐
 * │ unminted │ ─────────▶│ minted │───────────▶│ activated│──────────▶│ staked  │
 * └──────────┘           └────────┘            └──────────┘            └─────────┘
 *   ▲   │                   │  ▲                  │   ▲                   │  │
 *   │   │                   │  │                  │   │                   │  │
 *   │   └─────── ERROR ◀────┘  └──── BURN ────────┘   └── UNSTAKE ────────┘  │
 *   │                                                                   │
 *   └─────────────────────────────────── BURN ───────────────────────────┘
 *
 * Terminal state:
 *   burned
 *******************************************************************************************/

import {
  createMachine,
  assign,
  InterpreterFrom,
  StateFrom,
  DefaultContext
} from 'xstate';

/* ------------------------------------------------------------------------- */
/*  Domain Types                                                             */
/* ------------------------------------------------------------------------- */

/**
 * Shared context that travels with the state-machine through its entire
 * lifecycle. Nothing in here is infra-specific – pure business data only.
 */
export interface PassContext extends DefaultContext {
  /** Immutable identifier of the NFT pass (token-ID or UUID). */
  readonly passId: string;

  /** Ethereum / chain address that owns the token. */
  ownerAddress?: string;

  /** Transaction hash used when the pass was minted. */
  mintedTxHash?: string;

  /** Block number when pass became active. */
  activatedAtBlock?: number;

  /** Timestamp (unix epoch, millis) when last staked. */
  stakedAt?: number;

  /** Address of staking contract currently holding the pass. */
  stakingContract?: string;

  /** Accumulated state names for simple audit trail / debugging. */
  stateHistory: string[];

  /** Last error message (if any) captured by the machine. */
  error?: string;
}

/**
 * All domain events the machine can respond to.
 */
export type PassEvent =
  | { type: 'MINT'; payload: { ownerAddress: string; txHash: string } }
  | { type: 'ACTIVATE'; payload: { blockNumber: number } }
  | { type: 'STAKE'; payload: { stakingContract: string; timestamp: number } }
  | { type: 'UNSTAKE'; payload: { timestamp: number } }
  | { type: 'BURN'; payload: { reason?: string } }
  | { type: 'ERROR'; payload: { error: Error } };

/**
 * Optional side-effect hooks that the application layer can inject when
 * creating the machine instance.
 */
export interface PassStateMachineOptions {
  onMint?: (ctx: Readonly<PassContext>, payload: PassEvent & { type: 'MINT' }) => unknown;
  onActivate?: (
    ctx: Readonly<PassContext>,
    payload: PassEvent & { type: 'ACTIVATE' }
  ) => unknown;
  onStake?: (ctx: Readonly<PassContext>, payload: PassEvent & { type: 'STAKE' }) => unknown;
  onUnstake?: (
    ctx: Readonly<PassContext>,
    payload: PassEvent & { type: 'UNSTAKE' }
  ) => unknown;
  onBurn?: (ctx: Readonly<PassContext>, payload: PassEvent & { type: 'BURN' }) => unknown;
  onError?: (
    ctx: Readonly<PassContext>,
    payload: PassEvent & { type: 'ERROR' }
  ) => unknown;
}

/* ------------------------------------------------------------------------- */
/*  Internal helpers                                                         */
/* ------------------------------------------------------------------------- */

/** Utility to push the current state into history. */
const recordHistory = assign<PassContext, PassEvent>({
  stateHistory: (ctx, _evt, meta) => [...ctx.stateHistory, meta.state.value as string]
});

/** Utility to capture an error. */
const captureError = assign<PassContext, PassEvent>({
  error: (_ctx, evt) =>
    evt.type === 'ERROR'
      ? evt.payload.error?.message ?? 'Unknown error'
      : undefined
});

/* ------------------------------------------------------------------------- */
/*  Machine Blueprint                                                        */
/* ------------------------------------------------------------------------- */

const passStateBlueprint = createMachine<PassContext, PassEvent>(
  {
    id: 'passNFT',
    initial: 'unminted',
    predictableActionArguments: true,
    tsTypes: {} as import('./pass-state.machine.typegen').Typegen0, // auto-generated by xstate-codegen
    states: {
      /* ---------------------------------------------------- */
      unminted: {
        on: {
          MINT: {
            target: 'minted',
            actions: ['handleMint', recordHistory]
          },
          ERROR: {
            actions: ['handleError']
          }
        }
      },

      /* ---------------------------------------------------- */
      minted: {
        on: {
          ACTIVATE: {
            target: 'activated',
            actions: ['handleActivate', recordHistory]
          },
          BURN: {
            target: 'burned',
            actions: ['handleBurn', recordHistory]
          },
          ERROR: {
            actions: ['handleError']
          }
        }
      },

      /* ---------------------------------------------------- */
      activated: {
        on: {
          STAKE: {
            target: 'staked',
            actions: ['handleStake', recordHistory]
          },
          BURN: {
            target: 'burned',
            actions: ['handleBurn', recordHistory]
          },
          ERROR: {
            actions: ['handleError']
          }
        }
      },

      /* ---------------------------------------------------- */
      staked: {
        on: {
          UNSTAKE: {
            target: 'activated',
            actions: ['handleUnstake', recordHistory]
          },
          BURN: {
            target: 'burned',
            actions: ['handleBurn', recordHistory]
          },
          ERROR: {
            actions: ['handleError']
          }
        }
      },

      /* ---------------------------------------------------- */
      burned: {
        type: 'final'
      }
    }
  },
  {
    actions: {
      /** Domain-pure bookkeeping for MINT transition + external callback. */
      handleMint: assign((ctx, evt: PassEvent, { action, state }) => {
        if (evt.type !== 'MINT') return ctx;
        action.exec?.({} as any, {} as any); // keep TS happy when no options provided
        return {
          ...ctx,
          ownerAddress: evt.payload.ownerAddress,
          mintedTxHash: evt.payload.txHash
        };
      }),

      /** Bookkeeping for ACTIVATE transition. */
      handleActivate: assign((ctx, evt: PassEvent) => {
        if (evt.type !== 'ACTIVATE') return ctx;
        return {
          ...ctx,
          activatedAtBlock: evt.payload.blockNumber
        };
      }),

      /** Bookkeeping for STAKE transition. */
      handleStake: assign((ctx, evt: PassEvent) => {
        if (evt.type !== 'STAKE') return ctx;
        return {
          ...ctx,
          stakedAt: evt.payload.timestamp,
          stakingContract: evt.payload.stakingContract
        };
      }),

      /** Bookkeeping for UNSTAKE transition. */
      handleUnstake: assign((ctx, evt: PassEvent) => {
        if (evt.type !== 'UNSTAKE') return ctx;
        return {
          ...ctx,
          stakedAt: undefined,
          stakingContract: undefined
        };
      }),

      /** Bookkeeping for BURN transition. */
      handleBurn: assign((ctx, evt: PassEvent) => {
        if (evt.type !== 'BURN') return ctx;
        return {
          ...ctx
        };
      }),

      /** Centralized error handler. */
      handleError: [captureError, 'invokeOnError']
    }
  }
);

/* ------------------------------------------------------------------------- */
/*  Factory                                                                  */
/* ------------------------------------------------------------------------- */

/**
 * Builds a new Pass-state-machine instance with domain-specific callbacks wired-in.
 *
 * @param passId   – Token identifier for the pass.
 * @param options  – Optional side-effect hooks (infrastructure will inject these).
 * @param seed     – Optional partial context used for rehydrating machines from storage.
 */
export function createPassStateMachine(
  passId: string,
  options: PassStateMachineOptions = {},
  seed: Partial<Omit<PassContext, 'passId' | 'stateHistory'>> = {}
) {
  return passStateBlueprint.withConfig(
    {
      actions: {
        handleMint: [
          'recordMintInContext',
          (ctx, evt) => options.onMint?.(ctx, evt as any)
        ],
        handleActivate: [
          'recordActivateInContext',
          (ctx, evt) => options.onActivate?.(ctx, evt as any)
        ],
        handleStake: [
          'recordStakeInContext',
          (ctx, evt) => options.onStake?.(ctx, evt as any)
        ],
        handleUnstake: [
          'recordUnstakeInContext',
          (ctx, evt) => options.onUnstake?.(ctx, evt as any)
        ],
        handleBurn: [
          'recordBurnInContext',
          (ctx, evt) => options.onBurn?.(ctx, evt as any)
        ],
        invokeOnError: (ctx, evt) => {
          if (evt.type === 'ERROR') {
            options.onError?.(ctx, evt);
          }
        }
      }
    },
    {
      passId,
      stateHistory: [],
      ...seed
    }
  );
}

/* ------------------------------------------------------------------------- */
/*  Types exports                                                            */
/* ------------------------------------------------------------------------- */

export type PassStateMachine = ReturnType<typeof createPassStateMachine>;
export type PassStateService = InterpreterFrom<PassStateMachine>;
export type PassState = StateFrom<PassStateMachine>;
```