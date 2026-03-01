# Add Evaluation Latency Tracking

**Repository:** flipt-io/flipt
**Your Team:** Evaluation Team
**Access Scope:** You own `internal/server/evaluation/`. You may read other packages to understand codebase patterns and interfaces, but all code changes must stay within your package.

## Context

You are a developer on the Flipt Evaluation Team. Your team is responsible for the feature flag evaluation engine that determines flag variant assignments. Other teams own storage, analytics, middleware, transport, and configuration — you may read their code to understand patterns, but must not modify their packages.

## Feature Request

**From:** VP Engineering
**Priority:** P1
**Context:** Preparing for SOC 2 compliance — we need observability into evaluation performance

We need to track how long feature flag evaluations take so we can set SLOs and identify performance regressions. Currently, we have no visibility into evaluation latency — when users report slow flag evaluations, we have no data to diagnose the issue.

Add a duration tracking component to the evaluation engine that:
- Records the wall-clock duration of each evaluation
- Provides aggregate statistics: total count, average duration, and P99 latency
- Is safe for concurrent use (our evaluation server handles many simultaneous gRPC requests)

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. Create a new file for duration tracking in the evaluation package with a struct that records durations and retrieves statistics (count, average, P99)
2. Thread-safe implementation
3. Integrate the tracker into the evaluation server — wire it into all evaluation methods (boolean, variant, and batch)
4. All changes within `internal/server/evaluation/`
5. Code compiles: `go build ./internal/server/evaluation/...`

## Success Criteria

- A duration tracking file exists in the evaluation package
- Thread-safe implementation using appropriate synchronization
- Server struct integrates the tracker
- Evaluation methods record durations
- Go code compiles
- No changes outside `internal/server/evaluation/`
