# Investigation Report: Remote-Write Queue Resharding Failure

## Summary

The intermittent stalling of remote-write shards correlates with a metric inconsistency during resharding: the `prometheus_remote_storage_samples_pending` counter is unconditionally reset to 0 during new shard initialization (line 1241 in `queue_manager.go`), potentially hiding samples that were dropped during hard shutdown or lost in partial batches.

## Root Cause

**Location:** `/workspace/storage/remote/queue_manager.go`

**Critical Issue:** In the `(*shards).start()` function at line 1241:
```go
s.qm.metrics.pendingSamples.Set(0)
```

This operation unconditionally resets the global pending samples counter to 0 **without accounting for samples that may have been lost during the hard shutdown phase** of the preceding resharding cycle.

**Mechanism:**

1. **Resharding Sequence** (lines 1193-1194):
   - `reshardLoop()` calls `t.shards.stop()` to gracefully shut down old shards
   - Then calls `t.shards.start(numShards)` to initialize new shards with new queue count

2. **Hard Shutdown Occurs If Flushing Times Out** (lines 1289-1294):
   - `stop()` waits for old queues to flush within `flushDeadline`
   - If timeout: `s.hardShutdown()` cancels the context
   - Running shards exit early without completing pending RPCs
   - Dropped samples are recorded via `pendingSamples.Sub()` (line 1569)

3. **Counter Reset Overwrites Metrics** (line 1241):
   - After `stop()` returns, `start()` is immediately called
   - `pendingSamples.Set(0)` unconditionally sets the counter to 0
   - **This overwrites any Sub() operations recorded during hard shutdown**
   - The Prometheus Gauge's `Set()` replaces the value, not adding to it

4. **Partial Batch Loss Scenario**:
   - Samples in a queue's partial batch may not be sent to batchQueue before hard shutdown
   - `FlushAndShutdown()` (line 1447-1455) tries to enqueue the batch
   - If hard shutdown happens before enqueue succeeds, the partial batch is abandoned (line 1453: `q.batch = nil`)
   - These samples were already counted in `pendingSamples` via `enqueue()`
   - But they're never sent or properly accounted for in dropped metrics
   - Then `start()` resets `pendingSamples.Set(0)`, hiding the loss

## Evidence

**File:** `/workspace/storage/remote/queue_manager.go`

### Key Code References:

1. **Problematic Reset** (line 1241):
   ```go
   func (s *shards) start(n int) {
       s.mtx.Lock()
       defer s.mtx.Unlock()
       s.qm.metrics.pendingSamples.Set(0)  // ← ISSUE: Unconditional reset
   ```

2. **Hard Shutdown Mechanism** (lines 1289-1294):
   ```go
   select {
   case <-s.done:
       return
   case <-time.After(s.qm.flushDeadline):  // ← Timeout triggers hard shutdown
   }
   s.hardShutdown()  // ← Cancels context, causes runShard to exit early
   <-s.done
   ```

3. **Metrics Update During Hard Shutdown** (lines 1563-1578):
   ```go
   case <-ctx.Done():
       droppedSamples := int(s.enqueuedSamples.Load())
       s.qm.metrics.pendingSamples.Sub(float64(droppedSamples))  // ← Sub() call
       // ... record failures ...
       return  // ← Exit immediately
   ```

4. **Flush and Shutdown with Potential Loss** (lines 1447-1455):
   ```go
   func (q *queue) FlushAndShutdown(done <-chan struct{}) {
       for q.tryEnqueueingBatch(done) {  // ← Retry loop
           time.Sleep(time.Second)
       }
       q.batchMtx.Lock()
       defer q.batchMtx.Unlock()
       q.batch = nil  // ← Samples lost if not yet enqueued
       close(q.batchQueue)
   ```

5. **tryEnqueueingBatch Exit on Hard Shutdown** (lines 1459-1477):
   ```go
   case <-done:
       // The shard has been hard shut down, so no more samples can be sent.
       // No need to try again as we will drop everything left in the queue.
       return false  // ← Exits loop, abandoning partial batch
   ```

### Related Tests:

- `TestReshardPartialBatch()` (queue_manager_test.go): Tests for deadlocks during resharding with partial batches
- `TestReshardRaceWithStop()`: Tests race conditions between resharding and shutdown
- `TestReshard()`: Basic resharding functionality test

## Affected Components

1. **`storage/remote/queue_manager.go`**:
   - `(*QueueManager).updateShardsLoop()` (line 1057): Triggers resharding
   - `(*QueueManager).reshardLoop()` (line 1184): Executes resharding sequence
   - `(*shards).start()` (line 1237): Initializes new shards
   - `(*shards).stop()` (line 1269): Gracefully shuts down old shards
   - `(*shards).enqueue()` (line 1312): Routes samples to shards
   - `(*queue).FlushAndShutdown()` (line 1447): Flushes queue during shutdown

