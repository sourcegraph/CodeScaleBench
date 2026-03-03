# Investigation Report: Remote-Write Queue Resharding Failure

## Summary

The intermittent stalling of remote-write shards after resharding is caused by a **race condition in the metrics counter reset** combined with **asynchronous queue shutdown timing**. When `start()` is called on new shards, it immediately resets `pendingSamples` to zero, but old shards are still in the background flushing data and decrementing this same counter. Additionally, samples enqueued during the transition window between `stop()` and `start()` may end up in queues that are being hard-shutdown before they can be sent.

## Root Cause

**Location:** `storage/remote/queue_manager.go:1237-1266` (`start()` method) and lines 1184-1199 (`reshardLoop()`)

**Mechanism:**

The resharding process has a critical flaw in how it manages the pending samples metric during queue transitions:

1. **Premature Counter Reset** (line 1241):
   ```go
   func (s *shards) start(n int) {
       s.mtx.Lock()
       defer s.mtx.Unlock()
       s.qm.metrics.pendingSamples.Set(0)  // <-- RESETS COUNTER IMMEDIATELY
       ...
   }
   ```
   This resets the counter to 0 immediately when new shards start.

2. **Race with Old Shards Cleanup**:
   ```go
   func (t *QueueManager) reshardLoop() {
       for {
           select {
           case numShards := <-t.reshardChan:
               t.shards.stop()         // Old shards close softShutdown, start flushing
               t.shards.start(numShards)  // New shards created, counter reset to 0
           ...
           }
       }
   }
   ```

   Between `stop()` and `start()`:
   - Old shards close `softShutdown` channel to block new enqueues
   - Old shards begin `FlushAndShutdown()` on their queues
   - If flush takes longer than expected, old shards hard-shutdown via context cancellation
   - **Concurrently**: `start()` resets `pendingSamples` to 0
   - Old shards' `runShard()` goroutines continue decrementing this counter as they finish sending

3. **Hard Shutdown Timeout Behavior** (line 1286-1294):
   ```go
   select {
   case <-s.done:
       return
   case <-time.After(s.qm.flushDeadline):  // Typically 30 seconds
   }
   // Force an unclean shutdown
   s.hardShutdown()  // Cancels context, old runShard goroutines exit
   <-s.done
   ```

   If old shards don't complete flushing within `flushDeadline`:
   - Context is cancelled via `s.hardShutdown()`
   - Remaining samples in old queues are dropped
   - Old `runShard` goroutines decrement `pendingSamples` for these dropped samples
   - But counter was already reset to 0, so it never recovers

## Evidence

### Code References

**File: `storage/remote/queue_manager.go`**

- **Lines 1071-1074** (`updateShardsLoop`): Updates `t.numShards` immediately after sending reshape request, before actual resharding completes
  ```go
  case t.reshardChan <- desiredShards:
      t.logger.Info("Remote storage resharding", "from", t.numShards, "to", desiredShards)
      t.numShards = desiredShards  // <-- Updated before reshardLoop processes it
  ```

- **Lines 1184-1199** (`reshardLoop`): Asynchronously processes reshard requests
  ```go
  func (t *QueueManager) reshardLoop() {
      for {
          select {
          case numShards := <-t.reshardChan:
              t.shards.stop()         // Closes softShutdown, begins flushing
              t.shards.start(numShards)  // Creates new queues, resets counter
          ...
          }
      }
  }
  ```

- **Lines 1237-1266** (`start`): Problematic counter reset
  ```go
  func (s *shards) start(n int) {
      s.mtx.Lock()
      defer s.mtx.Unlock()
      s.qm.metrics.pendingSamples.Set(0)  // BUG: Resets while old shards still active
      ...
      s.queues = newQueues
      ...
      for i := range n {
          go s.runShard(hardShutdownCtx, i, newQueues[i])
      }
  }
  ```

- **Lines 1325-1327** (enqueue): Increments counter when samples enqueued
  ```go
  case tSample:
      s.qm.metrics.pendingSamples.Inc()
      s.enqueuedSamples.Inc()
  ```

- **Lines 1689-1691** (updateMetrics): Decrements counter when samples sent
  ```go
  s.qm.metrics.pendingSamples.Sub(float64(sampleCount))
  ```

- **Lines 1563-1578** (runShard hard shutdown): Drops samples when context cancelled
  ```go
  case <-ctx.Done():
      droppedSamples := int(s.enqueuedSamples.Load())
      s.qm.metrics.pendingSamples.Sub(float64(droppedSamples))  // <-- Sub after Set(0)
      ...
  ```

### Intermittency Explanation

The issue is intermittent because:

1. **Timing-dependent**: The race condition only manifests when:
   - Target discovery changes trigger resharding during active sample ingestion
   - Old shards' flush takes longer than expected (> flushDeadline)
   - New samples are enqueued during the transition window

