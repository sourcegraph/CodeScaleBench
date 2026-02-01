/**
 * @file Modal.js
 *
 * A11y-focused, production-grade modal component implemented as a React portal.
 * This component is intended to be shared across the PulseLearn Campus Hub
 * frontend to display dialogs, forms, media viewers, confirmations, etc.
 *
 * Usage:
 *   <Modal
 *      isOpen={state.isModalOpen}
 *      title="Edit profile"
 *      size="lg"
 *      onClose={() => setState({ isModalOpen : false })}
 *      initialFocusRef={firstInputRef}
 *    >
 *      …modal content…
 *   </Modal>
 *
 * Features:
 *  • Rendered in a ReactDOM portal so it is visually on top of everything else.
 *  • Focus trap and keyboard navigation (ESC to close).
 *  • Optional backdrop click to close (configurable).
 *  • ARIA attributes for screen-reader support.
 *  • Support for three predefined sizes (`sm`, `md`, `lg`) + full-screen.
 *  • Imperative API via ref (e.g. parent components can call modalRef.current.close()).
 *
 *  Styling is handled through an associated SCSS file that lives next to this
 *  component (import './Modal.scss'). The SCSS file is expected to set up the
 *  transitions, sizing helpers, z-index stacking, dark/light theme awareness, etc.
 */

import React, {
  useCallback,
  useEffect,
  useRef,
  useImperativeHandle,
  forwardRef,
} from 'react';
import ReactDOM from 'react-dom';
import PropTypes from 'prop-types';
import classNames from 'classnames';
import { v4 as uuidv4 } from 'uuid';

import './Modal.scss';

// The DOM node that will host *all* modals. It is created lazily the first time
// a modal is rendered so the consumer does not have to add it manually.
let modalRoot = null;
const getModalRoot = () => {
  if (typeof document === 'undefined') return null;

  if (!modalRoot) {
    modalRoot = document.getElementById('modal-root');
    if (!modalRoot) {
      modalRoot          = document.createElement('div');
      modalRoot.id       = 'modal-root';
      modalRoot.dataset.mount = 'pulslearn-modal-root';
      document.body.appendChild(modalRoot);
    }
  }
  return modalRoot;
};

const KEY_ESCAPE = 27;

// Utility: returns all tabbable nodes within a container.
const getTabbableNodes = container => {
  if (!container) return [];
  // Matches elements that are naturally tabbable or with tabindex not -1
  // Thanks to: https://developer.mozilla.org/en-US/docs/Web/Accessibility/Keyboard-navigable_JavaScript_widgets
  return Array.from(
    container.querySelectorAll(
      'a[href], area[href], input:not([disabled]), select:not([disabled]), ' +
        'textarea:not([disabled]), button:not([disabled]), iframe, object, embed, ' +
        '[tabindex]:not([tabindex="-1"]), [contenteditable=true]',
    ),
  ).filter(node => node.offsetWidth || node.offsetHeight || node.getClientRects().length);
};

