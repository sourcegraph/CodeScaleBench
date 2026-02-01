import React, { useCallback, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import styled, { css } from 'styled-components';
import { darken, rgba } from 'polished';
import { FiLoader } from 'react-icons/fi';

import useAnalytics from '../../hooks/useAnalytics';

/**
 * PulseButton — robust, reusable UI button.
 *
 * • Design-token driven (variant / size)
 * • Built-in async loading management
 * • Accessible (aria, keyboard, disabled semantics)
 * • Analytics hook integration (optional)
 * • Supports left / right icon, tooltip & full-width
 */

function PulseButton({
  children,
  variant = 'primary',
  size = 'md',
  icon: Icon,
  iconPosition = 'left',
  onClick,
  type = 'button',
  disabled = false,
  loading: loadingProp = false,
  analyticsId,
  fullWidth = false,
  tooltip,
  'aria-label': ariaLabel,
  'data-testid': testId,
  ...rest
}) {
  const [internalLoading, setInternalLoading] = useState(false);
  const isMountedRef = useRef(true);

  // guard setState when component unmounts
  React.useEffect(() => () => { isMountedRef.current = false; }, []);

  const analytics = useAnalytics();
  const loading = loadingProp || internalLoading;

  const handleClick = useCallback(
    async (e) => {
      if (disabled || loading) {
        e.preventDefault();
        return;
      }

      if (analyticsId && analytics) {
        analytics.track('button_click', { id: analyticsId });
      }

      if (typeof onClick === 'function') {
        const result = onClick(e);

        // auto-handle async handlers
        if (result && typeof result.then === 'function') {
          try {
            setInternalLoading(true);
            await result;
          } finally {
            if (isMountedRef.current) setInternalLoading(false);
          }
        }
      }
    },
    [onClick, disabled, loading, analyticsId, analytics]
  );

  const content = useMemo(() => {
    const iconNode = Icon ? (
      <IconWrapper
        $hasChildren={Boolean(children)}
        $position={iconPosition}
        role="img"
        aria-hidden="true"
      >
        <Icon size={20} />
      </IconWrapper>
    ) : null;

    const loader = (
      <IconWrapper role="status" aria-live="polite">
        <FiLoader size={20} className="spin" />
      </IconWrapper>
    );

    return (
      <>
        {loading ? loader : iconPosition === 'left' && iconNode}
        {children && <span>{children}</span>}
        {iconPosition === 'right' && !loading && iconNode}
      </>
    );
  }, [Icon, iconPosition, loading, children]);

  return (
    <StyledButton
      {...rest}
      type={type}
      $variant={variant}
      $size={size}
      $fullWidth={fullWidth}
      disabled={disabled || loading}
      aria-busy={loading}
      aria-label={ariaLabel}
      data-testid={testId}
      title={tooltip}
      onClick={handleClick}
    >
      {content}
    </StyledButton>
  );
}

PulseButton.propTypes = {
  children: PropTypes.node,
  variant: PropTypes.oneOf(['primary', 'secondary', 'danger', 'link', 'ghost']),
  size: PropTypes.oneOf(['sm', 'md', 'lg']),
  icon: PropTypes.elementType,
  iconPosition: PropTypes.oneOf(['left', 'right']),
  onClick: PropTypes.func,
  type: PropTypes.oneOf(['button', 'submit', 'reset']),
  disabled: PropTypes.bool,
  loading: PropTypes.bool,
  analyticsId: PropTypes.string,
  fullWidth: PropTypes.bool,
  tooltip: PropTypes.string,
  'aria-label': PropTypes.string,
  'data-testid': PropTypes.string,
};

export default PulseButton;

/* ---------------------------------------------------------------------
 * Styles
 * -------------------------------------------------------------------*/

const sizes = {
  sm: {
    h: '32px',
    font: '.875rem',
    px: '12px',
  },
  md: {
    h: '40px',
    font: '1rem',
    px: '16px',
  },
  lg: {
    h: '48px',
    font: '1.125rem',
    px: '20px',
  },
};

const variantStyles = {
  primary: ({ palette }) => css`
    background: ${palette.primary.main};
    color: ${palette.primary.contrastText};

    &:hover:not(:disabled) {
      background: ${darken(0.05, palette.primary.main)};
    }
    &:active:not(:disabled) {
      background: ${darken(0.1, palette.primary.main)};
    }
  `,
  secondary: ({ palette }) => css`
    background: ${palette.secondary.main};
    color: ${palette.secondary.contrastText};

    &:hover:not(:disabled) {
      background: ${darken(0.05, palette.secondary.main)};
    }
    &:active:not(:disabled) {
      background: ${darken(0.1, palette.secondary.main)};
    }
  `,
  danger: ({ palette }) => css`
    background: ${palette.error.main};
    color: ${palette.error.contrastText};

    &:hover:not(:disabled) {
      background: ${darken(0.05, palette.error.main)};
    }
    &:active:not(:disabled) {
      background: ${darken(0.1, palette.error.main)};
    }
  `,
  link: ({ palette }) => css`
    background: transparent;
    color: ${palette.primary.main};
    padding: 0;

    &:hover:not(:disabled) {
      text-decoration: underline;
      color: ${darken(0.1, palette.primary.main)};
    }
    &:active:not(:disabled) {
      color: ${darken(0.15, palette.primary.main)};
    }
  `,
  ghost: ({ palette }) => css`
    background: transparent;
    color: ${palette.text.primary};
    border: 1px solid ${rgba(palette.text.primary, 0.18)};

    &:hover:not(:disabled) {
      background: ${rgba(palette.text.primary, 0.05)};
    }
    &:active:not(:disabled) {
      background: ${rgba(palette.text.primary, 0.1)};
    }
  `,
};

const StyledButton = styled.button`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  height: ${({ $size }) => sizes[$size].h};
  min-width: ${({ $size }) => sizes[$size].h};
  padding: 0 ${({ $size }) => sizes[$size].px};
  font-size: ${({ $size }) => sizes[$size].font};
  font-weight: 600;
  line-height: 1;
  border: none;
  border-radius: ${({ theme }) => theme.shape.rounded};
  cursor: pointer;
  transition: background 0.1s ease-in-out, color 0.1s ease-in-out,
    transform 0.05s ease-in-out;
  width: ${({ $fullWidth }) => ($fullWidth ? '100%' : 'auto')};

  ${({ theme, $variant }) => variantStyles[$variant]({ palette: theme.palette })}

  &:disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }

  &:active:not(:disabled) {
    transform: scale(0.97);
  }

  /* loader rotation */
  .spin {
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(1turn);
    }
  }
`;

const IconWrapper = styled.span`
  display: flex;
  line-height: 0;
  ${({ $hasChildren, $position }) =>
    $hasChildren &&
    ($position === 'left'
      ? 'margin-right: .25rem;'
      : 'margin-left: .25rem;')}
`;

/**
 * Expected theme shape:
 * {
 *   palette: {
 *     primary: { main: String, contrastText: String },
 *     secondary: { main: String, contrastText: String },
 *     error: { main: String, contrastText: String },
 *     text: { primary: String }
 *   },
 *   shape: { rounded: String } // e.g., '6px'
 * }
 */
