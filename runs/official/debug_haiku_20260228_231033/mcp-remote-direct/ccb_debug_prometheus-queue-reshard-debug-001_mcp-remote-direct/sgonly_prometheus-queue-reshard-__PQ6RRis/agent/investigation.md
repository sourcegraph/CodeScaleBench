# Investigation Report: Remote-Write Queue Resharding Failure

## Summary

Resharding of remote-write queues causes samples to stall because of a race condition where in-flight samples don't properly update the `prometheus_remote_storage_samples_pending` metric when the shard context is cancelled during resharding. Samples that fail to send due to context cancellation bypass the metrics update, leaving the pending counter stuck at a non-zero value while new samples accumulate.

## Root Cause

### The Race Condition: Lost Metric Updates During Resharding

**Location:** `storage/remote/queue_manager.go`

The root cause involves a timing race between sample metrics tracking and context cancellation during resharding:

1. **Samples Enqueued & Metric Incremented** (lines 1320-1327):
   - When `enqueue()` adds a sample, it increments `pendingSamples.Inc()`
   - These samples are queued in the old shard's `queue.batch` or sent directly

2. **Resharding Triggered** (lines 1057-1082 `updateShardsLoop`):
   - The `calculateDesiredShards()` function detects need to reshard
   - Sends new shard count to `reshardChan`

3. **Context Cancellation During Send** (lines 1184-1199 `reshardLoop`):
   - `stop()` is called, which closes `softShutdown` and calls `hardShutdown()`
   - `hardShutdown()` cancels the context for all active shard goroutines
   - `start()` resets `pendingSamples` to 0 (line 1241)

4. **Lost Metric Updates** (lines 1789-1792, 1911-1914):
   ```go
   if errors.Is(err, context.Canceled) {
       // When there is resharding, we cancel the context for this queue, which means the data is not sent.
       // So we exit early to not update the metrics.
       return accumulatedStats, err
   }
   ```
   - **Critical Bug**: Samples in `sendSamplesWithBackoff()` that receive `context.Canceled` exit early WITHOUT calling `updateMetrics()`
   - These samples already incremented `pendingSamples` during enqueue
   - Their metrics are never decremented, leaving `pendingSamples` stuck >0

### Why It's Intermittent

The race condition is intermittent because:

1. **Timing Dependent**: The bug only manifests if samples are in-flight (inside `sendSamplesWithBackoff()`) when `hardShutdown()` is called
2. **Network Latency**: Slower remote-write endpoints increase the window when samples are in-flight
3. **Queue Backpressure**: High sample ingestion rate means more samples are likely to be in-flight during resharding
4. **Batch Boundaries**: Samples at batch boundaries have different timing characteristics

### Secondary Issue: Metrics Reset

**Location:** `storage/remote/queue_manager.go:1241`
```go
s.qm.metrics.pendingSamples.Set(0)
```

When `start()` initializes new shards, it unconditionally resets `pendingSamples` to 0. This assumes all old shards have finished flushing, but:
- If `stop()` times out with a hard shutdown, samples may still be in-flight
- Old shard goroutines may still be executing `updateMetrics()`
- These updates would then decrement from 0, creating negative values or metric inconsistencies

## Evidence

### Key Code References

1. **Sample Enqueue** (queue_manager.go:1320-1327):
   - `pendingSamples.Inc()` called for every enqueued sample
   - Tracked per shard in `enqueuedSamples` (line 1327)

2. **Context Cancellation in Resharding** (queue_manager.go:1563-1578):
   - When `ctx.Done()` (hard shutdown) is triggered, samples are dropped
   - Metrics ARE properly updated in this path

3. **Send Failure Path - NO Metrics Update** (queue_manager.go:1789-1792, 1911-1914):
   - `sendSamplesWithBackoff()` returns early on `context.Canceled`
   - Does NOT call `updateMetrics()` to decrement `pendingSamples`
   - Only `updateMetrics()` decrements the pending counters (queue_manager.go:1689)

4. **Hard Shutdown Trigger** (queue_manager.go:1269-1305):
   - `stop()` closes `softShutdown` and calls `hardShutdown()`
   - Waits with timeout for queues to flush
   - Times out and cancels context if not done quickly enough

