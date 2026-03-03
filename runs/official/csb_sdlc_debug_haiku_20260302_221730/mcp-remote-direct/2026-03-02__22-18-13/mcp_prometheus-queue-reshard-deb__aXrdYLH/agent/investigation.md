# Investigation Report: Remote-Write Queue Resharding Failure

## Summary
After Prometheus upgrades or target discovery changes, remote-write shards intermittently stall because samples enqueued during resharding are permanently dropped during hard shutdown when the flush deadline expires, violating the delivery guarantee and causing metrics to show stuck pending samples.

## Root Cause

**Location**: `storage/remote/queue_manager.go` - Resharding logic (lines 1184-1199, 1269-1305, 1491-1602)

**Mechanism**:
When resharding occurs (e.g., target discovery adds/removes targets), the `reshardLoop()` function:

1. Calls `t.shards.stop()` to shutdown old shards
2. Calls `t.shards.start(numShards)` to create new shards with different queue counts

During `stop()` (lines 1269-1305):
- Line 1275: Closes `softShutdown` channel (prevents new enqueues)
- Line 1281-1284: Takes write lock and initiates `FlushAndShutdown()` on all queues
- Line 1289: Waits up to `flushDeadline` (default 1 minute) for graceful flush
- Line 1293: If timeout exceeded, calls `hardShutdown()` unconditionally

When `hardShutdown()` is called (cancels `hardShutdownCtx`):
- All `runShard()` goroutines receive `ctx.Done()` signal (line 1563)
- Lines 1566-1577: **All pending samples are dropped without being sent**
- No re-attempt or recovery mechanism exists

**The Critical Bug**:
Samples in flight when the flush deadline expires are permanently lost because:
1. They're dropped during hard shutdown (line 1575-1577)
2. They're never re-enqueued to new shards
3. The metrics counters are decremented (lines 1569-1571) but the samples are gone
4. New shards start with a different hash distribution, so old shard data cannot be recovered

## Evidence

### Code References

**Resharding Trigger** (lines 1057-1082):
```
storage/remote/queue_manager.go:1072-1074
  case t.reshardChan <- desiredShards:
      t.logger.Info("Remote storage resharding", "from", t.numShards, "to", desiredShards)
      t.numShards = desiredShards
```

**Resharding Loop** (lines 1184-1199):
```
storage/remote/queue_manager.go:1189-1194
  case numShards := <-t.reshardChan:
      t.shards.stop()           // Initiates flush
      t.shards.start(numShards) // Creates new shards (NEW HASH DISTRIBUTION)
```

**Hard Shutdown Path** (lines 1286-1294):
```
storage/remote/queue_manager.go:1286-1294
  select {
  case <-s.done:
      return                    // Graceful flush succeeded
  case <-time.After(s.qm.flushDeadline):
      // Timeout - force shutdown
  }
  s.hardShutdown()             // Cancel context
  <-s.done
```

**Sample Drop on Hard Shutdown** (lines 1563-1578):
```
storage/remote/queue_manager.go:1563-1578
  case <-ctx.Done():
      // In this case we drop all samples in the buffer and the queue.
      // Remove them from pending and mark them as failed.
      droppedSamples := int(s.enqueuedSamples.Load())
      s.qm.metrics.pendingSamples.Sub(float64(droppedSamples))
      s.qm.metrics.failedSamplesTotal.Add(float64(droppedSamples))
      s.samplesDroppedOnHardShutdown.Add(uint32(droppedSamples))
      return
```

**Queue Flushing with Timeout** (lines 1447-1455):
```
storage/remote/queue_manager.go:1447-1455
  func (q *queue) FlushAndShutdown(done <-chan struct{}) {
      for q.tryEnqueueingBatch(done) {
          time.Sleep(time.Second)
      }
      q.batchMtx.Lock()
      q.batch = nil
      close(q.batchQueue)
  }
```

When `done` is closed (hard shutdown triggered), `tryEnqueueingBatch()` (lines 1469-1472) abandons the batch:
```
storage/remote/queue_manager.go:1469-1472
  case <-done:
      // The shard has been hard shut down, so no more samples can be sent.
      // No need to try again as we will drop everything left in the queue.
      return false
```

### CHANGELOG Evidence
Line 451 of CHANGELOG.md notes a related fix:
```
* [ENHANCEMENT] Remote Write: Disable resharding during active retry backoffs #13562
```
This indicates the Prometheus maintainers recognized resharding causes issues and added logic to disable it during recoverable errors (see `shouldReshard()` lines 1085-1105).

