```javascript
/**
 * @file Button.test.js
 * Comprehensive test–suite for the shared <Button/> component.
 *
 * Note:
 *  ─ The Button component is assumed to live inside:
 *      `@/components/common/Button.jsx`
 *  ─ The component signature is assumed to be:
 *        <Button
 *           variant="primary"            // visual variant
 *           isLoading={false}            // renders spinner + disables clicks
 *           disabled={false}             // manually disable the button
 *           onClick={fn}                 // click handler
 *           data-testid="my-btn"         // forwarded to root element
 *        >
 *           Children
 *        </Button>
 *  ─ <Button/> must expose accessibility attributes (`role="button"`,
 *      `aria-disabled`, `aria-busy`) internally.
 *
 * If any of the assumptions diverge from your implementation, tweak the tests
 * accordingly.
 */

/* ────────────────────────────────────────────────────────────────────────── */
/* Dependencies                                                             */
/* ────────────────────────────────────────────────────────────────────────── */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

import Button from '@/components/common/Button';

/* ────────────────────────────────────────────────────────────────────────── */
/* Utilities                                                                */
/* ────────────────────────────────────────────────────────────────────────── */
const setup = (props = {}, children = 'Click Me') => {
  const utils = render(<Button {...props}>{children}</Button>);
  const btn   = utils.getByRole('button');
  return { ...utils, btn };
};

/* ────────────────────────────────────────────────────────────────────────── */
/* Test–suite                                                               */
/* ────────────────────────────────────────────────────────────────────────── */
describe('<Button /> – basic rendering', () => {
  test('renders without crashing & displays children', () => {
    const label = 'Enroll now';
    const { btn } = setup({}, label);

    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent(label);
  });

  test('applies visual variant class', () => {
    const variant = 'secondary';
    const { btn } = setup({ variant });

    /* Implementation detail:
     *  We assume Button attaches `btn--<variant>` modifier class.
     *  Adjust the selector if you use a different convention.
     */
    expect(btn).toHaveClass(`btn--${variant}`);
  });
});

describe('<Button /> – interaction', () => {
  test('fires onClick event when enabled', () => {
    const onClick = jest.fn();
    const { btn } = setup({ onClick });

    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  test('does not fire onClick when disabled', () => {
    const onClick = jest.fn();
    const { btn }  = setup({ onClick, disabled: true });

    fireEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();
  });

  test('does not fire onClick when loading', () => {
    const onClick = jest.fn();
    const { btn } = setup({ onClick, isLoading: true });

    fireEvent.click(btn);
    expect(onClick).not.toHaveBeenCalled();
  });

  test('supports keyboard activation (Enter / Space)', async () => {
    const user = userEvent.setup();
    const onClick = jest.fn();
    const { btn } = setup({ onClick });

    await user.tab();
    expect(btn).toHaveFocus();

    await user.keyboard('{Enter}');
    await user.keyboard(' ');
    expect(onClick).toHaveBeenCalledTimes(2);
  });
});

describe('<Button /> – accessibility', () => {
  test('exposes aria-disabled when disabled', () => {
    const { btn } = setup({ disabled: true });
    expect(btn).toHaveAttribute('aria-disabled', 'true');
  });

  test('exposes aria-busy when loading', () => {
    const { btn } = setup({ isLoading: true });
    expect(btn).toHaveAttribute('aria-busy', 'true');
  });

  test('renders a deterministic loading spinner label', () => {
    const { btn } = setup({ isLoading: true }, 'Submit');
    /* The spinner element should be accessible via role "status". */
    const spinner = screen.getByRole('status');
    expect(spinner).toBeInTheDocument();
    // The button text should be preserved for screen‐readers.
    expect(btn).toHaveTextContent('Submit');
  });
});

describe('<Button /> – snapshot regression', () => {
  test('matches snapshot (primary, enabled)', () => {
    const { asFragment } = setup({ variant: 'primary' }, 'Snapshot');
    expect(asFragment()).toMatchSnapshot();
  });

  test('matches snapshot (loading state)', () => {
    const { asFragment } = setup({ isLoading: true }, 'Snapshot');
    expect(asFragment()).toMatchSnapshot();
  });
});
```