5. **Bugfix References** (CHANGELOG.md):
   - Line 925: "[BUGFIX] Remote-write: Fix deadlock between adding to queue and getting batch. #10395"
   - Line 451: "[ENHANCEMENT] Remote Write: Disable resharding during active retry backoffs #13562"
   - Line 1457: "[BUGFIX] Remote Write: Fixed blocked resharding edge case. #7122"

### Metric That Would Confirm Issue

Check these diagnostic metrics:
1. `prometheus_remote_storage_samples_pending{remote_name="..."}` - stuck >0
2. `prometheus_remote_storage_samples_dropped_total` - should increase on hard shutdown
3. `prometheus_remote_storage_samples_failed_total` - may not increment if metrics update is skipped
4. Log messages: "Resharding queues", "Resharding done" - timing relative to stuck pending samples

## Affected Components

### Primary Components
- **`storage/remote/queue_manager.go`** (core resharding logic)
  - `QueueManager.reshardLoop()` (lines 1184-1199)
  - `shards.stop()` (lines 1269-1305)
  - `shards.start()` (lines 1237-1266)
  - `shards.runShard()` (lines 1491-1602)
  - `shards.sendSamplesWithBackoff()` (lines 1698-1808)
  - `shards.sendV2SamplesWithBackoff()` (lines 1811-1920)
  - `shards.updateMetrics()` (lines 1661-1695)

### Affected Packages
- `storage/remote` - remote write queue management
- `config` - QueueConfig with MinShards/MaxShards settings
- Metrics exported via `prometheus` client library

### Related Tests
- `TestReshardRaceWithStop()` (queue_manager_test.go:553) - stress tests resharding race
- `TestQueue_FlushAndShutdownDoesNotDeadlock()` (queue_manager_test.go:1787) - deadlock prevention

## Recommendation

### Fix Strategy

**Primary Fix**: Ensure metrics are updated for all samples regardless of how they exit

1. **For samples in-flight during context cancellation**:
   - Track samples that enter `sendSamplesWithBackoff()` but don't complete
   - On context cancellation, still call `updateMetrics()` with the correct sample count
   - Mark these as "failed" in metrics but ensure `pendingSamples` is decremented

2. **For pending samples tracking**:
   - Don't reset `pendingSamples.Set(0)` in `start()`
   - Instead, only update it after all old shards have fully completed
   - Consider adding synchronization between old shard completion and new shard initialization

3. **Prevent the race entirely**:
   - Ensure `stop()` fully completes before `start()` is called
   - Add assertion that all old shards have finished before resetting metrics
   - Consider tracking in-flight sample count separately

### Diagnostic Steps to Confirm Root Cause

1. **During resharding, check**:
   - Are samples stuck in pending while no new sends are attempted?
   - Do logs show "Resharding done" followed by metrics stuck >0?
   - Is there correlation with network latency or remote endpoint issues?

2. **Check metrics timeline**:
   ```promql
   rate(prometheus_remote_storage_samples_pending[30s])
   # Should be 0 if no new samples. Positive value indicates traffic.
   ```

3. **Check shard transitions**:
   ```promql
   prometheus_remote_storage_num_shards  # Changes during resharding
   ```

4. **Enable debug logging**:
   - Set log level to debug to capture detailed resharding timestamps
   - Correlate with exact moment `pendingSamples` gets stuck

5. **Test with network latency**:
   - Introduce artificial latency to remote endpoint
   - Trigger target discovery changes to force resharding
   - Observe if `samples_pending` gets stuck during resharding

### Prevention

Until fixed:
- Avoid frequent target discovery changes that trigger resharding
- Increase `flushDeadline` in queue config to allow longer for samples to flush
- Use fixed number of shards if possible (set `min_shards` = `max_shards`)
- Monitor `prometheus_remote_storage_samples_pending` for stuck values post-resharding

## Additional Notes

The issue is particularly problematic because:
1. It's a silent failure - no error is logged when metrics become inconsistent
2. Samples aren't actually lost (they're sent), but the metric makes it appear they are
3. This breaks Prometheus's remote-write reliability guarantees at the observability level
4. Affects alerting and troubleshooting since the metric is inaccurate
