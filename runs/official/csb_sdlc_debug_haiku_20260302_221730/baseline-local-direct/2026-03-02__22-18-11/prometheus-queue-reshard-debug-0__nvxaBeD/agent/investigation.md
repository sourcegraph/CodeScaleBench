# Investigation Report: Remote-Write Queue Resharding Failure

## Summary

A race condition in the queue resharding logic causes sample data loss without proper metric accounting. When resharding occurs during active remote-write operations, partial batches waiting to be flushed are discarded without decrementing the `prometheus_remote_storage_samples_pending` metric, causing shards to appear stuck with pending samples.

## Root Cause

**Location:** `storage/remote/queue_manager.go`

**Issue:** The `FlushAndShutdown()` function (lines 1447-1455) unconditionally discards the partial batch with `q.batch = nil` when the hard shutdown signal is received, without decrementing the pending metrics counter for those samples.

```go
// storage/remote/queue_manager.go:1447-1455
func (q *queue) FlushAndShutdown(done <-chan struct{}) {
	for q.tryEnqueueingBatch(done) {
		time.Sleep(time.Second)
	}
	q.batchMtx.Lock()
	defer q.batchMtx.Unlock()
	q.batch = nil  // <-- RACE CONDITION: Samples discarded without metric updates
	close(q.batchQueue)
}
```

## Evidence

### Code References

1. **Resharding trigger and execution:**
   - Line 1189: `reshardChan` receives new shard count
   - Line 1193: `t.shards.stop()` initiates shutdown
   - Line 1194: `t.shards.start(numShards)` starts new shards

2. **Graceful to hard shutdown flow:**
   - Line 1274-1276: `softShutdown` channel is closed (prevents new enqueues)
   - Line 1283-1284: `queue.FlushAndShutdown()` called for each queue
   - Line 1289: Waits for `flushDeadline` (default behavior allows timeout)
   - Line 1293: `s.hardShutdown()` cancels context if timeout occurs

3. **Partial batch handling:**
   - Line 1396-1407: `queue.Append()` adds samples to partial batch
   - Line 1325-1327: `enqueue()` increments `pendingSamples` and `enqueuedSamples` atomics
   - Line 1452-1454: `FlushAndShutdown()` sets `q.batch = nil` without metric updates

4. **Hard shutdown sample accounting:**
   - Line 1566-1577: When context is cancelled, only `enqueuedSamples` is counted as dropped
   - But `enqueuedSamples` only reflects samples that reached the queue's batch collection, not partial batches stuck in tryEnqueueingBatch timeout

### The Race Condition Timeline

```
T0: Sample S enqueued
    - enqueuedSamples++
    - pendingSamples++ (metrics)
    - Sample added to partial batch q.batch

T1: Partial batch waiting to be flushed
    - q.batch contains S, but < MaxSamplesPerSend
    - Timer hasn't fired yet

T2: Resharding triggered
    - reshardLoop receives desiredShards count
    - t.shards.stop() called

T3: Graceful shutdown phase
    - softShutdown closed (prevents new enqueues)
    - FlushAndShutdown called for each queue
    - tryEnqueueingBatch attempts to send q.batch to batchQueue
    - BUT: batchQueue is full (previous batch still being sent by runShard)

T4: runShard blocked in sendSamplesWithBackoff
    - Remote endpoint slow/unresponsive
    - Context not cancelled yet

T5: flushDeadline timeout occurs
    - Hard shutdown initiated
    - s.hardShutdown() cancels context

T6: Hard shutdown execution
    - FlushAndShutdown receives <-done signal
    - tryEnqueueingBatch returns false (line 1469-1472)
    - q.batch = nil (line 1453) - SAMPLE S DISCARDED
    - Samples in q.batch NEVER counted in dropped metrics
    - pendingSamples metric remains unreduced

T7: runShard context cancellation
    - Exits at line 1563 (ctx.Done case)
    - Only decrements based on enqueuedSamples
    - But S was never added to enqueuedSamples count (it was in partial batch)
    - Result: pendingSamples stuck > 0
```

## Affected Components

1. **Core affected file:** `storage/remote/queue_manager.go`
   - Function: `shards.stop()` (lines 1269-1305)
   - Function: `queue.FlushAndShutdown()` (lines 1447-1455)
   - Function: `shards.start()` (lines 1237-1266)

2. **Related metrics:**
   - `prometheus_remote_storage_samples_pending` - stuck counter
   - `prometheus_remote_storage_samples_dropped_total` - incomplete accounting
   - `prometheus_remote_storage_sent_batches_total` - may be inaccurate

