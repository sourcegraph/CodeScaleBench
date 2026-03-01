# Task: Implement rolling_median for NumPy

## Objective
Add a `rolling_median` function to `numpy/lib/` that computes a rolling (sliding window)
median over a 1-D array, following NumPy's function dispatch and documentation conventions.

## Requirements

1. **Create `numpy/lib/_rolling_median.py`** (or add to existing stats module):
   - `rolling_median(a, window_size, *, axis=-1, mode='valid')` function
   - Supports 'valid', 'same', and 'full' modes (similar to np.convolve)
   - Handles edge cases: window_size > array length, window_size = 1
   - Uses `@array_function_dispatch` decorator for subclass support
   - Includes NumPy-style docstring with Parameters, Returns, Examples sections

2. **Register in module exports**:
   - Add to `numpy/lib/__init__.py` or appropriate submodule

3. **Create test file** `numpy/lib/tests/test_rolling_median.py`:
   - Test basic rolling median computation
   - Test different modes
   - Test edge cases

## Key Reference Files
- `numpy/lib/_function_base_impl.py` — array function implementations (median, average)
- `numpy/core/overrides.py` — `array_function_dispatch` decorator
- `numpy/lib/_nanfunctions_impl.py` — NaN-aware function patterns
- `numpy/lib/tests/test_function_base.py` — test patterns

## Success Criteria
- rolling_median function exists with proper signature
- Uses array_function_dispatch decorator
- Has NumPy-style docstring
- Handles window_size parameter
- Test file with test functions exists
