# Investigation Report: Remote-Write Queue Resharding Failure

## Summary

The remote-write queue resharding failure is caused by a race condition between the old shards being stopped and new shards being started. When resharding occurs, the `softShutdown` channel is closed to prevent new enqueues, but this creates a window where in-flight samples cannot be enqueued to either old or new shards, causing samples to accumulate with metrics showing `prometheus_remote_storage_samples_pending` stuck at values greater than zero.

## Root Cause

**Location:** `storage/remote/queue_manager.go:1184-1199` (reshardLoop) and `storage/remote/queue_manager.go:1269-1305` (stop function)

**Specific Issue:** The resharding mechanism has a critical race condition in the state transition:

```go
func (t *QueueManager) reshardLoop() {
    for {
        select {
        case numShards := <-t.reshardChan:
            t.shards.stop()      // Line 1193: Closes softShutdown
            t.shards.start(numShards)  // Line 1194: Creates new shards
```

When `stop()` is called:
1. Line 1275: `close(s.softShutdown)` immediately closes the channel
2. Lines 1281-1285: The function takes a write lock and calls `FlushAndShutdown()` on all queues
3. Lines 1286-1290: Waits up to `flushDeadline` for graceful shutdown

**The Race Condition:**

```go
func (s *shards) enqueue(ref chunks.HeadSeriesRef, data timeSeries) bool {
    s.mtx.RLock()
    defer s.mtx.RUnlock()
    shard := uint64(ref) % uint64(len(s.queues))
    select {
    case <-s.softShutdown:    // Line 1317: After softShutdown is closed,
        return false           // ALL future enqueues immediately return false
    default:
        appended := s.queues[shard].Append(data)
```

**Timeline of Failure:**

1. **T0**: `updateShardsLoop()` determines resharding is needed, sends signal on `reshardChan`
2. **T1**: `reshardLoop()` receives signal and calls `t.shards.stop()`
3. **T2**: `stop()` closes `softShutdown` channel at line 1275
4. **T3**: In-flight `Append()` calls from TSDB try to `enqueue()`:
   - The `select` statement on line 1316 immediately reads from closed `softShutdown`
   - `enqueue()` returns `false` without attempting to queue the sample
   - The `Append()` caller retries with exponential backoff (see line 748)
5. **T4**: `stop()` acquires write lock and calls `FlushAndShutdown()` on old queues
6. **T5**: **Critical Window**: Old shards are being flushed, but new shards haven't started yet
   - Any samples trying to enqueue will fail
   - The retry loop in `Append()` continues with backoff
7. **T6**: `start()` creates new shards and begins accepting samples
8. **T7**: Retrying `Append()` calls finally succeed

**Problem:** If the retry loop encounters max backoff or times out before new shards are ready, or if samples experience multiple failed enqueues, they may be dropped due to age limits or backoff exhaustion (see line 706-708 in the `Append()` function).

## Evidence

### Code References

1. **Resharding Loop** (`queue_manager.go:1184-1199`):
   - Shows sequential `stop()` -> `start()` transition
   - No synchronization between old shards being fully shutdown and new shards accepting samples

2. **Stop Function** (`queue_manager.go:1269-1305`):
   - Line 1275: `close(s.softShutdown)` - immediately blocks all enqueues
   - Line 1281: Write lock only taken AFTER softShutdown is closed
   - Race window exists between line 1275 and 1281

3. **Enqueue Function** (`queue_manager.go:1312-1341`):
   - Line 1316-1318: Select statement on closed channel immediately returns false
   - Line 1317: `case <-s.softShutdown:` - reading from closed channel always succeeds
   - No attempt to enqueue when softShutdown is closed

4. **Append Function** (`queue_manager.go:700-758`):
   - Line 706-708: Samples older than `SampleAgeLimit` are dropped
   - Line 729-755: Exponential backoff retry loop with max backoff
   - If backoff exceeds max before new shards start, enqueue attempts stop

