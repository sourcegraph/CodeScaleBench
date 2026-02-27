# Investigation Report: Remote-Write Queue Resharding Stall

## Summary
Remote-write queue resharding can cause samples to become permanently lost when partial batches fail to flush before hard shutdown timeout expires during queue transition. The lost samples appear as stalled shards with pending samples stuck above zero but no delivery progress.

## Root Cause

**Location:** `storage/remote/queue_manager.go:1447-1455` in `queue.FlushAndShutdown()`

The resharding process stalls due to a **race condition in partial batch cleanup** during queue shutdown:

```go
func (q *queue) FlushAndShutdown(done <-chan struct{}) {
    for q.tryEnqueueingBatch(done) {
        time.Sleep(time.Second)
    }
    q.batchMtx.Lock()
    defer q.batchMtx.Unlock()
    q.batch = nil                    // <-- BUG: Discards unsent samples
    close(q.batchQueue)
}
```

### Failure Scenario

1. **Resharding triggered** (e.g., 4→6 shards): `updateShardsLoop()` detects need to reshard
   - Sends desired shard count to `reshardChan`
   - `reshardLoop()` begins shutdown of old shards

2. **Old queue shutdown begins**: `shards.stop()` is called
   - Closes `softShutdown` channel (prevents new enqueues)
   - Spawns goroutines calling `queue.FlushAndShutdown()` for each queue
   - Waits for completion with `flushDeadline` timeout (default: 1 minute)

3. **Partial batch accumulation**: Old queue has partial batch with unsent samples
   - `tryEnqueueingBatch()` attempts to send batch to `batchQueue` channel
   - Channel is full (all downstream `runShard()` workers are busy)
   - Returns true to retry (line 1475)
   - Loop sleeps 1 second

4. **Hard shutdown timeout expires**: Before partial batch flushes
   - `stop()` timeout is reached (flushDeadline)
   - Calls `hardShutdown()` which cancels the context passed to `runShard()`
   - Signals the `done` channel

5. **Critical bug triggered**:
   - `tryEnqueueingBatch()` receives `<-done` signal (line 1469)
   - Returns false (line 1472) - exits flush retry loop
   - `q.batch = nil` executes (line 1453)
   - **All samples in the partial batch are permanently lost**
   - Never reaches `runShard()`, never tracked in failure metrics
   - Queue is closed (line 1454)

6. **New shards start** with `pendingSamples` reset to 0
   - Metrics show 0 pending, masking the data loss

## Evidence

### Code References

1. **Queue Shutdown Logic** (`storage/remote/queue_manager.go:1269-1305`)
   - `shards.stop()`: Initiates soft shutdown, spawns FlushAndShutdown goroutines, waits with timeout
   - Relevant: Hard shutdown triggered if flush exceeds `flushDeadline`

2. **Partial Batch Loss** (`storage/remote/queue_manager.go:1447-1477`)
   - `queue.FlushAndShutdown()`: Attempts to flush partial batch with retries
   - `tryEnqueueingBatch()`: Returns false when hard shutdown signal received, exiting retry loop
   - Missing: Logic to track/log samples lost in partial batch

3. **Shard Worker** (`storage/remote/queue_manager.go:1491-1600`)
   - `runShard()`: Receives batches from `batchQueue` channel
   - When context cancelled, drops remaining samples and logs error
   - But samples in *partial batch* (not yet in channel) are not counted

4. **Metrics Reset** (`storage/remote/queue_manager.go:1237-1266`)
   - `shards.start()`: Creates new queues and sets `pendingSamples.Set(0)` (line 1241)
   - Timing issue: Old shards' remaining samples may still be pending when metric is reset

### Timing Sensitivity

The bug manifests intermittently due to race conditions:

**Conditions Required:**
- Resharding occurs while old queue has partial batch (non-empty `q.batch`)
- `batchQueue` channel fills up faster than `runShard()` workers can drain it
- Hard shutdown timeout (default 1 minute) expires before batch can be flushed
- Network latency/remote endpoint slowness backs up the pipeline

**Why It's Intermittent:**
- Depends on when resharding happens relative to network conditions
- Depends on how full the queue is at reshard time
- Depends on remote storage response times
- More likely when targets frequently added/removed (triggering resharding)
- More likely with slow remote endpoints or high latency networks

## Affected Components

### Primary Files
- `storage/remote/queue_manager.go` - Queue management, resharding logic
  - `QueueManager` struct (line 417)
  - `shards` struct (line 1209)
  - `queue` struct (line 1343)
  - Resharding functions (lines 1057-1199)
  - Queue flush logic (lines 1445-1477)

