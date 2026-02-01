```javascript
/**
 * PulseLearn Campus Hub
 * --------------------------------------------
 * Re-usable input component to enforce consistent
 * styling, accessibility, and behavior across the
 * entire application.
 *
 * Capabilities:
 *  • Supports all native <input> types
 *  • Integrates with React-Hook-Form / Formik via `ref`
 *  • Optional debounced onChange to reduce re-renders
 *  • Basic client-side validation + error display
 *  • Password “show / hide” toggle
 *  • Dark / light theme awareness (via CSS variables)
 *
 * NOTE: This component purposefully avoids coupling to
 * any single form library, keeping the surface API small
 * while still being extremely flexible.
 */

import React, {
  forwardRef,
  useId,
  useState,
  useCallback,
  useMemo,
} from 'react';
import PropTypes from 'prop-types';
import debounce from 'lodash.debounce';

import './Input.css'; // uses CSS variables & BEM naming

// Helper: returns appropriate aria-describedby string
const buildDescribedBy = (helperId, errorId, hasError) => {
  const ids = [];
  if (helperId) ids.push(helperId);
  if (hasError && errorId) ids.push(errorId);
  return ids.join(' ') || undefined;
};

/**
 * Custom hook that wraps lodash.debounce but guarantees
 * stable identity across renders and cleans up on unmount.
 */
const useDebouncedCallback = (fn, delay, deps = []) => {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const memoized = useMemo(() => debounce(fn, delay), deps);

  // Cleanup
  React.useEffect(() => () => memoized.cancel(), [memoized]);

  return memoized;
};

const Input = forwardRef(
  (
    {
      id: explicitId,
      name,
      type = 'text',
      label,
      placeholder,
      value,
      defaultValue,
      onChange,
      onBlur,
      debounceDelay,
      required = false,
      disabled = false,
      readOnly = false,
      min,
      max,
      minLength,
      maxLength,
      pattern,
      autoComplete = 'off',
      spellCheck = false,
      helperText,
      error,
      className = '',
      style,
      inputProps = {},
    },
    ref,
  ) => {
    // Fallback to auto-generated id for a11y
    const generatedId = useId();
    const inputId = explicitId || `${name}-${generatedId}`;

    // Show/hide password state
    const [isMasked, setIsMasked] = useState(type === 'password');

    /* ---------------------------------
     * Handlers
     * --------------------------------- */
    const emitChange = useCallback(
      (e) => {
        if (onChange) onChange(e);
      },
      [onChange],
    );

    const debouncedChange = useDebouncedCallback(
      emitChange,
      debounceDelay,
      [emitChange],
    );

    const handleChange = debounceDelay ? debouncedChange : emitChange;

    const toggleMask = () => setIsMasked((prev) => !prev);

    /* ---------------------------------
     * Validation helpers
     * --------------------------------- */
    const inputError = error; // Externally supplied error string
    const hasError = Boolean(inputError);

    const helperId = helperText ? `${inputId}-helper` : undefined;
    const errorId = hasError ? `${inputId}-error` : undefined;

    /* ---------------------------------
     * Render
     * --------------------------------- */
    return (
      <div
        className={`pl-input ${hasError ? 'pl-input--error' : ''} ${disabled ? 'pl-input--disabled' : ''} ${className}`}
        style={style}
      >
        {label && (
          <label className="pl-input__label" htmlFor={inputId}>
            {label} {required && <span className="pl-input__required">*</span>}
          </label>
        )}

        <div className="pl-input__control-wrapper">
          <input
            id={inputId}
            name={name}
            ref={ref}
            type={type === 'password' && !isMasked ? 'text' : type}
            placeholder={placeholder}
            value={value}
            defaultValue={defaultValue}
            onChange={handleChange}
            onBlur={onBlur}
            required={required}
            disabled={disabled}
            readOnly={readOnly}
            min={min}
            max={max}
            minLength={minLength}
            maxLength={maxLength}
            pattern={pattern}
            autoComplete={autoComplete}
            spellCheck={spellCheck}
            aria-describedby={buildDescribedBy(helperId, errorId, hasError)}
            aria-invalid={hasError}
            className="pl-input__control"
            {...inputProps}
          />

          {/* Password visibility toggle */}
          {type === 'password' && !readOnly && !disabled && (
            <button
              type="button"
              aria-label={isMasked ? 'Show password' : 'Hide password'}
              className="pl-input__toggle-mask"
              onClick={toggleMask}
            >
              {isMasked ? '👁️' : '🙈'}
            </button>
          )}
        </div>

        {helperText && (
          <small id={helperId} className="pl-input__helper">
            {helperText}
          </small>
        )}

        {hasError && (
          <small id={errorId} role="alert" className="pl-input__error">
            {inputError}
          </small>
        )}
      </div>
    );
  },
);

Input.displayName = 'Input';

Input.propTypes = {
  id: PropTypes.string,
  name: PropTypes.string.isRequired,
  type: PropTypes.oneOf([
    'text',
    'password',
    'email',
    'number',
    'search',
    'url',
    'tel',
    'date',
    'datetime-local',
  ]),
  label: PropTypes.node,
  placeholder: PropTypes.string,
  value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  defaultValue: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  onChange: PropTypes.func,
  onBlur: PropTypes.func,
  debounceDelay: PropTypes.number,
  required: PropTypes.bool,
  disabled: PropTypes.bool,
  readOnly: PropTypes.bool,
  min: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  max: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  minLength: PropTypes.number,
  maxLength: PropTypes.number,
  pattern: PropTypes.string,
  autoComplete: PropTypes.string,
  spellCheck: PropTypes.bool,
  helperText: PropTypes.node,
  error: PropTypes.string,
  className: PropTypes.string,
  style: PropTypes.object, // eslint-disable-line react/forbid-prop-types
  inputProps: PropTypes.object, // eslint-disable-line react/forbid-prop-types
};

export default React.memo(Input);
```