5. **CHANGELOG References**:
   - Line 1457: "BUGFIX Remote Write: Fixed blocked resharding edge case. #7122"
   - Line 1572: "BUGFIX Remote write: do not reshard when unable to send samples. #6111"

### Metrics Confirming Issue

The metric `prometheus_remote_storage_samples_pending` will show:
- Value > 0 after resharding completes
- Sustained stall with no progress (samples not being flushed)
- Metrics would indicate samples stuck in queues during the resharding window

### Why It's Intermittent

The issue is **timing-dependent and appears intermittent** because:

1. **Target discovery timing**: When targets are added/removed, it takes time for metrics to flow through the system. The timing of when these metrics hit the queue during resharding determines if they're lost.

2. **Load characteristics**:
   - High load = more samples in flight = higher chance of hitting the race window
   - Low load = fewer samples in flight = may not encounter the condition
   - Specific metric patterns matter

3. **System responsiveness**:
   - Fast systems: New shards start quickly, minimizing the race window
   - Slow systems: Larger window, higher probability of sample loss

4. **Backoff timing**: Whether retry backoff aligns with the stop/start window affects whether samples are successfully requeued

## Affected Components

1. **`storage/remote/queue_manager.go`**:
   - `QueueManager.reshardLoop()` - orchestrates reshard
   - `QueueManager.updateShardsLoop()` - triggers reshard decision
   - `shards.stop()` - initiates shutdown
   - `shards.start()` - creates new shards
   - `shards.enqueue()` - attempts to queue samples

2. **`storage/remote/queue_manager.go` - queue operations**:
   - `queue.FlushAndShutdown()` - flushing during stop
   - `queue.Append()` - initial queueing attempt

3. **Metrics affected**:
   - `prometheus_remote_storage_samples_pending` - will show non-zero stuck values
   - `prometheus_remote_storage_samples_dropped_total` - if samples exceed age limit

4. **Related test file**:
   - `storage/remote/queue_manager_test.go` - contains resharding test scenarios

## Recommendation

### Fix Strategy

The fix should ensure samples in-flight during resharding can reach either old or new shards by:

1. **Option A: Synchronous State Transition** - Don't close `softShutdown` until new shards are ready to accept samples:
   - Create new shards first
   - Only then close old shards' `softShutdown`
   - This ensures a continuous path for samples

2. **Option B: Atomic Shard Swap** - Use an atomic swap of the shards pointer:
   - Create new shards and have them ready
   - Atomically update the shard pointer
   - Allow `enqueue()` to try a configurable number of times with the old shard count
   - This maintains backward compatibility with in-flight calculations

3. **Option C: Quiescing Before Resharding** - Enhanced shouldReshard check:
   - Implement a pre-resharding quiesce period where no new enqueues are accepted
   - Wait until all pending samples are flushed
   - Then perform resharding with no in-flight samples
   - Matches the intent of PR #6111 ("do not reshard when unable to send samples")

### Diagnostic Steps

To confirm this root cause in production, check for:

1. **Logs showing sequential resharding**:
   ```
   msg="Remote storage resharding" from=4 to=6
   msg="Resharding done" numShards=6
   ```
   followed by pending samples metric stuck at non-zero

2. **Metrics queries**:
   - `prometheus_remote_storage_samples_pending{job="prometheus"}` - should return to 0 eventually
   - `increase(prometheus_remote_storage_samples_dropped_total[5m])` - check for spikes during resharding

3. **Trace sampling**:
   - Enable debug logging for queue manager
   - Look for patterns of `case <-s.softShutdown: return false` in enqueue attempts
   - Correlate with resharding log messages

4. **Timing analysis**:
   - Measure time between "resharding from X to Y" log and "resharding done"
   - Correlate with target discovery events from scrape manager
   - Check if delays in new shard startup correlate with sample loss

## Additional Notes

The CHANGELOG entry for PR #7122 ("Fixed blocked resharding edge case") suggests this issue was identified and partially addressed, but the current code still exhibits the race condition. The fix may have addressed one manifestation (completely blocked resharding) but not the more subtle case of partial sample loss during the transition window.
