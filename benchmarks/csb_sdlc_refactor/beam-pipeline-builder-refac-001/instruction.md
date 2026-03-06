# Task: Refactor PipelineOptions Validation in Apache Beam

## Background
The PipelineOptions validation in Apache Beam is scattered across multiple locations. This task consolidates validation into a dedicated validator class using the Builder pattern.

## Objective
Create a `PipelineOptionsValidator` class that centralizes validation for PipelineOptions, replacing scattered validation calls.

## Steps
1. Study the existing PipelineOptions interface in `sdks/java/core/src/main/java/org/apache/beam/sdk/options/`
2. Identify validation logic in `PipelineOptionsFactory` and `PipelineOptionsValidator` (if exists)
3. Create `/workspace/sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptionsValidator.java` with:
   - A Builder that accumulates validation rules
   - Methods: `validateRequired()`, `validateType()`, `validateRange()`
   - A `validate()` method that runs all accumulated rules and returns a `ValidationResult`
4. Create a `ValidationResult` class that holds errors and warnings
5. Create a test file for the validator

## Key Reference Files
- `sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptions.java`
- `sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptionsFactory.java`

## Success Criteria
- PipelineOptionsValidator.java exists with Builder pattern
- ValidationResult class exists
- Test file exists
- Validator has validateRequired, validateType, and validate methods
