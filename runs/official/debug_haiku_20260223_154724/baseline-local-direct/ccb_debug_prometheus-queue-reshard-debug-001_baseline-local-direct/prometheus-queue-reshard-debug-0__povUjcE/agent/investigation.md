# Investigation Report: Remote-Write Queue Resharding Failure

## Summary

The remote-write queue resharding mechanism contains a race condition where `prometheus_remote_storage_samples_pending` metric can become stalled with incorrect values. The issue occurs when the shared sample-counting metrics (`pendingSamples`, `enqueuedSamples`) are reset during shard startup before the hardshutdown cleanup from the previous shard instance completes, causing samples dropped during timeout-triggered hardshutdowns to be incorrectly accounted.

## Root Cause

**File:** `storage/remote/queue_manager.go`
**Functions:** `reshardLoop()` (line 1184), `stop()` (line 1269), `start()` (line 1237), `runShard()` (line 1491)

**Mechanism:**

The resharding process has an implicit but unchecked ordering assumption:

```go
// reshardLoop() at lines 1189-1194
case numShards := <-t.reshardChan:
    t.shards.stop()      // Stops old shards
    t.shards.start(numShards)  // Starts new shards
```

During `stop()` (lines 1269-1305):
1. `softShutdown` is closed (prevents new enqueues)
2. Old queues are told to flush via `FlushAndShutdown()`
3. If the flush deadline expires, `hardShutdown()` cancels the context
4. `hardShutdown()` triggers cleanup in old `runShard` goroutines

During `start()` (lines 1237-1266):
1. **Critical reset:** `s.enqueuedSamples.Store(0)` (line 1256)
2. **Critical reset:** `s.qm.metrics.pendingSamples.Set(0)` (line 1241)
3. New queues created
4. New `runShard` goroutines started

**The Race:**

```
Timeline of the race condition:

t0: Sample S enqueued in old shard
    → enqueuedSamples = 1, pendingSamples = 1

t1: Resharding triggered, stop() called
    → softShutdown closed, FlushAndShutdown() for all queues

t2: Flush deadline exceeded
    → hardShutdown() cancels context

t3: reshardLoop() calls start()
    → enqueuedSamples.Store(0)   [RESET]
    → pendingSamples.Set(0)      [RESET]
    → New shards created

t4: Old runShard sees ctx.Done()
    → Reads droppedSamples = int(s.enqueuedSamples.Load())
    → Gets 0 (was reset in t3!)
    → Decrements pendingSamples -= 0
    → Sample S is lost but not accounted

t5: New samples enqueued in new shards
    → enqueuedSamples = 1, pendingSamples = 1
    → Metrics show pending but don't reflect lost samples
```

The old `runShard` goroutine cannot decrement the metrics properly because the counters it depends on were reset by `start()` before it could read them.

## Evidence

### Code References:

1. **Metric Reset in start():**
   - Line 1241: `s.qm.metrics.pendingSamples.Set(0)`
   - Line 1256: `s.enqueuedSamples.Store(0)`

2. **Hardshutdown Cleanup Path:**
   - Lines 1563-1579: When `ctx.Done()` is received
   - Line 1566: `droppedSamples := int(s.enqueuedSamples.Load())`
   - Line 1569: `s.qm.metrics.pendingSamples.Sub(float64(droppedSamples))`

3. **Sample Enqueue Path:**
   - Lines 1313-1333: Enqueue function
   - Line 1326: `s.qm.metrics.pendingSamples.Inc()`
   - Line 1327: `s.enqueuedSamples.Inc()`

4. **Resharding Loop:**
   - Lines 1189-1194: Sequential stop() then start()
   - Line 1073: Logs "Remote storage resharding from=4 to=6"

### Supporting Code Structure:

- **shards struct** (lines 1209-1234): Contains shared atomic counters across all runShard goroutines
- **enqueuedSamples** (line 1215): Per-shard instance counter, but shared by multiple runShard goroutines during transition
- **pendingSamples** (line 87): Prometheus metric used by all shards

## Why This is Intermittent

The race condition manifests only under specific timing conditions:

1. **Requires timeout during flush:** The `flushDeadline` must expire before all old shards finish sending samples (line 1289)
2. **Requires concurrent activity:** While `hardShutdown()` is canceling old shards, `start()` must reset the counters before old runShards read them
3. **Requires samples in flight:** There must be samples in old queues that haven't been sent yet
4. **Timing-dependent:** The exact interleaving of old shard cleanup and new shard initialization varies based on:
   - Network latency in remote write destination
   - System scheduling of goroutines
   - Load and number of samples being sent
   - Duration of resharding decision (line 1072)

The issue is most likely to occur when:
- Target discovery adds/removes many targets (causes resharding)
- Remote storage endpoint is slow or temporarily unavailable (triggers timeouts)
- Prometheus is under moderate load (prevents immediate completion)

## Affected Components

**Primary:**
- `storage/remote/queue_manager.go` - QueueManager, shards struct, resharding logic
- Package: `github.com/prometheus/prometheus/storage/remote`

**Secondary:**
- Metrics tracking: `prometheus_remote_storage_samples_pending`
- Queue management: Append, FlushAndShutdown, runShard functions

**Impact:**
- Remote write queue becomes stuck with incorrect metric values
- Some samples may be silently dropped without proper accounting
- Resharding can trigger cascading failures in monitoring of remote write capacity

## Recommendation

### Fix Strategy

**Option 1 (Safest): Separate counters per shard instance**
- Create new `enqueuedSamples` counters in each shard instance rather than resetting
- Old shards track their dropped samples independently
- New shards track their enqueued samples independently
- Prevents cross-contamination during transitions

**Option 2 (Simpler): Snapshot counters before reset**
- In `stop()`, before calling `hardShutdown()`, capture the current value of `enqueuedSamples`
- Pass this snapshot to hardshutdown cleanup path
- Old runShards use the snapshot instead of reading the live atomic value
- Prevents reads of reset values

**Option 3 (Most robust): Add synchronization between stop and start**
- Don't call `start()` until all old runShards have completed cleanup
- Ensure hardshutdown cleanup code runs before metrics are reset
- Requires stronger synchronization guarantees

### Diagnostic Steps to Confirm

1. **Enable verbose logging** at resharding points:
   - Log when `hardShutdown()` is called vs when samples were dropped
   - Log `enqueuedSamples` value before and after `start()`

2. **Monitor these metrics together:**
   - `prometheus_remote_storage_samples_pending` (should decrease monotonically)
   - `prometheus_remote_storage_samples_dropped_total` (should account for drops)
   - `prometheus_remote_storage_samples_sent_total` (should increase)

3. **Check for correlation:**
   - When `prometheus_remote_storage_samples_pending` gets stuck
   - Check logs for "Currently resharding, skipping" messages (line 1076)
   - Check for timeout messages near `flushDeadline` (default 10s, line 651)
   - Verify remote endpoint was slow or unavailable at that time

4. **Reproduce with test:**
   - Create test that triggers resharding while samples are slow to send
   - Verify metrics are consistent before/after resharding
   - Check that no samples are lost without being counted in drop metrics

### Immediate Workarounds

1. Increase `flushDeadline` to reduce timeout likelihood
2. Reduce resharding frequency by adjusting `shardUpdateDuration` (line 1060)
3. Ensure remote write endpoint has low latency and high availability
4. Monitor `prometheus_remote_storage_shards` metric for frequent resharding spikes
