# Add Evaluation Duration Tracking to Flipt

**Repository:** flipt-io/flipt
**Your Team:** Evaluation Team
**Access Scope:** You own `internal/server/evaluation/`. You may read `internal/storage/`, `internal/server/analytics/`, `internal/server/middleware/`, `rpc/flipt/evaluation/`, and `internal/config/` to understand contracts and patterns. All code changes must be in `internal/server/evaluation/`.

## Context

You are a developer on the Flipt Evaluation Team. Your team owns the flag evaluation logic in `internal/server/evaluation/`. The Platform Team owns the storage layer (`internal/storage/`), analytics pipeline (`internal/server/analytics/`), and middleware (`internal/server/middleware/`).

Operators need to understand evaluation performance. The evaluation server currently performs flag evaluations (boolean, variant, batch) but does not track how long each evaluation takes. The analytics and middleware teams have already built infrastructure for recording evaluation outcomes — you need to add duration tracking within your package.

## Task

Add evaluation duration tracking to the evaluation server. Each `Boolean()`, `Variant()`, and `Batch()` call should record its wall-clock duration and expose per-flag timing statistics.

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. Create a new file `internal/server/evaluation/duration.go` that defines:
   - A `DurationTracker` struct that records evaluation durations per flag key
   - Fields: a map from flag key to a slice of `time.Duration` values (or summary stats)
   - `RecordDuration(flagKey string, d time.Duration)` method
   - `GetStats(flagKey string) DurationStats` method returning `{Count int64, AvgMs float64, P99Ms float64}`
   - Thread-safe via `sync.RWMutex`

2. Integrate the tracker into the evaluation `Server` struct:
   - Read `internal/server/evaluation/server.go` to understand the existing `Server` struct and its constructor (`New()`)
   - Add a `durations *DurationTracker` field to `Server`
   - Initialize it in the constructor

3. Instrument the evaluation methods:
   - Read `internal/server/evaluation/evaluation.go` to understand `Boolean()`, `Variant()`, and `Batch()` methods
   - At the start of each method, record `start := time.Now()`
   - Before returning, call `s.durations.RecordDuration(flagKey, time.Since(start))`
   - For `Batch()`, record duration for each individual flag evaluation within the batch loop

4. To understand the evaluation flow, you need to trace across packages:
   - `internal/storage/storage.go` defines `EvaluationStore` interface — the `Server` calls methods on this interface
   - `rpc/flipt/evaluation/` defines the protobuf request/response types
   - `internal/server/middleware/grpc/middleware.go` shows how the middleware already instruments evaluations with OpenTelemetry — your duration tracking is complementary (server-side, not middleware-side)
   - `internal/server/analytics/` shows the existing analytics pattern — follow its style for consistency

### Hints

- The `Server` struct in `server.go` is initialized with `New(logger, store)` — add the tracker there
- `evaluation.go` methods like `Boolean()` already have deferred functions for tracing — add duration recording similarly
- The `Batch()` method iterates over a list of requests — track per-flag durations inside the loop
- Look at how `internal/server/analytics/sink.go` defines its interface pattern — follow a similar style for your `DurationTracker`
- Use `sync.RWMutex` — write lock for `RecordDuration()`, read lock for `GetStats()`
- For P99, keep a circular buffer or just track count/sum (full percentile tracking is optional)

## Success Criteria

- New `duration.go` file exists in `internal/server/evaluation/`
- `DurationTracker` struct with `RecordDuration()` and `GetStats()` methods
- Thread-safe implementation using `sync.RWMutex`
- Tracker integrated into `Server` struct and initialized in constructor
- Evaluation methods (`Boolean`, `Variant`, `Batch`) record durations
- Code compiles: `go build ./internal/server/evaluation/...`
- All changes within `internal/server/evaluation/` only
