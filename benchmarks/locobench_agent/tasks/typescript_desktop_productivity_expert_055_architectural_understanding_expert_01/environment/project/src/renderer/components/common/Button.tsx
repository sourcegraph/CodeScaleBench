```typescript
// PaletteFlow Studio ─ Button.tsx
// ================================================================
// A highly-configurable, theme-aware button component used across
// PaletteFlow Studio’s renderer layer. The component supports the
// following advanced features:
//
// • Variants (primary, secondary, danger, ghost, text).
// • Sizes (xs, sm, md, lg).
// • Loading state with animated spinner.
// • Disabled state with full a11y compliance.
// • Keyboard-shortcut hint tooltip (e.g. “⌘ S”).
// • Focus-ring + high-contrast handling for accessibility.
// • Forwarded ref + polymorphic `as` prop (default: HTMLButtonElement).
// • Automatic detection of ⌘/Ctrl-key symbol depending on platform.
//
// Dependencies: react, styled-components, polished, @paletteflow/shared-ui
// ========================================================================

import React, {
  ForwardedRef,
  HTMLAttributes,
  MouseEventHandler,
  ReactElement,
  ReactNode,
  forwardRef,
  useMemo,
} from 'react';
import styled, { css, keyframes } from 'styled-components';
import { darken, transparentize } from 'polished';
import { Tooltip } from '@paletteflow/shared-ui/Tooltip';
import { VisuallyHidden } from '@paletteflow/shared-ui/VisuallyHidden';

// ---------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------

export type ButtonSize = 'xs' | 'sm' | 'md' | 'lg';
export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost' | 'text';

interface BaseButtonProps extends HTMLAttributes<HTMLElement> {
  children?: ReactNode;
  icon?: ReactElement;
  /**
   * Where should the icon be rendered?
   * – 'left': before the children
   * – 'right': after the children
   */
  iconPosition?: 'left' | 'right';
  loading?: boolean;
  disabled?: boolean;
  size?: ButtonSize;
  variant?: ButtonVariant;
  /**
   * Optional keyboard shortcut to show in the tooltip.
   * Example: 'meta+s', 'ctrl+shift+k'
   */
  shortcut?: string;
  /**
   * If provided, a tooltip is rendered on hover/focus.
   * Falls back to `shortcut` if no custom tooltip text is given.
   */
  tooltip?: string;
  onClick?: MouseEventHandler<HTMLElement>;
}

/**
 * Polymorphic component props helper.
 * @template T - Element type
 */
type PolymorphicProps<T extends React.ElementType> = BaseButtonProps & {
  as?: T;
} & React.ComponentPropsWithoutRef<T>;

// ---------------------------------------------------------------------
// Styled helpers
// ---------------------------------------------------------------------

const sizes: Record<ButtonSize, { height: number; paddingX: number; fontSize: number }> = {
  xs: { height: 24, paddingX: 8, fontSize: 12 },
  sm: { height: 30, paddingX: 12, fontSize: 13 },
  md: { height: 36, paddingX: 16, fontSize: 14 },
  lg: { height: 44, paddingX: 20, fontSize: 16 },
};

const pulse = keyframes`
  0%   { opacity: .3; }
  50%  { opacity: .6; }
  100% { opacity: .3; }
`;

/**
 * Resolve variant-specific colors based on theme.
 */
const variantStyles = (variant: ButtonVariant, theme: any) => {
  const palette = theme.colors;
  switch (variant) {
    case 'primary':
      return css`
        background: ${palette.accent};
        color: ${palette.accentText};
        &:hover:not(:disabled) {
          background: ${darken(0.04, palette.accent)};
        }
        &:active:not(:disabled) {
          background: ${darken(0.06, palette.accent)};
        }
      `;
    case 'secondary':
      return css`
        background: ${palette.surface2};
        color: ${palette.text};
        &:hover:not(:disabled) {
          background: ${darken(0.06, palette.surface2)};
        }
        &:active:not(:disabled) {
          background: ${darken(0.08, palette.surface2)};
        }
      `;
    case 'danger':
      return css`
        background: ${palette.danger};
        color: ${palette.dangerText};
        &:hover:not(:disabled) {
          background: ${darken(0.05, palette.danger)};
        }
        &:active:not(:disabled) {
          background: ${darken(0.08, palette.danger)};
        }
      `;
    case 'ghost':
      return css`
        background: transparent;
        color: ${palette.text};
        &:hover:not(:disabled) {
          background: ${transparentize(0.9, palette.text)};
        }
        &:active:not(:disabled) {
          background: ${transparentize(0.85, palette.text)};
        }
      `;
    case 'text':
    default:
      return css`
        background: transparent;
        color: ${palette.textSoft};
        &:hover:not(:disabled) {
          color: ${palette.text};
          background: ${transparentize(0.92, palette.text)};
        }
        &:active:not(:disabled) {
          background: ${transparentize(0.88, palette.text)};
        }
      `;
  }
};

const Base = styled.button<Required<Pick<BaseButtonProps, 'size' | 'variant' | 'loading'>>>`
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  outline: none;
  cursor: pointer;
  user-select: none;
  border-radius: ${({ theme }) => theme.radii.sm}px;
  font-family: ${({ theme }) => theme.fonts.sans};
  font-weight: 500;
  transition: background-color 120ms ease-out, box-shadow 120ms ease-out,
    color 120ms ease-out, opacity 120ms ease-out;
  ${({ size }) => {
    const s = sizes[size];
    return css`
      height: ${s.height}px;
      padding: 0 ${s.paddingX}px;
      font-size: ${s.fontSize}px;
      line-height: 1;
      min-width: ${s.height}px;
    `;
  }}
  ${({ variant, theme }) => variantStyles(variant, theme)};
  &:focus-visible {
    box-shadow: 0 0 0 3px ${({ theme }) => transparentize(0.6, theme.colors.accent)};
  }
  &:disabled,
  &[aria-disabled='true'] {
    cursor: not-allowed;
    opacity: 0.65;
  }
  /* Loading state - hide content */
  ${({ loading }) =>
    loading &&
    css`
      & > span,
      & > svg {
        opacity: 0;
      }
    `}
