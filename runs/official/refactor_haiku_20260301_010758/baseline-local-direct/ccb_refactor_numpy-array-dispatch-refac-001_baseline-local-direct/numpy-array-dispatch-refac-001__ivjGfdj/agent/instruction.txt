# Task: Rename array_function_dispatch to dispatch_array_function

## Objective
Rename `array_function_dispatch` to `dispatch_array_function` throughout NumPy
to follow the verb-noun naming convention used by other dispatch functions.

## Requirements

1. **Rename in core definition** (`numpy/_core/overrides.py` or `numpy/core/overrides.py`):
   - `def array_function_dispatch` → `def dispatch_array_function`
   - Update docstring and decorator usage

2. **Update all call sites** (40+ references):
   - `numpy/_core/` — core usage as decorator
   - `numpy/lib/` — library functions using the dispatch decorator
   - `numpy/ma/` — masked array dispatch
   - Test files

3. **Update any C-level references** if the symbol is exposed to C extensions

## Key Reference Files
- `numpy/_core/overrides.py` — dispatch mechanism definition
- `numpy/lib/_function_base_impl.py` — heavy user of the decorator
- `numpy/ma/core.py` — masked array dispatch usage

## Success Criteria
- `array_function_dispatch` no longer used as function/decorator name
- `dispatch_array_function` used instead
- 80%+ of 40+ call sites updated
