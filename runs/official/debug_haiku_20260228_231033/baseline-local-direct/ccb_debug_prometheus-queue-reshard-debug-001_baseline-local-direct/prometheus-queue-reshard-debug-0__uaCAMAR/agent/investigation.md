# Investigation Report: Remote-Write Queue Resharding Failure

## Summary

Remote-write queue resharding causes intermittent sample loss and metric inconsistency due to premature `pendingSamples` metric reset and shard destination recalculation during the resharding window. When targets are added/removed triggering resharding, samples in flight experience a race condition where old shards are stopped before all pending samples are flushed, while the new shards immediately reset the pending count to zero.

## Root Cause

The root cause is a **race condition and metric accounting bug** in the resharding process at `/workspace/storage/remote/queue_manager.go`:

### Primary Issue: Metric Reset Before Flush Completion (Line 1241)

**Location:** `/workspace/storage/remote/queue_manager.go:1237-1266` (`shards.start()` function)

When resharding initiates:
1. `reshardLoop()` at line 1184 calls `t.shards.stop()` followed immediately by `t.shards.start(numShards)`
2. Inside `start()` at line 1241, the code does:
   ```go
   s.qm.metrics.pendingSamples.Set(0)
   ```

**The problem:** This line resets `pendingSamples` to 0 **regardless of whether old shards have completed flushing**. If samples are still pending in old shard queues or in the flush deadline timeout period (line 1289: `flushDeadline`), resetting the metric creates:
- Loss of visibility into truly pending samples
- Incorrect metric values if those samples later fail during hard shutdown (line 1293)
- Inconsistent state where `pendingSamples` shows 0 but shards still have data queued

### Secondary Issue: Shard Destination Recalculation During Retry (Line 1315)

**Location:** `/workspace/storage/remote/queue_manager.go:1312-1340` (`shards.enqueue()` function)

The shard assignment uses modulo arithmetic:
```go
shard := uint64(ref) % uint64(len(s.queues))  // Line 1315
```

**The problem during resharding:**
1. Thread attempts to enqueue sample with `ref=X` when shards = 4 → calculates `shard = X % 4`
2. `softShutdown` is closed, `enqueue()` returns false at line 1318
3. Thread backs off (lines 730-754, 786-809, etc.) with exponential backoff
4. Meanwhile, `stop()` completes and `start(newShards=6)` is called
5. Thread retries enqueue → now calculates `shard = X % 6`
6. **Same sample gets assigned to a different shard**, violating ordering guarantees

### Tertiary Issue: Hard Shutdown Drops Unaccounted Samples (Lines 1563-1578)

**Location:** `/workspace/storage/remote/queue_manager.go:1491-1578` (`runShard()` function)

When `flushDeadline` timeout expires (line 1289):
1. `hardShutdown()` is called at line 1293, cancelling the context
2. All shard goroutines receive `<-ctx.Done()` at line 1563
3. Samples are immediately dropped at lines 1566-1578 **without being flushed**
4. The sample counts are subtracted from metrics, but if `pendingSamples.Set(0)` was already called, the accounting is inconsistent

## Evidence

### Code References

**Key locations:**

1. **Metric reset bug:**
   - File: `/workspace/storage/remote/queue_manager.go`
   - Function: `shards.start()`
   - Lines: 1237-1266
   - Critical line: 1241 - `s.qm.metrics.pendingSamples.Set(0)`

2. **Shard modulo calculation:**
   - File: `/workspace/storage/remote/queue_manager.go`
   - Function: `shards.enqueue()`
   - Lines: 1312-1340
   - Critical line: 1315 - `shard := uint64(ref) % uint64(len(s.queues))`

3. **Resharding orchestration:**
   - File: `/workspace/storage/remote/queue_manager.go`
   - Function: `reshardLoop()`
   - Lines: 1184-1199
   - Critical lines: 1193-1194 - `t.shards.stop()` followed by `t.shards.start(numShards)`

4. **Flush deadline timeout:**
   - File: `/workspace/storage/remote/queue_manager.go`
   - Function: `shards.stop()`
   - Lines: 1286-1294
   - Timeout and hard shutdown: 1289-1294

5. **Hard shutdown handling:**
   - File: `/workspace/storage/remote/queue_manager.go`
   - Function: `runShard()`
   - Lines: 1563-1578
   - Hard shutdown drops samples without accounting validation

### Enqueue Flow During Resharding

The problematic sequence:
1. **T1:** Append thread calls `enqueue()` with softShutdown open
2. **T2:** Resharding triggered → `softShutdown` closed → `enqueue()` returns false
3. **T3:** Append thread backs off with exponential backoff (`Sleep()` at line 748, 805, 859, 912)
4. **T4:** Meanwhile: `stop()` closes softShutdown and calls `FlushAndShutdown()` on each queue
5. **T5:** If flush exceeds `flushDeadline` (default 30s), `hardShutdown()` cancels context
6. **T6:** `start()` is called, resetting `pendingSamples.Set(0)` **during the flush period**
7. **T7:** Append thread wakes from backoff, calls `enqueue()` again → sample goes to **different shard** due to new queue count
8. **T8:** Old shard samples are dropped on hard shutdown, metrics become inconsistent