`;

// Spinner (pure CSS)
/* eslint-disable react/no-array-index-key */
const Spinner = styled.div<{ sizePx: number }>`
  position: absolute;
  width: ${({ sizePx }) => sizePx}px;
  height: ${({ sizePx }) => sizePx}px;
  border-radius: 50%;
  border: 2px solid transparent;
  border-top-color: ${({ theme }) => theme.colors.text};
  animation: ${pulse} 1s cubic-bezier(0.68, -0.55, 0.27, 1.55) infinite;
`;

// ---------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------

/**
 * Detect platform and replace occurrences of 'meta'/'cmd'/'ctrl' with
 * platform-appropriate symbol for display in tooltips.
 */
function normalizeShortcut(shortcut?: string): string | undefined {
  if (!shortcut) return;
  const isMac = /mac/i.test(navigator.userAgent);
  const replacements: Record<string, string> = isMac
    ? { meta: '⌘', cmd: '⌘', ctrl: '^', shift: '⇧', alt: '⌥', option: '⌥' }
    : { meta: 'Ctrl', cmd: 'Ctrl', ctrl: 'Ctrl', shift: 'Shift', alt: 'Alt', option: 'Alt' };

  return shortcut
    .split('+')
    .map((part) => replacements[part.toLowerCase()] ?? part)
    .join(isMac ? '' : '+');
}

/**
 * Button component used across renderer. Polymorphic via `as` prop.
 */
function InternalButton<T extends React.ElementType = 'button'>(
  props: PolymorphicProps<T>,
  ref: ForwardedRef<any>
) {
  const {
    children,
    icon,
    iconPosition = 'left',
    loading = false,
    disabled = false,
    size = 'md',
    variant = 'primary',
    shortcut,
    tooltip,
    as,
    onClick,
    ...rest
  } = props as PolymorphicProps<any>;

  // Compose final disabled state.
  const isDisabled = disabled || loading;

  // Pre-compute tooltip content for performance.
  const tooltipContent = useMemo(() => tooltip || normalizeShortcut(shortcut), [tooltip, shortcut]);

  const content = (
    <>
      {/* Icon slot */}
      {icon && iconPosition === 'left' && (
        <span style={{ display: 'inline-flex', marginRight: children ? 6 : 0 }}>{icon}</span>
      )}
      {children && <span>{children}</span>}
      {icon && iconPosition === 'right' && (
        <span style={{ display: 'inline-flex', marginLeft: children ? 6 : 0 }}>{icon}</span>
      )}
    </>
  );

  const body = (
    <Base
      as={as}
      ref={ref}
      role="button"
      aria-busy={loading}
      aria-disabled={isDisabled}
      disabled={typeof as === 'string' && as === 'button' ? isDisabled : undefined}
      size={size}
      variant={variant}
      loading={loading}
      onClick={(e) => {
        if (isDisabled) {
          e.preventDefault();
          return;
        }
        (onClick as MouseEventHandler<HTMLElement>)?.(e);
      }}
      {...rest}
    >
      {content}
      {loading && <Spinner sizePx={size === 'xs' ? 10 : 14} />}
      {/* Screen-reader hint for loading */}
      {loading && <VisuallyHidden>Loading…</VisuallyHidden>}
    </Base>
  );

  // Conditionally wrap with tooltip
  return tooltipContent ? (
    <Tooltip content={tooltipContent} placement="top">
      {body}
    </Tooltip>
  ) : (
    body
  );
}

// ---------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------

/**
 * React-forwarded polymorphic Button component.
 * Usage:
 *    <Button onClick={…} variant="secondary" shortcut="meta+s">
 *      Save
 *    </Button>
 */
const Button = forwardRef(InternalButton) as <T extends React.ElementType = 'button'>(
  p: PolymorphicProps<T> & { ref?: ForwardedRef<any> }
) => ReactElement;

export { Button };
export type { BaseButtonProps as ButtonProps };
```