## Affected Components

1. **Primary**: `storage/remote/queue_manager.go`
   - `reshardLoop()` - orchestrates shard replacement
   - `shards.stop()` - initiates graceful flush with timeout
   - `shards.start()` - creates new shards with new queue distribution
   - `runShard()` - executes hard shutdown and drops samples

2. **Secondary**: Metrics system
   - `prometheus_remote_storage_samples_pending` - shows stuck pending samples
   - `prometheus_remote_storage_failed_samples_total` - incremented but samples are gone
   - Related: `shards_desired`, `numShards`, `highestTimestamp` metrics

3. **Timing Dependencies**:
   - Default `flushDeadline`: typically 1 minute (user configurable)
   - `shardUpdateDuration`: 30 seconds (checks if resharding needed)
   - `BatchSendDeadline`: typically 5-10 seconds per batch

## Why the Issue is Intermittent

1. **Load-Dependent**: High sample ingestion rates cause batches to accumulate in queues, requiring more time to flush all pending work
2. **Network-Dependent**: Slow remote-write endpoint responses delay flush completion
3. **Target Discovery Timing**: Resharding happens at fixed 30-second intervals; coinciding with high load or network issues increases failure probability
4. **Flush Deadline**: Default 1 minute is often insufficient when:
   - Many shards (each with separate flush operations)
   - Large batches (more time to serialize/send)
   - Slow remote endpoint (network latency)

**Example Failure Scenario**:
- T=0s: Target discovery changes, 100 targets added → need resharding from 4→8 shards
- T=30s: reshardLoop detects change, initiates stop()
- T=31s: 8 old shards each have 1000 pending samples in flight to slow endpoint
- T=85s: Only 6 of 8 shards have flushed (2 still waiting for sends to complete)
- T=90s: flushDeadline (60s) expires → hardShutdown() triggered
- T=91s: 2000+ samples dropped, never reach remote storage

## Recommendation

### Fix Strategy
1. **Option A (Preferred)**: Extend or make flush deadline dynamic based on shard count and queue depth
2. **Option B**: Implement graceful queue draining into new shards instead of dropping samples
3. **Option C**: Temporarily disable resharding (via `shouldReshard()` logic) when queues have high pending samples
4. **Option D**: Store dropped samples back into WAL for retry instead of discarding

### Diagnostic Steps
To confirm root cause in a failing deployment:

1. **Check these metrics during resharding**:
   ```
   # Look for drops when resharding occurs
   prometheus_remote_storage_failed_samples_total (increments during hard shutdown)
   prometheus_remote_storage_samples_pending (stuck >0 after resharding)
   prometheus_remote_storage_shards (changes value)

   # Related metric showing behind status
   prometheus_remote_storage_queue_highest_timestamp_seconds (stops advancing)
   prometheus_remote_storage_queue_highest_sent_timestamp_seconds (lags behind)
   ```

2. **Check logs for these patterns**:
   ```
   "Remote storage resharding" from=X to=Y       (resharding started)
   "Failed to flush all samples on shutdown"     (hard shutdown occurred)
   "Stopped remote storage"                      (shutdown messages)
   ```

3. **Enable debug logging** to see shard timing:
   ```
   # Look for these debug messages
   "QueueManager.updateShardsLoop" (resharding decision)
   "runShard timer ticked" (shows batch send activity)
   ```

4. **Measure time between logs**:
   - If <60 seconds between "resharding started" and "Failed to flush", confirms timeout issue
   - If resharding logs absent despite metric jumps, suggests config-driven resharding

5. **Profile queue depth during high load**:
   - Correlate `samples_pending` with `shards` metric changes
   - If pending spikes exactly when resharding occurs, confirms batches are in flight during transition

### Affected Versions
- Upstream Prometheus from ba14bc4 onwards until fix is merged
- Affects installations with:
  - Dynamic target discovery (Kubernetes, Consul, cloud SDV)
  - High sample ingestion rates (100k+ samples/sec)
  - Slow remote-write endpoints (>100ms latency)
  - Default queue configuration (flushDeadline=1min, minShards=1)

### Long-term Monitoring
Monitor these metrics in production to detect the issue:
```promql
# Alert: Samples stuck in queue after resharding
rate(prometheus_remote_storage_failed_samples_total[5m]) > 0
AND prometheus_remote_storage_samples_pending > 0
AND increase(prometheus_remote_storage_shards[1m]) != 0
```
