# Investigation Report: Remote-Write Queue Resharding Failure

## Summary

The remote-write queue resharding mechanism can cause `prometheus_remote_storage_samples_pending` metric to become stuck at non-zero values after resharding occurs. The root cause is a metrics accounting inconsistency where pending samples from old shards are incompletely tracked during the resharding transition, specifically when `start()` resets the global `pendingSamples` gauge to zero while old shard goroutines may still have in-flight samples or pending state updates.

## Root Cause

**File**: `storage/remote/queue_manager.go`
**Primary Issue Location**: Lines 1237-1265 (the `start()` method)
**Specific Problem**: Line 1241 calls `s.qm.metrics.pendingSamples.Set(0)` unconditionally when starting new shards, without accounting for samples that may still be in transit or being processed by old shard goroutines.

### Detailed Mechanism

The remote-write queue resharding process works as follows:

1. **Update Loop** (`updateShardsLoop`, line 1057-1082):
   - Calculates desired shard count every 10 seconds
   - If resharding is needed, sends desiredShards value to `reshardChan`

2. **Reshard Loop** (`reshardLoop`, line 1184-1199):
   ```go
   case numShards := <-t.reshardChan:
       t.shards.stop()          // Stop old shards
       t.shards.start(numShards) // Start new shards
   ```

3. **Stop Sequence** (`stop()`, lines 1269-1305):
   - Closes `softShutdown` channel to prevent new enqueues (line 1275)
   - Calls `FlushAndShutdown()` on all queues to flush partial batches (line 1284)
   - Waits for queues to empty with timeout (flushDeadline, default 30 seconds)
   - If timeout: calls `hardShutdown()` to cancel context (line 1293)
   - Waits for all `runShard` goroutines to exit via `<-s.done` (line 1294)

4. **Start Sequence** (`start()`, lines 1237-1266):
   - **Line 1241**: `s.qm.metrics.pendingSamples.Set(0)` ← **PROBLEMATIC**
   - Creates new queues (lines 1244-1249)
   - Starts new `runShard` goroutines (lines 1263-1265)

### The Race Condition

The issue manifests in this critical window:

```
Timeline of Events:
─────────────────────────────────────────────────────────────────

Time 1: Samples enqueued in old shards
        pendingSamples = 100, enqueuedSamples = 100

Time 2: Some samples sent via HTTP
        updatePersistedState() → pendingSamples = 70, enqueuedSamples = 70

Time 3: Resharding triggered
        stop() called, holding WLock
        ├─ close(softShutdown)
        ├─ FlushAndShutdown() called on queues
        └─ Wait for runShard goroutines to exit

Time 4: Old runShard goroutine receives ctx.Done()
        ├─ droppedSamples := s.enqueuedSamples.Load()  // = 30
        ├─ pendingSamples.Sub(30)  // pendingSamples now = 40
        └─ Exits (running.Dec() triggered)

Time 5: All runShard goroutines exited
        stop() returns, releasing WLock

Time 6: start() called by reshardLoop
        ├─ Acquires WLock
        ├─ pendingSamples.Set(0)  ← OVERWRITES current value!
        ├─ Creates new shards
        └─ Starts new runShard goroutines

PROBLEM: If new samples arrive from WAL before Time 6 completes,
they will increment pendingSamples in Time 6, but Set(0) in Time 6
might overwrite their increment!
```

## Evidence

### Key Code References

1. **Shard Enumeration** (line 315): The base calculation for routing samples to shards:
   ```go
   shard := uint64(ref) % uint64(len(s.queues))
   ```
   When the number of queues changes (4 → 6 shards), the same series reference gets routed differently.

2. **Pending Samples Lifecycle** (lines 1326-1327, 1689-1691, 1569-1571):
   - **Increment**: `s.qm.metrics.pendingSamples.Inc()` during `enqueue()`
   - **Decrement (success)**: `s.qm.metrics.pendingSamples.Sub()` in `updatePersistedState()`
   - **Decrement (error)**: `s.qm.metrics.pendingSamples.Sub()` in ctx.Done() handler
   - **RESET**: `s.qm.metrics.pendingSamples.Set(0)` in `start()`

3. **Synchronization Issues** (lines 1237-1265, 1269-1305):
   - The `stop()` method waits for all shards to exit but has a timeout mechanism
   - The `start()` method blindly resets metrics without considering in-flight operations
   - There's no atomic transaction grouping the "stop old → start new" operation

4. **Enqueue Retry Loop** (lines 731-755 in `Append()`):
   ```go
   for {
       if t.shards.enqueue(...) {
           continue outer
       }
       // Backs off and retries if shards are shutting down
       time.Sleep(time.Duration(backoff))
       backoff *= 2
   }
   ```
   During resharding, samples may be retried but lose their original accounting if metrics are reset mid-transition.

## Affected Components

