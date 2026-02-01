```javascript
/**
 * PulseLearn Campus Hub
 * ----------------------------------------
 * Common Spinner component used across the front-end
 *
 * This component is purposely framework-agnostic—relying only on React and
 * styled-components—so that it can be imported by any page, modal, or widget
 * that needs a visual “loading” indicator while awaiting asynchronous data.
 *
 * It supports multiple sizes, theme-aware color variants, optional full-screen
 * overlays, and accessibility attributes out-of-the-box.
 */

import React, { memo } from 'react';
import PropTypes from 'prop-types';
import styled, { keyframes, css, useTheme } from 'styled-components';

/* -------------------------------------------------------------------------- */
/*                               Helper Methods                               */
/* -------------------------------------------------------------------------- */

/**
 * Maps the `size` prop into a concrete pixel dimension.
 * Accepts string presets (`sm`, `md`, `lg`) or a numeric value.
 * @param {'sm'|'md'|'lg'|number} size
 * @returns {number} pixel size
 */
function resolveSize(size) {
  const SIZE_PRESETS = { sm: 24, md: 40, lg: 64 };

  if (typeof size === 'number') {
    return size;
  }

  if (size in SIZE_PRESETS) {
    return SIZE_PRESETS[size];
  }

  // Fallback for unexpected input
  console.warn(
    `[Spinner] Invalid size="${size}" provided. Falling back to default medium size.`
  );
  return SIZE_PRESETS.md;
}

/* -------------------------------------------------------------------------- */
/*                             Styled Components                              */
/* -------------------------------------------------------------------------- */

const spinKeyframes = keyframes`
  0%   { transform: rotate(0deg);   }
  100% { transform: rotate(360deg); }
`;

/**
 * Dynamically calculates colors based on theme + variant.
 * Variant hierarchy:  explicit prop  -> theme.palette.primary.main  -> hardcoded fallback
 */
const ringColor = (theme, variant) => {
  // prettier-ignore
  const palette = (theme && theme.palette) || {};
  switch (variant) {
    case 'secondary': return palette.secondary?.main || '#6c757d';
    case 'success':   return palette.success?.main   || '#28a745';
    case 'danger':    return palette.error?.main     || '#dc3545';
    case 'warning':   return palette.warning?.main   || '#ffc107';
    case 'info':      return palette.info?.main      || '#17a2b8';
    case 'light':     return palette.grey?.[100]     || '#f8f9fa';
    case 'dark':      return palette.grey?.[900]     || '#343a40';
    case 'primary':
    default:          return palette.primary?.main   || '#007bff';
  }
};

/**
 * Spinner circle.  Using border-based animation to keep DOM lightweight.
 */
const SpinnerRing = styled.div.attrs(({ diameter }) => ({
  style: { width: diameter, height: diameter }
}))`
  border-radius: 50%;
  border: ${({ diameter }) => Math.max(Math.round(diameter / 10), 2)}px solid
    ${({ theme, variant }) => ringColor(theme, variant)}55; /* 33% opacity */
  border-top-color: ${({ theme, variant }) => ringColor(theme, variant)};
  animation: ${spinKeyframes} 0.8s linear infinite;
`;

/**
 * Container around the ring—allows for unified flex alignment.
 */
const Wrapper = styled.div`
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
`;

/**
 * Overlay variant stretches a semi-transparent screen and centers the spinner.
 */
const Overlay = styled.div`
  position: fixed;
  inset: 0;
  z-index: 1600; /* Above modals (default 1500) */
  background: ${({ overlayColor }) =>
    overlayColor ??
    'rgba(255, 255, 255, 0.6)'}; /* Fallback if theme unavailable */

  /* Center child content */
  display: flex;
  align-items: center;
  justify-content: center;

  ${({ blur }) =>
    blur &&
    css`
      backdrop-filter: blur(${typeof blur === 'number' ? `${blur}px` : '4px'});
    `}
`;

const Message = styled.div`
  font-size: 0.85rem;
  color: ${({ theme }) => theme?.palette?.text?.secondary ?? '#6c757d'};
  text-align: center;
`;

/* -------------------------------------------------------------------------- */
/*                              React Component                               */
/* -------------------------------------------------------------------------- */

/**
 * Spinner
 * --------------------------------------------------------------------------
 * @param {Object} props
 * @param {'sm'|'md'|'lg'|number} [props.size='md']               Visual size
 * @param {'primary'|'secondary'|'success'|'danger'|'warning'|
 *         'info'|'light'|'dark'} [props.variant='primary']       Color variant
 * @param {boolean} [props.overlay=false]                         Full-screen overlay
 * @param {string}  [props.message]                               Optional message
 * @param {string}  [props.ariaLabel='Loading']                   ARIA label
 * @param {number|boolean} [props.blur=true]                      Add blur behind overlay
 * @param {string} [props.overlayColor]                           Custom overlay color
 * @returns {JSX.Element}
 */
const Spinner = memo(
  ({
    size = 'md',
    variant = 'primary',
    overlay = false,
    message,
    ariaLabel = 'Loading',
    blur = true,
    overlayColor,
    ...rest
  }) => {
    const theme = useTheme(); // gracefully falls back to undefined
    const diameter = resolveSize(size);

    const core = (
      <Wrapper role="status" aria-label={ariaLabel} {...rest}>
        <SpinnerRing
          variant={variant}
          diameter={diameter}
          theme={theme} /* styled-components theme injection */
        />
        {message && <Message>{message}</Message>}
      </Wrapper>
    );

    if (!overlay) return core;

    // Overlay variant
    return (
      <Overlay
        role="presentation"
        aria-hidden="true"
        overlayColor={overlayColor}
        blur={blur}
      >
        {core}
      </Overlay>
    );
  }
);

/* -------------------------------------------------------------------------- */
/*                             Prop-Types & Export                            */
/* -------------------------------------------------------------------------- */

Spinner.propTypes = {
  size: PropTypes.oneOfType([
    PropTypes.oneOf(['sm', 'md', 'lg']),
    PropTypes.number
  ]),
  variant: PropTypes.oneOf([
    'primary',
    'secondary',
    'success',
    'danger',
    'warning',
    'info',
    'light',
    'dark'
  ]),
  overlay: PropTypes.bool,
  message: PropTypes.string,
  ariaLabel: PropTypes.string,
  blur: PropTypes.oneOfType([PropTypes.bool, PropTypes.number]),
  overlayColor: PropTypes.string
};

export default Spinner;
```