## Affected Components

### Primary Package
- **`storage/remote/`** - Queue management and resharding logic
  - `queue_manager.go` - Core QueueManager and shards implementation
  - `queue_manager_test.go` - Existing tests for resharding (TestReshard, TestReshardPartialBatch, TestReshardRaceWithStop)

### Related Packages
- **`storage/remote/client.go`** - WriteClient interface consumers of QueueManager
- **`storage/`** - Storage interface implementations
- **Prometheus core WAL Watcher** - Feeds samples to QueueManager via Append() methods

### Metrics Affected
- `prometheus_remote_storage_samples_pending` - Shows 0 during active resharding even with pending data
- `prometheus_remote_storage_shards` - Correct count of shards but pending samples metric is stale
- `prometheus_remote_storage_enqueue_retries_total` - Incremented during reshape backoffs but ordering not guaranteed

## Why the Issue is Intermittent

The issue is intermittent (non-deterministic) due to timing-dependent race conditions:

1. **Flush deadline variance:** Whether samples flush before the hard shutdown timeout depends on:
   - Remote endpoint response time
   - Network latency
   - Number of pending samples
   - System load at the time of resharding

2. **Backoff timing:** When append retries execute relative to `start()` being called determines if samples go to old or new shards:
   - If retry completes before `start()`, goes to old shard → may be dropped
   - If retry completes after `start()`, goes to new shard → goes to different shard ID

3. **Target discovery timing:** Resharding is triggered by target discovery changes:
   - Large target additions → more samples queued → longer flush times
   - Small target changes → fewer retries needed → different timing

4. **Metric visibility:** Some systems might have slower metric collection, so stalled shards aren't immediately apparent

## Diagnostic Steps and Metrics to Confirm Root Cause

### 1. Detect Metric Inconsistency
Monitor these metrics during resharding:
```
prometheus_remote_storage_samples_pending      # Should never spike to 0 during active sending
prometheus_remote_storage_shards               # Number of active shards
prometheus_remote_storage_enqueue_retries_total # Increments during reshard window
prometheus_remote_storage_failed_samples_total  # Indicates samples dropped
```

**Expected behavior:** `pendingSamples` should never drop to 0 in the middle of data transmission.

### 2. Detect Shard Assignment Drift
Add instrumentation to log shard assignments:
- Before resharding: Log which shard each series reference maps to
- After resharding: Compare if same references map to different shards
- Check if distribution is uneven (some shards receiving more samples than others)

### 3. Logs to Watch For
```
level=info msg="Resharding queues" from=4 to=6
level=info msg="Resharding done" numShards=6
```

After these log lines, check if:
- `pendingSamples` metric goes to 0 briefly
- Any samples fail to send with "dropped on hard shutdown" errors
- Enqueue retries spike during the resharding window

### 4. Timing Analysis
- Measure time between `shards.stop()` and `shards.start()` calls
- Compare against `flushDeadline` (default 30 seconds)
- If resharding happens frequently (< flushDeadline), samples accumulate

### 5. Validate With Tracing
Add traces to capture:
- When `pendingSamples.Set(0)` is called
- Concurrent `enqueue()` operations during reshape window
- Sample counts at hard shutdown vs metric values

## Recommendation

### Root Fix Required
The primary fix is to **NOT reset `pendingSamples` to 0 during resharding** without accounting for in-flight data.

**Proposed approach:**
1. Move `pendingSamples.Set(0)` **after** `stop()` completes and flushes are finalized
2. Track the count of samples from old shards that are still pending when `start()` begins
3. Initialize new shards with remaining pending counts rather than 0

### Secondary Fix Required
Ensure sample destinations remain consistent during the resharing window:
1. Either complete all retries **before** calling `stop()`, or
2. Use **cached shard count** in enqueue retry logic to avoid recalculation

### Short-term Mitigation
- Increase `FlushDeadline` configuration to reduce hard shutdown timeouts
- Reduce `calculateDesiredShards()` frequency to minimize resharding
- Monitor `prometheus_remote_storage_samples_pending` for unexpected zeros
- Alert on large spikes in `enqueue_retries_total`

### Testing Improvements
Current tests exist but don't validate:
- Metric consistency across resharding (TestReshard, TestReshardPartialBatch)
- That all enqueued samples are accounted for
- That pending samples never mysteriously become 0
- That shard assignments remain deterministic during resharding

Add tests that:
1. Verify `pendingSamples == sum(samples_in_all_shard_queues)` before and after resharding
2. Confirm samples never change destination shard during retry windows
3. Assert hard shutdown doesn't drop samples that were already counted in metrics