const Modal = forwardRef(
  (
    {
      id,
      title,
      isOpen,
      onClose,
      closeOnEsc = true,
      closeOnBackdrop = true,
      size = 'md', // 'sm' | 'md' | 'lg' | 'full'
      children,
      initialFocusRef = null,
      labelledBy = null,
    },
    ref,
  ) => {
    // Generate stable IDs for accessibility
    const internalId = useRef(id || `modal-${uuidv4()}`);
    const titleId = labelledBy || `${internalId.current}-title`;

    // Refs for focus management
    const modalRef = useRef(null); // wrapper inside the portal
    const previouslyFocusedEl = useRef(null);

    // Close helpers -----------------------------------------------------------
    const triggerClose = useCallback(
      reason => {
        if (typeof onClose === 'function') {
          onClose(reason);
        }
      },
      [onClose],
    );

    // Expose imperative API ----------------------------------------------------
    useImperativeHandle(
      ref,
      () => ({
        close: () => triggerClose('imperative'),
        open: () => {
          if (!isOpen) {
            // consumer must handle by updating isOpen prop
            // we just expose the symmetry of close/open for completeness
            console.warn(
              'Modal.open() called but component is controlled via isOpen prop. ' +
                'Update the isOpen prop from the parent to open the modal.',
            );
          }
        },
        root: () => modalRef.current,
      }),
      [isOpen, triggerClose],
    );

    // Focus trap --------------------------------------------------------------
    useEffect(() => {
      if (!isOpen) return undefined;

      previouslyFocusedEl.current = document.activeElement;

      const nodeToFocus = initialFocusRef?.current || modalRef.current;
      nodeToFocus && nodeToFocus.focus();

      const handleKeyDown = e => {
        // ESC key to close
        if (e.keyCode === KEY_ESCAPE && closeOnEsc) {
          e.preventDefault();
          triggerClose('escape');
        }

        // Tab focus trap
        if (e.key === 'Tab') {
          const tabbable = getTabbableNodes(modalRef.current);
          if (tabbable.length === 0) {
            e.preventDefault();
            return;
          }
          const first = tabbable[0];
          const last = tabbable[tabbable.length - 1];
          if (e.shiftKey) {
            // shift + tab
            if (document.activeElement === first) {
              e.preventDefault();
              last.focus();
            }
          } else if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      };

      document.addEventListener('keydown', handleKeyDown);

      return () => {
        document.removeEventListener('keydown', handleKeyDown);
        // Return focus to the previously focused element
        previouslyFocusedEl.current?.focus?.();
      };
    }, [isOpen, closeOnEsc, initialFocusRef, triggerClose]);

    // Disable background scroll while modal is open ---------------------------
    useEffect(() => {
      if (!isOpen) return undefined;

      const originalOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';

      return () => {
        document.body.style.overflow = originalOverflow;
      };
    }, [isOpen]);

    // Early return if not open (do not render portal nor listeners) -----------
    if (!isOpen) return null;

    // Backdrop click handler ---------------------------------------------------
    const onBackdropClick = e => {
      if (modalRef.current && !modalRef.current.contains(e.target)) {
        if (closeOnBackdrop) {
          triggerClose('backdrop');
        } else {
          // If backdrop click is disabled, prevent focus loss.
          modalRef.current.focus();
        }
      }
    };

    // Modal JSX ---------------------------------------------------------------
    const modalJSX = (
      <div
        className="pl-modal-overlay"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        id={internalId.current}
        onMouseDown={onBackdropClick} // Use mousedown to capture before focus shift
        data-testid="pl-modal-overlay"
      >
        <div
          className={classNames('pl-modal', `pl-modal--${size}`)}
          ref={modalRef}
          tabIndex={-1} // Make div programmatically focusable
        >
          <header className="pl-modal__header">
            {title && (
              <h2 id={titleId} className="pl-modal__title">
                {title}
              </h2>
            )}
            <button
              type="button"
              className="pl-modal__close"
              aria-label="Close dialog"
              onClick={() => triggerClose('close-button')}
              data-testid="pl-modal-close-btn"
            >
              ×
            </button>
          </header>
          <section className="pl-modal__body">{children}</section>
        </div>
      </div>
    );

    return ReactDOM.createPortal(modalJSX, getModalRoot());
  },
);

Modal.displayName = 'Modal';

Modal.propTypes = {
  id: PropTypes.string,
  title: PropTypes.oneOfType([PropTypes.string, PropTypes.node]),
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired, // called with reason string
  closeOnEsc: PropTypes.bool,
  closeOnBackdrop: PropTypes.bool,
  size: PropTypes.oneOf(['sm', 'md', 'lg', 'full']),
  children: PropTypes.node.isRequired,
  initialFocusRef: PropTypes.shape({
    current: PropTypes.instanceOf(Element),
  }),
  labelledBy: PropTypes.string,
};

export default Modal;