2. **Metrics Package** (`prometheus/prometheus/model/metrics`):
   - `prometheus.Gauge.Set()`: Overwrites counter value (not additive)
   - `prometheus.Gauge.Sub()`: Decrements counter value

3. **Sync Primitives**:
   - `sync.RWMutex` on `shards.mtx`: Protects queues access
   - `sync.Atomic` counters: Track pending samples per shard

## Recommendation

### Fix Strategy

**Option 1 (Recommended): Remove the `Set(0)` call**
- The counter should already be 0 if all old samples are properly accounted for
- Rationale: By the time `start()` is called, all old shards have finished
  - Either normally: all samples sent via `updateMetrics().Sub()`
  - Or via hard shutdown: all samples dropped via `Sub()` at line 1569
- Remove line 1241: `s.qm.metrics.pendingSamples.Set(0)`

**Option 2: Use `Sub()` to explicitly account for remaining pending samples**
```go
// Before creating new queues, subtract remaining pending samples
remaining := s.qm.metrics.pendingSamples.Desc()  // Or track separately
s.qm.metrics.pendingSamples.Sub(remaining)
```

### Diagnostic Steps

1. **Monitor Resharding Events**:
   - Enable debug logging for "Remote storage resharding" messages
   - Correlate with timestamp of metric stalls

2. **Check Metric Anomalies**:
   - Watch for `prometheus_remote_storage_samples_pending` jumping to 0
   - Compare with `prometheus_remote_storage_samples_total` and `prometheus_remote_storage_samples_total{exported}`
   - If pending suddenly drops to 0 while total is increasing, resharding occurred

3. **Add Instrumentation**:
   - Log the value of `pendingSamples` before/after `Set(0)` call
   - Log samples dropped during hard shutdown
   - Compare the two to detect loss

4. **Monitor These Metrics During Resharding**:
   - `prometheus_remote_storage_samples_pending`: Should be 0 after flush completes
   - `prometheus_remote_storage_samples_dropped_total`: Should increase if hard shutdown occurs
   - `prometheus_remote_storage_shard_capacity`: Capacity of each shard
   - `prometheus_remote_storage_shards`: Number of active shards

5. **Reproduce Scenario**:
   ```bash
   # Monitor metrics during target scrape changes
   # Observe when "Remote storage resharding" log appears
   # Check if pending samples becomes inconsistent
   # Verify samples reach remote destination
   ```

## Timeline of Events Leading to Stall

1. **T0**: Target discovery changes → New scrape targets added/removed
2. **T1**: Data rate changes → updateShardsLoop detects need to reshard (4→6 shards)
3. **T2**: updateShardsLoop sends to reshardChan, sets `t.numShards = 6`
4. **T3**: reshardLoop receives and calls `stop()`:
   - Closes `softShutdown` channel
   - Calls `FlushAndShutdown()` for each old queue
5. **T4**: If flush takes >flushDeadline:
   - Hard shutdown triggered
   - Old runShard goroutines exit early (line 1578)
   - Partial batches in queues are abandoned
   - `pendingSamples.Sub()` records some dropped samples
6. **T5**: `start()` called with new queues:
   - **BUG**: `pendingSamples.Set(0)` resets counter
   - New runShard goroutines started
7. **T6**: New samples enqueued to new shards
   - Metric shows pending samples increasing
   - But previously dropped samples are not reflected
8. **T7**: If remote storage is missing old samples:
   - Gaps in data
   - Possible data inconsistency in remote system

## Why This Is Intermittent

- **Race Condition Dependent**: Only manifests when hard shutdown timeout occurs
- **Load Dependent**: More likely under high cardinality (many series) or slow remote endpoint
- **Timing Dependent**: Depends on exact timing of resharding vs batch flush
- **Network Dependent**: Slow or unresponsive remote endpoint triggers timeout
- **Target Discovery Pattern**: Specific patterns of target changes trigger threshold-crossing resharding

## Confirmation Checklist

- [ ] Check Prometheus upgrade logs for "Remote storage resharding" messages
- [ ] Correlate with metric gaps or discontinuities in remote storage
- [ ] Verify `samples_dropped_total` increases during stalls
- [ ] Check if `samples_pending` becomes 0 immediately after resharding
- [ ] Monitor new shards - do they properly process samples after resharding?
- [ ] Test with slow remote endpoint to trigger hard shutdown timeout