### Related Components
- `tsdb/wlog/watcher.go` - WAL Watcher that calls `Append()` and retries
  - Should detect retries but lost samples bypass this
- Remote write metrics:
  - `prometheus_remote_storage_samples_pending` - Reset to 0 when new shards start
  - `prometheus_remote_storage_samples_dropped_total` - Not incremented for lost partials
  - `prometheus_remote_storage_sent_batch_duration_seconds` - Shows no activity when samples stall

## Why Metrics Show Stall

1. **Stalled shards appear to have pending samples** (>0)
   - WAL Watcher hasn't retried the lost samples yet (they were dequeued)
   - Or WAL replay is catching up slowly

2. **No progress on delivery**
   - The partial batch samples never reached remote storage
   - Never appear in failed metrics or logs
   - Metrics reset when new shards start (line 1241)

3. **Intermittent nature explains variability**
   - Only affects samples in partial batches during unlucky reshard timing
   - May only lose tens or hundreds of samples, not entire queue
   - Lost samples not tracked = mysterious stalls

## Recommended Diagnostics

To confirm this root cause:

### 1. Check Logs for Reshard/Shutdown Patterns
```
Look for sequence:
  "Resharding queues" from=4 to=6
  "Failed to flush all X on shutdown" (if hard shutdown was triggered)

Timeline gap between reshard message and next samples indicates loss window
```

### 2. Monitor Timing Metrics
```
Track:
  - Time between "Resharding" log and "Resharding done" completion
  - If takes >50 seconds, approaching hard shutdown timeout
  - Number of shards with samples_pending after reshard
```

### 3. Enable Debug Logs for Queue Manager
```
Look for:
  "Currently resharding, skipping." - indicates resharding already in progress
  "QueueManager.calculateDesiredShards" - shows shard calc details
  "tryEnqueueingBatch" attempts (would need code instrumentation)
```

### 4. Create Test Case for Intermittent Reproduction
```
Trigger by:
  - Rapidly add/remove targets (force resharding)
  - Slow remote write endpoint
  - High sample rate
  - Restart during heavy reshard activity
```

## Fix Strategy

### Short-term Diagnostic Fix
Add logging in `FlushAndShutdown()` to detect partial batch loss:

```go
func (q *queue) FlushAndShutdown(done <-chan struct{}) {
    for q.tryEnqueueingBatch(done) {
        time.Sleep(time.Second)
    }
    q.batchMtx.Lock()
    defer q.batchMtx.Unlock()

    if len(q.batch) > 0 {
        // Log the samples that are being lost
        q.qm.logger.Error("Samples lost during hard shutdown",
            "count", len(q.batch))
    }
    q.batch = nil
    close(q.batchQueue)
}
```

### Recommended Long-term Fixes

1. **Force final flush attempt after hard shutdown**
   - Add one more `tryEnqueueingBatch` call after receiving `<-done` signal
   - Accept samples will be dropped but ensure they're counted in metrics
   - Increment `failedSamplesTotal` for proper accounting

2. **Separate metric tracking**
   - Add new metric: `remote_storage_samples_lost_on_hard_shutdown`
   - Decouple from `failedSamplesTotal` (those are network failures)
   - Alert ops when samples lost during resharding

3. **Increase soft shutdown timeout or use two-phase approach**
   - Current 1-minute flush deadline may be too aggressive
   - Or implement soft-timeout followed by a final grace period
   - Give partial batches fair chance to flush

4. **Prevent concurrent reshard/stop**
   - Add mutex to prevent reshardLoop and Stop() from running simultaneously
   - Related to CHANGELOG issue #5460: "Prevent reshard concurrent with calling stop"

## Summary Table

| Aspect | Finding |
|--------|---------|
| **Root Cause** | Samples in partial batches discarded when hard shutdown timeout expires |
| **Location** | `queue.FlushAndShutdown()` at line 1453 |
| **Impact** | Data loss during resharding; appears as metrics stall |
| **Frequency** | Intermittent; depends on timing and network conditions |
| **Detection** | No error logs; metrics reset masks loss; WAL may show unexpected gap |
| **Fix Complexity** | Medium - requires metric tracking + flush logic changes |
| **Severity** | High - silent data loss during cluster operations |

## References

- CHANGELOG entries mentioning related issues:
  - "Remote-write: Fix deadlock when stopping a shard. #10279"
  - "Remote Write: Disable resharding during active retry backoffs #13562"
  - "Remote_write: Prevent reshard concurrent with calling stop #5460"
