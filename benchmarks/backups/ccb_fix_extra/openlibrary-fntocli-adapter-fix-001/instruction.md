# Fix FnToCLI Adapter Handling of List Inputs and Filesystem Paths

**Repository:** internetarchive/openlibrary
**Language:** Python
**Difficulty:** hard

## Problem

The `FnToCLI` adapter generates a command-line interface from a function signature, but it does not correctly handle parameters that are lists or that represent filesystem paths. Functions expecting a collection of numbers do not receive values in the expected types, and functions expecting an optional list of filesystem paths do not receive `Path`-like objects.

## Key Components

- The `FnToCLI` class — responsible for mapping function signatures to CLI arguments
- Parameter type inference and conversion logic within the adapter

## Task

1. Locate the `FnToCLI` adapter class and understand how it maps function signatures to CLI arguments
2. Fix list parameter handling: when a function defines a parameter as a list of numbers, the CLI should accept multiple values and deliver them as a list of integers
3. Fix path parameter handling: when a function defines an optional list of filesystem paths, values should be converted to `Path`-like objects, and omitting them should yield `None`
4. Ensure the adapter correctly invokes the underlying function with interpreted arguments and returns the function's result
5. Run existing tests to ensure no regressions

## Success Criteria

- List-of-numbers parameters are correctly parsed and passed as `list[int]`
- Optional list-of-paths parameters are correctly parsed as `list[Path]` or `None`
- The adapter correctly invokes the underlying function and returns its result
- All existing tests pass

