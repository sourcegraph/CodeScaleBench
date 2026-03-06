# Task: Write Unit Tests for Bazel Starlark Rule Evaluation

## Objective
Write comprehensive unit tests for the Starlark evaluation of rule() calls in BUILD files, covering rule instantiation, attribute validation, and error handling.

## Steps
1. Study the Starlark rule evaluation in `src/main/java/com/google/devtools/build/lib/packages/`
2. Understand how `RuleClass` and `RuleFactory` process rule() calls
3. Study existing tests in `src/test/java/com/google/devtools/build/lib/packages/`
4. Create a test file `StarlarkRuleEvalTest.java` in the test directory with tests for:
   - Basic rule instantiation with required attributes
   - Missing required attribute produces error
   - Attribute type validation (string vs list vs label)
   - Default attribute values are applied
   - Visibility attribute handling
   - Rule name validation (valid and invalid names)

## Key Reference Files
- `src/main/java/com/google/devtools/build/lib/packages/RuleClass.java`
- `src/main/java/com/google/devtools/build/lib/packages/RuleFactory.java`
- `src/test/java/com/google/devtools/build/lib/packages/` — existing tests

## Success Criteria
- Test file exists in the test directory
- Tests cover rule instantiation
- Tests cover attribute validation
- Tests cover error cases
