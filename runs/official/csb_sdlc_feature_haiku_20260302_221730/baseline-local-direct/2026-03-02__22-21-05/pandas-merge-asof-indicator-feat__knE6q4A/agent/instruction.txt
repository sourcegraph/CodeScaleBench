# Task: Add indicator Parameter to merge_asof()

## Objective
Add an `indicator` parameter to `pandas.merge_asof()` that creates a column indicating
the merge result, similar to how `pd.merge()` supports `indicator=True`.

## Requirements

1. **Modify `pandas/core/reshape/merge.py`**:
   - Add `indicator` parameter to `merge_asof()` function signature
   - Pass `indicator` through to `_AsOfMerge` class
   - In `_AsOfMerge.__init__()`, store indicator setting
   - After merge, add indicator column showing 'both', 'left_only', or 'right_only'

2. **Update `_AsOfMerge` class**:
   - Accept `indicator` in constructor
   - Implement indicator column generation in `get_result()` or post-processing

3. **Create test additions** in `pandas/tests/reshape/merge/test_merge_asof.py`:
   - Test indicator=True produces _merge column
   - Test indicator with custom name
   - Test indicator values are correct

## Key Reference Files
- `pandas/core/reshape/merge.py` — merge_asof and _AsOfMerge class
- `pandas/core/reshape/merge.py` — _MergeOperation.get_result() for indicator pattern
- `pandas/tests/reshape/merge/test_merge_asof.py` — existing asof merge tests

## Success Criteria
- merge_asof function accepts indicator parameter
- _AsOfMerge class handles indicator
- Indicator column added to result when requested
- Follows existing indicator pattern from pd.merge()
- Test additions present
