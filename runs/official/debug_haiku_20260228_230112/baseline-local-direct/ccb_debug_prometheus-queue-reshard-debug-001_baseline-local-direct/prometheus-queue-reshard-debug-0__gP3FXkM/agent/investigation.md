# Investigation Report: Remote-Write Queue Resharding Stalled Samples

## Summary

Remote-write shards stall with pending samples stuck in the metric after resharding due to a race condition where `runShard()` goroutines exit before flushing partial batches when the queue's `batchQueue` channel closes. Samples are incremented when enqueued but never decremented, leaving them permanently pending.

---

## Root Cause

**Location:** `storage/remote/queue_manager.go` - Race between `queue.FlushAndShutdown()` and `runShard()` during resharding

**Mechanism:**

1. **Enqueue phase (normal operation):**
   - Sample arrives at `Append()`
   - `shards.enqueue()` routes to appropriate queue shard: `shard := uint64(ref) % uint64(len(s.queues))` (line 1315)
   - Sample is appended to queue's partial batch: `s.queues[shard].Append(data)` (line 1320)
   - **Metric incremented:** `s.qm.metrics.pendingSamples.Inc()` (line 1326)

2. **Send phase (normal operation):**
   - `runShard()` receives batches from `batchQueue` channel (line 1580)
   - When timer fires (line 1593), it calls `queue.Batch()` to get partial batch
   - `sendBatch()` is called, which calls `updateMetrics()` (line 1549/1556)
   - **Metric decremented:** `s.qm.metrics.pendingSamples.Sub()` (line 1689)

3. **The race condition during resharding:**
   - Old shards are processing final batches while `stop()` is called
   - `stop()` calls `FlushAndShutdown(done)` on each queue (line 1284)
   - `FlushAndShutdown()` tries to enqueue the partial batch: `tryEnqueueingBatch(done)` (line 1448)
   - Meanwhile, `runShard()` is in its select loop waiting for: batchQueue receive, timer, or context cancellation
   - **Critical window:** If `batchQueue` channel is closed BEFORE the timer fires and BEFORE `runShard()` processes the timer case:
     - `runShard()` receives from closed channel: `batch, ok := <-batchQueue` (line 1580)
     - `ok=false` causes immediate return from `runShard()` (line 1581-1582)
     - **Samples in `queue.batch` are NEVER sent**
     - **Samples in pending metric are NEVER decremented**

---

## Evidence

### Code References

**1. Enqueue increments metric (line 1326 in queue_manager.go):**
```go
func (s *shards) enqueue(ref chunks.HeadSeriesRef, data timeSeries) bool {
    s.mtx.RLock()
    defer s.mtx.RUnlock()
    shard := uint64(ref) % uint64(len(s.queues))
    select {
    case <-s.softShutdown:
        return false
    default:
        appended := s.queues[shard].Append(data)
        if !appended {
            return false
        }
        switch data.sType {
        case tSample:
            s.qm.metrics.pendingSamples.Inc()  // ← SAMPLE COUNTED
            s.enqueuedSamples.Inc()
```

**2. Send path decrements metric (line 1689 in queue_manager.go):**
```go
func (s *shards) updateMetrics(_ context.Context, err error, sampleCount, exemplarCount, ...) {
    // ... error handling ...
    // Pending samples/exemplars/histograms also should be subtracted, as an error means
    // they will not be retried.
    s.qm.metrics.pendingSamples.Sub(float64(sampleCount))  // ← SAMPLE REMOVED
    s.qm.metrics.pendingExemplars.Sub(float64(exemplarCount))
    s.qm.metrics.pendingHistograms.Sub(float64(histogramCount))
```

**3. Queue closure during reshape (lines 1447-1454 in queue_manager.go):**
```go
func (q *queue) FlushAndShutdown(done <-chan struct{}) {
    for q.tryEnqueueingBatch(done) {
        time.Sleep(time.Second)
    }
    q.batchMtx.Lock()
    defer q.batchMtx.Unlock()
    q.batch = nil
    close(q.batchQueue)  // ← CLOSES CHANNEL
}
```

**4. Early exit on closed channel (lines 1580-1582 in queue_manager.go):**
```go
case batch, ok := <-batchQueue:
    if !ok {
        return  // ← EXITS IMMEDIATELY, skipping timer case
    }
```

**5. Partial batch lost - timer case never reached (lines 1593-1599):**
```go
case <-timer.C:
    batch := queue.Batch()  // ← THIS CODE NEVER EXECUTES IF CHANNEL CLOSED FIRST
    if len(batch) > 0 {
        sendBatch(batch, s.qm.protoMsg, s.qm.compr, true)
    }
    queue.ReturnForReuse(batch)
    timer.Reset(time.Duration(s.qm.cfg.BatchSendDeadline))
```

**6. Metric reset without accounting (line 1241 in queue_manager.go):**
```go
func (s *shards) start(n int) {
    s.mtx.Lock()
    defer s.mtx.Unlock()

    s.qm.metrics.pendingSamples.Set(0)  // ← UNCONDITIONALLY RESETS METRIC
    s.qm.metrics.numShards.Set(float64(n))
```

### Resharding workflow (lines 1184-1199)

