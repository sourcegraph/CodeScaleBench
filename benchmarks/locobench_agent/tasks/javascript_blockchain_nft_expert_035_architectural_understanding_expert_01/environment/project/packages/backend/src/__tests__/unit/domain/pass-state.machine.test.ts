```typescript
/**
 * @file pass-state.machine.test.ts
 *
 * Unit-tests for the PassStateMachine domain component.  The state-machine
 * controls the lifecycle of a Show-Pass NFT and enforces legal transitions.
 *
 * NOTE: The domain layer lives behind a public API – we never reach directly
 * into private members; we solely rely on the interface contract.
 *
 * Test philosophy:
 *  • Golden-path:   Valid transitions should succeed and reflect the new state.
 *  • Guard-rails:   Illegal transitions must throw a DomainError.
 *  • Fuzz / table:  Transition matrix is expressed as table-driven tests so that
 *                  adding a new state requires updating *exactly one* place.
 */

import { PassStateMachine } from '../../../../domain/pass/PassStateMachine';
import { PassState } from '../../../../domain/pass/PassState';
import { PassEvent } from '../../../../domain/pass/PassEvent';
import { DomainError } from '../../../../domain/errors/DomainError';

describe('PassStateMachine', () => {
  /**
   * Utility that wraps a transition and returns its resulting state.
   */
  const fire = (
    sm: PassStateMachine,
    event: PassEvent,
  ): PassState => {
    sm.handle(event);
    return sm.state;
  };

  it('Starts in the Mintable state by default', () => {
    const sm = new PassStateMachine();
    expect(sm.state).toBe(PassState.Mintable);
  });

  it('Supports a custom bootstrap state (for migrations / replays)', () => {
    const sm = new PassStateMachine(PassState.Staked);
    expect(sm.state).toBe(PassState.Staked);
  });

  describe('Golden-path transitions', () => {
    it('Mintable → Minted → Activated → Staked → Upgraded → Burned', () => {
      const sm = new PassStateMachine();

      expect(fire(sm, PassEvent.MINT)).toBe(PassState.Minted);
      expect(fire(sm, PassEvent.ACTIVATE)).toBe(PassState.Activated);
      expect(fire(sm, PassEvent.STAKE)).toBe(PassState.Staked);
      expect(fire(sm, PassEvent.UPGRADE)).toBe(PassState.Upgraded);
      expect(fire(sm, PassEvent.BURN)).toBe(PassState.Burned);
    });
  });

  /**
   * Transition matrix:
   * row = current state,
   * column = event,
   * value = expected next state or `X` (should throw).
   */
  const matrix: Record<
    PassState,
    Partial<Record<PassEvent, PassState | 'X'>>
  > = {
    [PassState.Mintable]: {
      [PassEvent.MINT]: PassState.Minted,
      [PassEvent.ACTIVATE]: 'X',
      [PassEvent.STAKE]: 'X',
      [PassEvent.UPGRADE]: 'X',
      [PassEvent.BURN]: 'X',
    },
    [PassState.Minted]: {
      [PassEvent.MINT]: 'X',
      [PassEvent.ACTIVATE]: PassState.Activated,
      [PassEvent.STAKE]: 'X',
      [PassEvent.UPGRADE]: 'X',
      [PassEvent.BURN]: PassState.Burned,
    },
    [PassState.Activated]: {
      [PassEvent.MINT]: 'X',
      [PassEvent.ACTIVATE]: 'X',
      [PassEvent.STAKE]: PassState.Staked,
      [PassEvent.UPGRADE]: PassState.Upgraded,
      [PassEvent.BURN]: PassState.Burned,
    },
    [PassState.Staked]: {
      [PassEvent.MINT]: 'X',
      [PassEvent.ACTIVATE]: 'X',
      [PassEvent.STAKE]: 'X', // idempotency guard
      [PassEvent.UPGRADE]: PassState.Upgraded,
      [PassEvent.BURN]: PassState.Burned,
    },
    [PassState.Upgraded]: {
      [PassEvent.MINT]: 'X',
      [PassEvent.ACTIVATE]: 'X',
      [PassEvent.STAKE]: PassState.Staked, // can re-stake after upgrade
      [PassEvent.UPGRADE]: 'X',            // upgrade is one-shot
      [PassEvent.BURN]: PassState.Burned,
    },
    [PassState.Burned]: {
      [PassEvent.MINT]: 'X',
      [PassEvent.ACTIVATE]: 'X',
      [PassEvent.STAKE]: 'X',
      [PassEvent.UPGRADE]: 'X',
      [PassEvent.BURN]: 'X',
    },
  };

  describe('Guard-rail: illegal transitions are rejected', () => {
    // Generate a Jest table of [initialState, event, expected]
    const cases: Array<[PassState, PassEvent, PassState | 'X']> = [];

    Object.entries(matrix).forEach(([fromState, row]) => {
      Object.entries(row).forEach(([event, expected]) => {
        cases.push([Number(fromState) as PassState, Number(event) as PassEvent, expected]);
      });
    });

    it.each(cases)(
      '%s --(%s)--> %s',
      (initialState, event, expected) => {
        const sm = new PassStateMachine(initialState);

        if (expected === 'X') {
          expect(() => sm.handle(event)).toThrow(DomainError);
          expect(sm.state).toBe(initialState); // state unchanged
        } else {
          sm.handle(event);
          expect(sm.state).toBe(expected);
        }
      },
    );
  });

  describe('Idempotency / Replay-safety', () => {
    it('Re-processing the same event stream stabilizes at the same state', () => {
      const events: PassEvent[] = [
        PassEvent.MINT,
        PassEvent.ACTIVATE,
        PassEvent.STAKE,
        PassEvent.UPGRADE,
        PassEvent.BURN,
      ];

      // First run
      const first = new PassStateMachine();
      events.forEach(evt => first.handle(evt));

      // Second run (simulate event sourcing replay)
      const second = new PassStateMachine();
      events.forEach(evt => second.handle(evt));

      expect(second.state).toBe(first.state);
      expect(second.state).toBe(PassState.Burned);
    });
  });
});
```