- **`storage/remote/queue_manager.go`**:
  - `QueueManager.Start()` - Spawns `updateShardsLoop()` and `reshardLoop()`
  - `QueueManager.Append()` - Enqueues samples to shards
  - `QueueManager.updateShardsLoop()` - Detects need for resharding
  - `QueueManager.reshardLoop()` - Orchestrates resharding
  - `QueueManager.calculateDesiredShards()` - Determines new shard count
  - `shards.start()` - Creates new shard queues and workers
  - `shards.stop()` - Gracefully shuts down old shards
  - `shards.enqueue()` - Routes samples to individual shards
  - `shards.runShard()` - Worker goroutine that sends batches
  - `updatePersistedState()` - Updates metrics after send attempt

- **Metrics affected**:
  - `prometheus_remote_storage_samples_pending` (gauge)
  - `prometheus_remote_storage_exemplars_pending` (gauge)
  - `prometheus_remote_storage_histograms_pending` (gauge)

- **Related modules**:
  - WAL Watcher (`storage/remote/write.go`) - Feeds samples to queue manager
  - Queue/Batch management - Tracks partial and full batches

## Why the Issue is Intermittent

The issue is intermittent because it requires a specific timing coincidence:

1. **Timing Window**: The race window is very small—only between when old shards exit and when new shards' workers start accepting samples. This window is typically on the order of milliseconds.

2. **Load Dependency**: The issue is more likely to occur when:
   - Target count changes are frequent (triggers more resharding)
   - The flush deadline is reached (forcing context cancellation)
   - High throughput of new samples during resharding
   - Network latency causes HTTP requests to be in flight longer

3. **Shard Rebalancing**: The issue compounds when resharding changes the shard count significantly:
   - 4 → 6 shards: Many series get remapped to different shards
   - Samples for remapped series may be enqueued during the transition
   - The original shard's accounting for those samples gets lost

4. **Backoff Behavior**: The retry backoff in `Append()` (lines 747-754) may mask the issue:
   - Failed enqueues retry with exponential backoff
   - If resharding completes before retry, samples still get sent
   - But accounting discrepancies may persist

## Diagnostic Metrics and Logs

To confirm the root cause, monitor these signals:

### Prometheus Metrics

- **`prometheus_remote_storage_samples_pending`**: Should gradually decrease when remote storage is healthy. Will get stuck if resharding accounting fails.
- **`prometheus_remote_storage_enqueue_retries_total`**: Sharp increase during resharding indicates samples are retrying enqueues.
- **`prometheus_remote_storage_sent_samples_total`**: Compare against `samples_pending` to identify gaps.

### Log Patterns Indicating the Bug

```
# Normal resharding
level=info msg="Remote storage resharding" from=4 to=6
level=info msg="Resharding done" numShards=6
level=info msg="Remote storage started."

# With the bug
level=info msg="Remote storage resharding" from=4 to=6
level=info msg="Resharding done" numShards=6
# Then samples_pending becomes stuck at non-zero
# No more sends appear in logs despite samples being pending
```

### Debugging Recommendations

1. **Add Instrumentation**:
   - Log `pendingSamples.Load()` before and after `Set(0)` in `start()`
   - Log `enqueuedSamples.Load()` for each shard when it exits
   - Track time delta between `stop()` returning and `start()` being called

2. **Observe These Metrics**:
   ```
   prometheus_remote_storage_samples_pending > 0 &&
   prometheus_remote_storage_sent_samples_total not increasing
   ```

3. **Check Log Timing**:
   - Look for "Resharding done" followed by no "samples flushed" messages
   - Identify if hard shutdown was triggered (flush deadline exceeded)

## Recommendation

### Fix Strategy

The root cause can be fixed by one of these approaches:

1. **Approach A: Don't reset metrics**
   - Remove `Set(0)` from `start()`
   - Instead, let old shards properly decrement before creating new ones
   - Ensures sample accounting stays consistent across transition
   - Risk: pendingSamples might accumulate if old samples aren't fully accounted

2. **Approach B: Atomic transition with carryover**
   - Before `Set(0)`, read current `pendingSamples` value
   - After creating new queues, restore any samples that were in-flight
   - More complex but preserves accuracy

3. **Approach C: Wait-and-verify pattern**
   - After `stop()` returns, verify that `enqueuedSamples.Load() == 0` for all old shards
   - Only then call `start()` to create new shards
   - Add timeout with hard error if accounting is inconsistent
   - Most robust but may delay resharding

4. **Approach D: Per-shard pending counters** (Best long-term)
   - Move away from global `pendingSamples` gauge
   - Use per-shard pending samples tracking
   - Aggregate to global for metrics
   - Avoids transitions entirely by having independent shard tracking

### Verification After Fix

1. Run existing tests: `TestReshard`, `TestReshardRaceWithStop`, `TestReshardPartialBatch`
2. Add stress test with:
   - Frequent resharding while under load
   - Verify `samples_pending` never stays stuck > 0
   - Monitor that all samples eventually send
3. Verify metrics continuity:
   - `samples_pending + sent_samples_total + failed_samples_total` should equal initial enqueued count

## Related Issues

- Issue #14405: "Handle or log error if no metadata is found" (referenced in code but separate)
- Potential impact on: remote-write reliability, metrics accuracy, autoscaling of shard counts