2. **Load-dependent**: Occurs more frequently under:
   - High sample ingestion rates (more samples in flight during transition)
   - Slow remote storage endpoints (longer flush time for old shards)
   - Frequent target discovery changes (more resharding events)

3. **Scale-dependent**: More visible at:
   - Larger shard counts (more goroutines in transition)
   - Higher capacity configs (more samples buffered in queues)

## Affected Components

1. **`storage/remote/queue_manager.go`**:
   - `QueueManager` struct (manages resharding)
   - `shards` struct (represents parallel send queues)
   - `start()` method (initializes new shards)
   - `stop()` method (shuts down old shards)
   - `reshardLoop()` (processes reshard events)
   - `updateShardsLoop()` (decides when to reshard)
   - `enqueue()` function (enqueues samples to shards)
   - `runShard()` goroutine (sends batches, updates metrics)

2. **`storage/remote` package**:
   - Metrics tracking pending samples
   - WAL watcher integration that calls `Append()`

## Root Cause Analysis: Why Shards Stall

The stalling occurs through this sequence:

1. **Reshape triggered**: Target discovery change → desired shards change (e.g., 4 → 6)

2. **Async reshard starts**:
   ```
   updateShardsLoop sends to reshardChan
   reshardLoop receives: stop() old shards, start() new shards
   ```

3. **Old shards shutdown**:
   - `stop()` closes `softShutdown` channel
   - WAL watcher's `enqueue()` calls fail (return false)
   - New samples in-flight retry with backoff

4. **Critical race - Counter reset**:
   - `start()` acquires write lock
   - Sets `pendingSamples = 0` (line 1241)
   - Creates new queues and starts new `runShard` goroutines
   - Releases lock

5. **Samples enqueued to new shards**:
   - WAL watcher's retries succeed on new shards
   - Samples are `Append()`ed to new queues
   - `pendingSamples` is incremented for each sample

6. **Potential stall scenarios**:

   **Scenario A - Partial batch buffering**:
   - New samples are buffered in queue's partial batch
   - Batch doesn't fill up to capacity
   - Batch timeout (10+ seconds) waiting for more samples
   - If no new samples arrive, `runShard` timer eventually flushes batch

   **Scenario B - Hard shutdown during transition**:
   - Old shards exceed `flushDeadline` waiting to send
   - `hardShutdown()` cancels old context
   - Old `runShard` goroutines exit, dropping queued samples
   - They call `Sub(droppedSamples)` on counter already reset to 0
   - Counter tracking becomes inconsistent

   **Scenario C - Queue channel deadlock**:
   - Sample enqueued during transition window
   - Ends up in old shard's batch that's never flushed
   - Or in new shard queue that runShard never reads from

## Recommendation

### Fix Strategy

The `start()` method should NOT reset `pendingSamples` to 0 unconditionally. Instead:

1. **Preserve old shard metrics**: Don't reset the counter; let old shards naturally decrement it as they complete
2. **Alternative**: Only reset counter AFTER confirming old shards are fully stopped
3. **Or**: Atomically transfer pending count from old shards to new shards

### Diagnostic Steps

To confirm this root cause in a live system:

1. **Monitor these metrics during resharding**:
   - `prometheus_remote_storage_samples_pending` (should not jump to 0)
   - `prometheus_remote_storage_shards` (actual number of shards)
   - `prometheus_remote_storage_shards_desired` (target number)

2. **Enable debug logging** in queue_manager:
   - Watch for "Remote storage resharding" messages
   - Check timestamps against "Resharding done"
   - Look for "(Currently resharding, skipping.)" messages (queue blocked)

3. **Examine for stuck samples**:
   ```promql
   # High pending with zero output rate
   prometheus_remote_storage_samples_pending > 0
   and
   rate(prometheus_remote_storage_samples_total[1m]) == 0

   # Check for specific shards stuck
   prometheus_remote_storage_samples_pending
   without (job, instance) by (shard)
   ```

4. **Look for dropped samples**:
   - Check if `prometheus_remote_storage_samples_failed_total` increased during resharding
   - This would indicate hard shutdown occurred

5. **Check logs for timeout messages**:
   - Search for flush deadline exceeded during resharding
   - These correlate with hard shutdown dropping samples

### Prevention Measures

1. **Increase `flushDeadline`** in queue config if resharding frequently fails
2. **Reduce resharding frequency** by tuning `shardUpdateDuration` (currently 10 seconds)
3. **Monitor resharding events** and correlation with:
   - Target discovery changes
   - Sample ingestion rate spikes
   - Remote storage latency increases

## Related Code

- CHANGELOG.md mentions issue #7122 "Fixed blocked resharding edge case" (line 1457)
- This investigation suggests the fix may have been incomplete or partially reverted
- The core issue of counter reset during transition persists
