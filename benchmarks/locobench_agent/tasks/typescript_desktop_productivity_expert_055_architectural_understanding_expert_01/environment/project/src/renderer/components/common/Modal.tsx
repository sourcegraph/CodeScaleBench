```tsx
/**
 * PaletteFlow Studio
 * Modal.tsx
 *
 * A11y-first, theme-aware, stack-safe modal component with escape / backdrop
 * dismissal, focus trapping, and motion.  Uses React portals to render into
 * document.body so it can live outside of parent overflow/transform
 * contexts.  Complies with WAI-ARIA Authoring Practices.
 *
 * Because the renderer runs inside Electron we do *not* assume a browser-only
 * environment:  When in a frameless window we automatically add a drop shadow
 * to visually separate modal chrome from the OS chrome.
 *
 * NOTE:
 *   Although Electron bundles Node, this file should stay browser-safe;
 *   avoid fs / path imports here.
 */

import {
  ReactNode,
  KeyboardEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import ReactDOM from 'react-dom';
import { motion, AnimatePresence, Variants } from 'framer-motion';
import styled, { css } from 'styled-components';

// -- Theme ------------------------------------------------------------------

interface Theme {
  palette: {
    surface: string;
    backdrop: string;
    textPrimary: string;
    textSecondary: string;
    divider: string;
  };
  borderRadius: number;
  elevation: {
    modal: string;
  };
}

/**
 * Hook that retrieves theme variables from our global palette system.
 * Replace with your own theming solution (e.g. @mui/material or
 * Styled-Components ThemeProvider).
 */
const useTheme = (): Theme => {
  // Simplified fallback theme; real implementation would consume context.
  return {
    palette: {
      surface: '#1e1f20',
      backdrop: 'rgba(0,0,0,0.55)',
      textPrimary: '#ffffff',
      textSecondary: '#c1c1c1',
      divider: '#2d2e30',
    },
    borderRadius: 12,
    elevation: {
      modal: '0 16px 32px rgba(0,0,0,0.45)',
    },
  };
};

// -- Focus Trap -------------------------------------------------------------

/**
 * Very small focus-trap implementation. Cycles focus within the modal while
 * it's open. For production, consider `focus-trap-react` for more edge-cases.
 */
const useFocusTrap = (active: boolean) => {
  const focusableSelector =
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
  const firstFocusRef = useRef<HTMLElement | null>(null);
  const lastFocusRef = useRef<HTMLElement | null>(null);

  const trap = useCallback(
    (e: KeyboardEvent) => {
      if (!active || e.key !== 'Tab') return;

      const modal = e.currentTarget as HTMLElement;
      const focusable = Array.from(
        modal.querySelectorAll<HTMLElement>(focusableSelector)
      ).filter(el => !el.hasAttribute('disabled'));

      if (focusable.length === 0) {
        e.preventDefault();
        return;
      }
      firstFocusRef.current = focusable[0];
      lastFocusRef.current = focusable[focusable.length - 1];

      if (e.shiftKey && document.activeElement === firstFocusRef.current) {
        // Shift + Tab on first item: jump to last
        e.preventDefault();
        lastFocusRef.current?.focus();
      } else if (
        !e.shiftKey &&
        document.activeElement === lastFocusRef.current
      ) {
        // Tab on last item: jump to first
        e.preventDefault();
        firstFocusRef.current?.focus();
      }
    },
    [active]
  );

  return trap;
};

// -- Modal Manager ----------------------------------------------------------

/**
 * Simple z-index stack.  We push a number on mount and pop on unmount.
 * This avoids z-index clashes with e.g. context menus or nested modals.
 */
class ZStack {
  private index = 2000; // starting point above app content
  private stack: number[] = [];

  push(): number {
    const next = ++this.index;
    this.stack.push(next);
    return next;
  }

  pop(): void {
    this.stack.pop();
    if (this.stack.length === 0) {
      // reclaim indexes when nothing is open
      this.index = 2000;
    }
  }
}

const globalZStack = new ZStack();

// -- Component Types --------------------------------------------------------

type ModalSize = 'xs' | 'sm' | 'md' | 'lg' | 'fullscreen';

export interface ModalProps {
  open: boolean;
  onClose?: () => void;
  size?: ModalSize;
  title?: string | ReactNode;
  hideCloseButton?: boolean;
  /**
   * If provided, the ref element will receive initial focus when the modal
   * opens. Otherwise the first focusable element is focused automatically.
   */
  initialFocusRef?: React.RefObject<HTMLElement>;
  /**
   * Controls if Escape should close the modal. Defaults to true.
   */
  allowEscape?: boolean;
  /**
   * Additional aria attributes to merge into the top-level dialog.
   */
  aria?: {
    labelledBy?: string;
    describedBy?: string;
  };
  children: ReactNode;
}

// -- Styled Components ------------------------------------------------------

const Backdrop = styled(motion.div)`
  position: fixed;
  inset: 0;
  background: ${({ theme }: { theme: Theme }) => theme.palette.backdrop};
  backdrop-filter: blur(2px);
`;

const Surface = styled(motion.section)<{ widthPx: number }>`
  position: fixed;
  top: 50%;
  left: 50%;
  width: ${({ widthPx }) => widthPx}px;
  max-height: 90vh;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  background: ${({ theme }) => theme.palette.surface};
  color: ${({ theme }) => theme.palette.textPrimary};
  border-radius: ${({ theme }) => theme.borderRadius}px;
  box-shadow: ${({ theme }) => theme.elevation.modal};
  overflow: hidden;
