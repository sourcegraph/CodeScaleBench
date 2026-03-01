# Task: Rename _engine to _index_engine in Index

## Objective
Rename the `_engine` property/attribute to `_index_engine` in `pandas/core/indexes/base.py`
and all subclasses to avoid naming collisions and improve clarity.

## Requirements

1. **Rename in base class** `pandas/core/indexes/base.py`:
   - `_engine` property → `_index_engine`
   - Update cache decorators and lazy evaluation

2. **Update all subclass overrides** (20+ references):
   - `pandas/core/indexes/range.py`
   - `pandas/core/indexes/multi.py`
   - `pandas/core/indexes/datetimes.py`
   - `pandas/core/indexes/period.py`
   - Internal callers

3. **Update internal callers** that access `._engine`

## Key Reference Files
- `pandas/core/indexes/base.py` — base Index with _engine
- `pandas/core/indexes/range.py` — RangeIndex override
- `pandas/core/indexes/multi.py` — MultiIndex
- `pandas/_libs/index.pyx` — Cython engine implementations

## Success Criteria
- `_engine` no longer used as property name in Index
- `_index_engine` used instead
- Subclass overrides updated
- Internal callers updated (80%+)