```go
func (t *QueueManager) reshardLoop() {
    for {
        select {
        case numShards := <-t.reshardChan:
            t.shards.stop()         // ← Calls FlushAndShutdown on all queues
            t.shards.start(numShards) // ← Resets pendingSamples.Set(0)
        case <-t.quit:
            return
        }
    }
}
```

---

## Affected Components

1. **storage/remote/queue_manager.go:**
   - `QueueManager.reshardLoop()` - Orchestrates reshard sequence
   - `shards.stop()` - Initiates graceful queue closure
   - `shards.start()` - Resets metrics and starts new shards
   - `shards.runShard()` - Shard worker goroutine (lines 1491-1602)
   - `shards.enqueue()` - Routes and counts incoming samples
   - `shards.updateMetrics()` - Decrements metric on successful/failed send

2. **storage/remote/queue.go:**
   - `queue.FlushAndShutdown()` - Closes queue channel
   - `queue.Batch()` - Retrieves partial batch
   - `queue.Chan()` - Provides send-only reference to batchQueue

3. **Metrics:**
   - `prometheus_remote_storage_samples_pending` - Affected gauge metric
   - Also affects `prometheus_remote_storage_exemplars_pending` and `prometheus_remote_storage_histograms_pending`

---

## Why This Is Intermittent (Timing-Sensitive Race)

The issue only manifests under specific timing conditions:

1. **Must have samples in partial batch:** A sample enqueued but not yet forming a complete batch at reshape time
2. **Timer not yet fired:** The batch deadline timer in `runShard()` must not have triggered before channel close
3. **Concurrent close window:** The exact moment `batchQueue` is closed must occur before `runShard()` executes the timer case

**Probability factors:**
- Depends on `BatchSendDeadline` setting (default: 5 seconds)
- Depends on `MaxSamplesPerSend` (partial batch threshold)
- Depends on sample arrival rate
- Depends on reshape frequency
- More likely when reshards happen frequently (e.g., rapid target discovery changes)

**Example scenario:**
- 100ms after last batch sent, `batchQueue` is closed
- Timer is set for 5 seconds
- `runShard()` select blocks on timer and closed channel simultaneously
- If select picks channel first → race condition triggers

---

## Diagnostic Confirmation Strategy

### Metrics to Monitor

1. **`prometheus_remote_storage_samples_pending`** - Should decrease monotonically
   - If stuck at constant >0 after reshard → root cause likely confirmed
   - Check if delta from pre-reshard to post-reshard is non-zero

2. **`prometheus_remote_storage_shards`** - Number of active shards
   - Watch for reshard events (`prometheus_remote_storage_desired_shards` changes)

3. **`prometheus_remote_storage_samples_total`** (with outcome=success/failure)
   - Compare total sent with `pending + sent`
   - Missing samples in this equation = lost samples

### Logs to Examine

**In prometheus logs, search for:**
```
"Remote storage resharding" from=X to=Y
```

Then check around that timestamp for:
1. Any errors in shard goroutines
2. Backoff messages in Append() (indicates enqueue failures during reshard)
3. Shard exit/completion logs
4. No "runShard timer ticked" messages after reshard (indicates timer never fired)

### Instrumentation Needed (recommended fixes)

1. Log when samples are left in `queue.batch` at FlushAndShutdown time
2. Log when `batchQueue` receives from closed channel in runShard
3. Add assertion that `pendingSamples >= 0` (currently can go negative during soft-reset race)
4. Track samples dropped during FlushAndShutdown via hard shutdown path

---

## Recommendation

### Root Cause Fix Options

**Option 1 (Recommended): Flush remaining samples before closing channel**
- In `queue.FlushAndShutdown()`: Wait for all pending batches in `queue.batch` to be sent before closing `batchQueue`
- Ensure `runShard()` processes timer case and sends final partial batches before channel closes
- Requires synchronization mechanism (e.g., WaitGroup or hand-off flag)

**Option 2: Defer channel close in runShard**
- Have `runShard()` close the channel on exit, not `FlushAndShutdown()`
- Prevents race where channel closes while shard is still processing
- Requires restructuring of shutdown sequence

**Option 3: Send partial batch in timer case during shutdown**
- In `runShard()` timer case: Even if `batchQueue` is closed, still send partial batch
- Requires detecting shutdown state separately from channel closure

**Option 4: Count dropped samples in FlushAndShutdown**
- When `tryEnqueueingBatch()` fails to send due to channel closure
- Decrement pending metric to account for lost samples
- Trade-off: Some data loss is allowed (but accounted)

### Short-term Mitigation
- Set `BatchSendDeadline` to smaller value (e.g., 1 second instead of 5 seconds) to increase timer firing probability
- Reduce reshape frequency by adjusting `maxShards` calculation tolerances
- Monitor `samples_pending` metric closely after upgrades with configuration changes

### Testing Needed
- Add test case: `TestReshardWithPendingBatch` - Verify no samples stuck during rapid reshards with persistent sample flow
- Add test: `TestReshardTimeoutCloseRace` - Stress test the exact race condition window
- Run existing tests with various `BatchSendDeadline` values

---

## Summary of Impact

- **Severity:** Medium (silent data loss, no error logged)
- **Detection:** Monitor for `samples_pending` growth after reshards
- **User Impact:** Remote-write destination misses samples during target discovery scaling events
- **Root:** Synchronization gap between queue closure and final batch transmission during resharding
