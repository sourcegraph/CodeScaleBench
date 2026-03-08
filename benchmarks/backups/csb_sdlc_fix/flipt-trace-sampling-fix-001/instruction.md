# Add Sampling Ratio and Propagator Configuration to Trace Instrumentation

**Repository:** flipt-io/flipt
**Language:** Go
**Difficulty:** hard

## Problem

The current OpenTelemetry instrumentation in Flipt generates all traces with a fixed configuration: it always samples at 100% and applies a predefined set of context propagators. Users cannot adjust how many traces are collected or choose which propagators to use, which limits observability flexibility and causes excessive trace data in production environments.

## Key Components

- OpenTelemetry/tracing initialization — where the tracer provider and sampling strategy are configured
- Configuration schema — where tracing settings are defined and validated
- Propagator setup — where context propagation formats are registered

## Task

1. Add a configurable sampling rate parameter (numeric value in the inclusive range 0–1) to the tracing configuration
2. Add a configurable propagators list to the tracing configuration, limited to supported options
3. Validate inputs: sampling rate must be in [0, 1], propagators must be from supported options
4. Apply sensible defaults when settings are omitted (100% sampling, standard propagators)
5. Produce clear error messages for invalid configuration values
6. Run existing tests to ensure no regressions

## Success Criteria

- Trace sampling rate is configurable via the config schema
- Context propagators are configurable via the config schema
- Invalid values produce clear validation errors
- Omitted values use sensible defaults
- All existing tests pass

