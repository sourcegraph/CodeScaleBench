# Investigation Report: Remote-Write Queue Resharding Failure

## Summary

The intermittent stalling of remote-write shards after resharding is caused by a race condition between metrics reset in `shards.start()` and metrics decrement in exiting `runShard` goroutines. When `hardShutdown` is called during resharding, queued samples are dropped but their metrics may not be properly decremented if the reset occurs before the final accounting.

## Root Cause

**File:** `storage/remote/queue_manager.go`

**Primary Issue Location:** Lines 1237-1266 (`start()` function) and Lines 1563-1578 (`runShard` context cancellation)

**Mechanism:**

When resharding occurs:
1. `reshardLoop()` (line 1189) calls `t.shards.stop()` followed by `t.shards.start(numShards)`
2. In `stop()`, if `flushDeadline` is exceeded (line 1289), `hardShutdown()` is called (line 1293)
3. All `runShard` goroutines receive `ctx.Done()` and execute lines 1566-1575, loading pending sample counts and decrementing metrics
4. After all old shards exit, `start()` is called
5. At line 1241, **`s.qm.metrics.pendingSamples.Set(0)` forcefully resets the metric to 0**
6. At line 1256, **`s.enqueuedSamples.Store(0)` resets the atomic counter**

**The Race Condition:**

If timing aligns such that:
- Old `runShard` goroutines load `s.enqueuedSamples` (line 1566) AFTER the counter reset at line 1256
- These goroutines read a count of 0 (because it was just reset)
- They then decrement the global metric by 0 instead of the actual dropped sample count
- **Result:** Dropped samples are not properly accounted for in the global metric

Additionally, the metric reset at line 1241 assumes all prior operations have completed, but if any updates are in-flight between hardShutdown and start(), they can be lost.

## Evidence

### Code References

**Problematic Sequence:**

1. **Metric reset before potential completion** (`queue_manager.go:1241`):
   ```go
   s.qm.metrics.pendingSamples.Set(0)  // Forceful reset
   ```

2. **Counter reset** (`queue_manager.go:1256`):
   ```go
   s.enqueuedSamples.Store(0)  // Atomic counter reset
   ```

3. **Old shard metrics decrement** (`queue_manager.go:1566-1569`):
   ```go
   droppedSamples := int(s.enqueuedSamples.Load())
   s.qm.metrics.pendingSamples.Sub(float64(droppedSamples))
   ```

### Timing Window

**Duration:** Between `hardShutdown()` call (line 1293) and when old `runShard` goroutines finish exiting (line 1578)

**Condition:** Occurs when resharding is triggered while queues are not fully flushed within `flushDeadline` (typically when targets are rapidly added/removed)

### Partial Batch Issue

**Additional Problem** (`queue_manager.go:1447-1455`):

```go
func (q *queue) FlushAndShutdown(done <-chan struct{}) {
    for q.tryEnqueueingBatch(done) {
        time.Sleep(time.Second)
    }
    q.batchMtx.Lock()
    defer q.batchMtx.Unlock()
    q.batch = nil  // Batch discarded without sending if hardShutdown occurs
    close(q.batchQueue)
}
```

When `done` channel is received (hardShutdown), the partial batch in `q.batch` is set to `nil` without being sent. While the samples ARE accounted for in `enqueuedSamples`, a gap exists between batch discard and metrics update.

## Affected Components

- **`storage/remote/queue_manager.go`** - Main resharding orchestration
  - `reshardLoop()` (line 1184) - Controls reshard flow
  - `shards.stop()` (line 1269) - Stops old shards with timeout
  - `shards.start()` (line 1237) - Initializes new shards
  - `runShard()` (line 1491) - Worker goroutines handling sample sends

- **Metrics Subsystem:**
  - `prometheus_remote_storage_samples_pending` - Can become inconsistent
  - `prometheus_remote_storage_shards` - Incremented with potential stale data

- **Queue Management:**
  - `queue.FlushAndShutdown()` (line 1447) - Batch flushing during shard stop
  - `tryEnqueueingBatch()` (line 1459) - Partial batch queueing logic

## Recommendation

### Diagnostic Steps to Confirm Root Cause

1. **Add instrumentation to track metric updates:**
   - Log `pendingSamples` value immediately before and after `start()` call
   - Log `enqueuedSamples` value when `hardShutdown` is called and when `runShard` exits
   - Compare dropped sample counts from logs vs metric final values

2. **Monitor resharding events:**
   ```
   level=info msg="Remote storage resharding" from=X to=Y
   level=warn msg="Resharding timeout exceeded" numShards=Y
   ```
   Trigger resharding during target discovery changes and observe if metrics become stuck

3. **Check for metric anomalies:**
   - Query `prometheus_remote_storage_samples_pending` during and after resharding
   - Look for values that don't decrease despite successful sends
   - Correlate with shard count changes

### Fix Strategy

The metrics reset logic in `start()` must be synchronized with old `runShard` completion:

1. **Option 1 (Recommended):** Decrement only the difference
   - Instead of `Set(0)`, calculate pending samples from sent vs enqueued
   - Ensure old shards fully decrement before new shards reset

2. **Option 2:** Defer metrics reset
   - Move metrics reset to after all old `runShard` goroutines have fully exited
   - Add synchronization barrier between `stop()` returning and `start()` beginning
   - Use explicit channel signaling to ensure completion ordering

3. **Option 3:** Per-shard metrics tracking
   - Track metrics per-shard object rather than global counter
   - Prevents cross-shard metric interference during resharding

## Why It's Intermittent

1. **Race condition dependency:** Requires specific timing between metric reset and shard exit
2. **Load-dependent:** More likely with rapid target changes (triggers frequent resharding)
3. **Network-dependent:** Worse when remote endpoint is slow (triggers hardShutdown)
4. **Configuration-dependent:** Depends on `flushDeadline` value vs. actual send latency

The stall manifests when:
- Resharding is triggered frequently (target discovery instability)
- Remote endpoint has latency > `flushDeadline`
- Multiple shards drop samples in same resharding cycle
- New shards start before old shard metrics are fully accounted