`;

const Header = styled.header`
  padding: 1rem 1.25rem;
  font-size: 1.125rem;
  font-weight: 600;
  border-bottom: 1px solid
    ${({ theme }) => theme.palette.divider};
  display: flex;
  align-items: center;
  justify-content: space-between;
`;

const Body = styled.main`
  padding: 1rem 1.25rem;
  overflow-y: auto;
  flex: 1 1 auto;
  color: ${({ theme }) => theme.palette.textSecondary};
`;

const Footer = styled.footer`
  padding: 0.75rem 1.25rem;
  border-top: 1px solid
    ${({ theme }) => theme.palette.divider};
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
`;

const CloseButton = styled.button`
  all: unset;
  cursor: pointer;
  line-height: 1;
  padding: 0.25rem;
  border-radius: 50%;
  transition: background 120ms ease-in;
  color: ${({ theme }) => theme.palette.textSecondary};

  &:hover,
  &:focus-visible {
    background: rgba(255, 255, 255, 0.08);
  }
`;

// -- Motion Variants --------------------------------------------------------

const backdropVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1 },
};

const modalVariants: Variants = {
  hidden: { opacity: 0, y: 24, scale: 0.98 },
  visible: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { type: 'spring', stiffness: 260, damping: 25 },
  },
  exit: { opacity: 0, y: -24, scale: 0.98 },
};

// -- Helpers ----------------------------------------------------------------

const sizeToWidth = (size: ModalSize | undefined): number => {
  switch (size) {
    case 'xs':
      return 320;
    case 'sm':
      return 480;
    case 'md':
      return 640;
    case 'lg':
      return 860;
    case 'fullscreen':
      return window.innerWidth; // fallback; we override style anyway
    default:
      return 640;
  }
};

// -- Component --------------------------------------------------------------

export const Modal = ({
  open,
  onClose,
  children,
  size = 'md',
  title,
  hideCloseButton = false,
  initialFocusRef,
  allowEscape = true,
  aria = {},
}: ModalProps) => {
  const theme = useTheme();
  const [zIndex, setZIndex] = useState<number>(() => globalZStack.push());
  const dialogRef = useRef<HTMLElement>(null);

  // ----- Lifecycle --------------------------------------------------------
  useEffect(() => {
    // When unmounting OR when open toggles to false -> pop z-index.
    if (!open) return;
    return () => {
      globalZStack.pop();
    };
  }, [open]);

  // Body scroll freeze
  useEffect(() => {
    if (open) {
      const prevOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      return () => {
        document.body.style.overflow = prevOverflow;
      };
    }
  }, [open]);

  // Initial focus
  useLayoutEffect(() => {
    if (open) {
      // Give the browser a tick so the portal DOM exists
      requestAnimationFrame(() => {
        if (initialFocusRef?.current) {
          initialFocusRef.current.focus();
        } else {
          dialogRef.current
            ?.querySelector<HTMLElement>(
              'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
            )
            ?.focus();
        }
      });
    }
  }, [open, initialFocusRef]);

  // ---- Event handlers ----------------------------------------------------
  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget && onClose) {
        onClose();
      }
    },
    [onClose]
  );

  const handleKeyDown = useFocusTrap(open);

  const escHandler = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (allowEscape && e.key === 'Escape') {
        e.stopPropagation();
        onClose?.();
      }
    },
    [onClose, allowEscape]
  );

  // -- Safeguard: don't render if not open ---------------------------------
  if (!open) return null;

  // -- Determine width / full-screen ---------------------------------------
  const widthPx = sizeToWidth(size);

  // -- Portal root ---------------------------------------------------------
  const portalRoot =
    document.getElementById('modal-root') ??
    (() => {
      const el = document.createElement('div');
      el.setAttribute('id', 'modal-root');
      document.body.appendChild(el);
      return el;
    })();

  return ReactDOM.createPortal(
    <AnimatePresence>
      <Backdrop
        key="backdrop"
        initial="hidden"
        animate="visible"
        exit="hidden"
        variants={backdropVariants}
        onClick={handleBackdropClick}
        onKeyDown={escHandler}
        style={{ zIndex }}
        theme={theme}
        aria-hidden={true}
      >
        <Surface
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={aria.labelledBy}
          aria-describedby={aria.describedBy}
          variants={modalVariants}
          initial="hidden"
          animate="visible"
          exit="exit"
          widthPx={widthPx}
          theme={theme}
          onKeyDown={handleKeyDown}
          css={
            size === 'fullscreen' &&
            css`
              width: 100vw !important;
              height: 100vh !important;
              max-height: 100vh !important;
              border-radius: 0 !important;
            `
          }
        >
          {title && (
            <Header theme={theme}>
              <span id={aria.labelledBy?.toString() || undefined}>
                {title}
              </span>
              {!hideCloseButton && (
                <CloseButton
                  onClick={onClose}
                  aria-label="Close modal"
                  theme={theme}
                >
                  ✕
                </CloseButton>
              )}
            </Header>
          )}
          <Body theme={theme}>{children}</Body>
        </Surface>
      </Backdrop>
    </AnimatePresence>,
    portalRoot
  );
};

// -- Named Sub-components ---------------------------------------------------

Modal.Header = Header;
Modal.Body = Body;
Modal.Footer = Footer;

Modal.displayName = 'Modal';
```