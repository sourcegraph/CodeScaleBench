# Add OTLP Exporter Support for Tracing

**Repository:** flipt-io/flipt
**Language:** Go
**Difficulty:** hard

## Problem

Flipt currently only supports Jaeger and Zipkin as tracing exporters, limiting observability integration options for teams using OpenTelemetry collectors or other OTLP-compatible backends. Users cannot export trace data using the OpenTelemetry Protocol (OTLP), which is becoming the standard for telemetry data exchange in cloud-native environments. This forces teams to either use intermediate conversion tools or stick with legacy tracing backends.

## Reproduction

1. Enable tracing in Flipt configuration
2. Attempt to set `tracing.exporter: otlp` in configuration
3. Start Flipt service and observe configuration validation errors
4. Note that only `jaeger` and `zipkin` are accepted as valid exporter values

## Key Components

- Tracing exporter initialization — where Jaeger/Zipkin exporters are created
- Configuration schema — where valid exporter values are defined and validated
- Exporter factory/selection logic

## Task

1. Add `otlp` as a supported tracing exporter alongside `jaeger` and `zipkin`
2. When `otlp` is selected, allow configuration of an endpoint (default: `localhost:4317`)
3. Maintain `jaeger` as the default exporter when no exporter is specified
4. Ensure configuration validation accepts all three exporter values without errors
5. Run existing tests to ensure no regressions

## Success Criteria

- Setting `tracing.exporter: otlp` starts the service without validation errors
- OTLP exporter connects to the configured endpoint (or default `localhost:4317`)
- Default behavior (Jaeger) is unchanged when exporter is not specified
- Existing Jaeger and Zipkin configurations continue to work
- All existing tests pass