3. **Triggering conditions:**
   - Target discovery changes (add/remove targets)
   - Any action triggering dynamic shard reallocation
   - Configuration changes to remote-write URL/parameters

4. **Dependent components:**
   - `runShard()` (lines 1491-1602) - runs concurrently with resharding
   - `sendSamplesWithBackoff()` (lines 1698-1808) - can block indefinitely on slow endpoints

## Why This Is Intermittent

The race condition only manifests under specific timing conditions:

1. **Slow remote endpoint required:**
   - Remote endpoint must be slow enough that `sendSamplesWithBackoff()` blocks during resharding
   - This causes `batchQueue` to remain full, preventing `FlushAndShutdown()` from enqueuing the partial batch

2. **Partial batch must exist:**
   - A batch with samples below `MaxSamplesPerSend` must be accumulating
   - Timer deadline has not yet fired to flush it
   - Typical when sample arrival rate is low or uneven

3. **flushDeadline must timeout:**
   - `FlushAndShutdown()` waits only `flushDeadline` duration (typically 10 seconds)
   - If remote endpoint recovery time exceeds this window, hard shutdown is forced
   - Brief network hiccups may not trigger this, explaining intermittent nature

4. **Resharding must occur during this window:**
   - Target discovery changes must trigger resharding precisely when conditions 1-3 are met
   - Adding/removing targets causes dynamic shard reallocation
   - Correlation with target changes explains "intermittent" nature

## Recommended Diagnostic Steps

### Immediate Verification

1. **Check for pending samples with zero out-of-order samples:**
   ```promql
   prometheus_remote_storage_samples_pending{job="prometheus"} > 0
   ```
   Compare with:
   ```promql
   rate(prometheus_remote_storage_sent_batches_total[5m]) == 0
   ```
   If pending > 0 but send rate = 0, confirms stalled shard.

2. **Check remote endpoint connectivity during resharding:**
   ```promql
   rate(prometheus_remote_storage_retried_samples_total[1m])
   ```
   Spike in retries during resharding indicates slow endpoint.

3. **Monitor resharding frequency:**
   ```promql
   rate(prometheus_remote_storage_resharding_changes_total[5m])
   ```
   (Note: This metric may not exist; search logs instead)

### Log Analysis

1. **Search logs for resharding correlated with stalls:**
   ```
   grep -E "Resharding queues|Resharding done|Failed to flush all samples" prometheus.log
   ```
   Check timing between these events.

2. **Check for timeout patterns:**
   ```
   grep "time.After.*flushDeadline" prometheus.log
   ```
   Look for frequency of hard shutdowns (flushDeadline timeouts).

3. **Verify remote endpoint issues:**
   ```
   grep -E "remote.*timeout|context.*canceled|connection.*refused" prometheus.log
   ```
   Correlate with resharding events.

### Metrics to Monitor

1. **`prometheus_remote_storage_samples_pending`** - Primary indicator of stuck samples
2. **`prometheus_remote_storage_samples_dropped_total`** - May show unexpected increases
3. **`prometheus_remote_storage_retried_samples_total`** - Watch for spikes
4. **`prometheus_remote_storage_sent_batches_total`** - Check for stalled increments
5. **Shard-specific pending metrics** (if available) - Identify which shards stall

## Recommendation

### Root Fix Required

The `FlushAndShutdown()` function must be modified to:

1. **Track partial batch samples before discarding:**
   - Count samples in `q.batch` when hard shutdown occurs
   - Properly decrement `pendingSamples` and `failedSamplesTotal` metrics
   - Update `enqueuedSamples` to reflect the loss

2. **Prevent premature batch loss:**
   - Extend the window for graceful shutdown of partial batches
   - Use context timeout instead of simple time.After for more precise control
   - Ensure hard shutdown only occurs after all reasonable attempts to flush

### Temporary Workaround (if fix cannot be deployed immediately)

1. **Increase `flush_deadline`** in remote write configuration
   - Gives more time for graceful shutdown before hard shutdown
   - Reduces likelihood of partial batch loss due to timeout
   - May introduce brief delays during resharding

2. **Reduce `max_samples_per_send`** or increase sample arrival rate
   - Forces more frequent batch flushes
   - Reduces likelihood of partial batches being in queue during resharding
   - May increase overhead

3. **Reduce target churn** during high-traffic periods
   - Avoid service discovery changes when remote endpoints are slow
   - Delay configuration reloads if possible

## Verification of Fix

After fix implementation:

1. Run under target churn with slow remote endpoints
2. Verify `prometheus_remote_storage_samples_pending` remains at 0
3. Check that all metrics account for all samples (no leaks)
4. Monitor `prometheus_remote_storage_samples_dropped_total` accurately reflects actual dropped samples
