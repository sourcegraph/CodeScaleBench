# Investigation Report: Remote-Write Queue Resharding Failure

## Summary

The intermittent remote-write sample stall is caused by a race condition during queue resharding where incoming samples continuously retry enqueue operations (holding locks) while the resharding process times out waiting for old shards to flush, triggering a hard shutdown that silently drops all pending data. The issue is exacerbated when recoverable errors occur, causing aggressive resharding attempts that worsen lock contention.

## Root Cause

**Location:** `storage/remote/queue_manager.go`, specifically in the interaction between `reshardLoop()` (lines 1184-1199), `stop()` (lines 1269-1305), `enqueue()` (lines 1312-1341), and `Append()` (lines 702-758).

### Mechanism

The resharding process has a critical race condition:

1. **Resharding Trigger** (line 1072-1077 in `updateShardsLoop()`):
   - Sends desired shard count to `reshardChan`
   - Immediately updates `t.numShards` (line 1074)
   - Does NOT wait for actual resharding to complete

2. **Resharding Execution** (line 1189-1194 in `reshardLoop()`):
   ```go
   case numShards := <-t.reshardChan:
       t.shards.stop()      // Flush old shards
       t.shards.start(numShards)  // Start new shards
   ```

3. **The Race Condition**:
   - `stop()` (line 1269-1305):
     - Takes `RLock` to close `softShutdown` (line 1274-1275)
     - Takes `Lock` to flush queues (line 1281)
     - Waits up to `flushDeadline` for all queues to flush (line 1286-1290)

   - `Append()` & `enqueue()` (line 702-758, 1312-1341):
     - `enqueue()` holds `RLock` while appending to queue (line 1313-1314)
     - If queue is full (being flushed), returns false
     - `Append()` retries immediately with backoff (line 748-754)
     - **Tight retry loop holds `RLock` repeatedly**

   - **Result**: `stop()` cannot acquire `Lock` because `RLock` holders (`Append()` retries) never fully release the lock. After `flushDeadline` timeout, `hardShutdown()` is triggered (line 1293) which **silently drops all pending samples** (line 1569-1578 in `runShard()`).

### Why It's Intermittent

The timing of the race depends on:

1. **Target discovery rate**: Rapid target additions = rapid resharding = more window for race
2. **Sample arrival rate**: Higher rate = more `Append()` calls = tighter retry loop
3. **Network conditions**: When recoverable errors occur (429, 503), backoff increases from 5ms to MaxBackoff, making the problem worse
4. **Shard hash distribution**: New series may hash to queues that are full, causing more retries

## Evidence

### Code References

**1. The Retry Loop (file: storage/remote/queue_manager.go:731-755)**
```
731:    for {
732:        select {
733:        case <-t.quit:
734:            return false
735:        default:
736:        }
737:        if t.shards.enqueue(s.Ref, timeSeries{...}) {
738:            continue outer
739:        }
740:        t.metrics.enqueueRetriesTotal.Inc()
741:        time.Sleep(time.Duration(backoff))
742:        backoff *= 2
743:        if backoff > t.cfg.MaxBackoff {
744:            backoff = t.cfg.MaxBackoff
745:        }
746:    }
```
**Issue**: Tight retry loop without yielding locks. Each retry calls `enqueue()` which takes `RLock`.

**2. The Stop Timeout (file: storage/remote/queue_manager.go:1286-1294)**
```
1286:   select {
1287:   case <-s.done:
1288:       return
1289:   case <-time.After(s.qm.flushDeadline):
1290:   }
1291:   // Force an unclean shutdown.
1292:   s.hardShutdown()
1293:   <-s.done
```
**Issue**: Hard shutdown triggered if flush doesn't complete in time.

**3. Hard Shutdown Sample Drop (file: storage/remote/queue_manager.go:1563-1578)**
```
1563:   case <-ctx.Done():  // hardShutdown cancels ctx
1564:       // In this case we drop all samples in the buffer and the queue.
1565:       droppedSamples := int(s.enqueuedSamples.Load())
1566:       droppedExemplars := int(s.enqueuedExemplars.Load())
1567:       droppedHistograms := int(s.enqueuedHistograms.Load())
1568:       s.qm.metrics.pendingSamples.Sub(float64(droppedSamples))
1569:       s.qm.metrics.failedSamplesTotal.Add(float64(droppedSamples))
1570:       s.samplesDroppedOnHardShutdown.Add(uint32(droppedSamples))
1571:       return
```
**Issue**: All samples are dropped silently (marked as "failed" but process never notified).

**4. Recoverable Error Handling (file: storage/remote/queue_manager.go:2014-2029)**
```
2014:   // We should never reshard for a recoverable error; increasing shards could
2015:   // make the problem worse, particularly if we're getting rate limited.
2016:
2017:   // reshardDisableTimestamp holds the unix timestamp until which resharding
2018:   // is disabled. We'll update that timestamp if the period we were just told
2019:   // to sleep for is newer than the existing disabled timestamp.
2020:   reshardWaitPeriod := time.Now().Add(time.Duration(sleepDuration) * 2)
2021:   if oldTS, updated := setAtomicToNewer(&t.reshardDisableEndTimestamp, reshardWaitPeriod.Unix()); updated {
2022:       // If the old timestamp was in the past, then resharding was previously
2023:       // enabled. We want to track the time where it initially got disabled for
2024:       // logging purposes.
2025:       disableTime := time.Now().Unix()
2026:       if oldTS < disableTime {
2027:           t.reshardDisableStartTimestamp.Store(disableTime)
2028:       }
2029:   }
```
**Evidence**: This is the mitigation—resharding is disabled during recoverable errors to prevent aggressive resharding during backoff.

**5. Metrics Reset During Resharding (file: storage/remote/queue_manager.go:1241)**
```
1241:   s.qm.metrics.pendingSamples.Set(0)
```
**Issue**: While starting new shards, `pendingSamples` is reset to 0 without waiting for old shard goroutines to finish sending. Meanwhile, old shard goroutines may still call `updateMetrics()` (line 1689) to decrement the metric. This can:
- Cause metric to become inaccurate
- Undercount actual pending data
- Hide the data loss from monitoring

**6. Hash Function Sensitivity (file: storage/remote/queue_manager.go:1315)**
```
1315:   shard := uint64(ref) % uint64(len(s.queues))
```
**Issue**: When shard count changes (e.g., 4→6), series hash to different queues, causing potential queue rebalancing issues during transition.

## Affected Components

1. **storage/remote/queue_manager.go**:
   - `QueueManager.updateShardsLoop()` - triggers resharding
   - `QueueManager.reshardLoop()` - executes resharding
   - `shards.enqueue()` - routes samples to queues
   - `shards.stop()` - flushes and shuts down old queues
   - `shards.start()` - creates new queues
   - `QueueManager.Append()` - enqueues samples with retry logic
   - `shards.runShard()` - sends samples (hard shutdown path)

2. **storage/remote/queue_manager.go (metrics)**:
   - `prometheus_remote_storage_samples_pending` - stuck at >0
   - `prometheus_remote_storage_samples_failed_total` - silently incremented during hard shutdown
   - `prometheus_remote_storage_enqueue_retries_total` - high during resharding stress

3. **Timing Constants** (line 55):
   - `shardUpdateDuration = 10 * time.Second` - resharding check interval
   - `flushDeadline` (from config) - timeout for queue flush during reshard

## Recommendation

### Root Fix Strategy

**Short-term mitigations already in code (line 2020-2029)**:
1. Disable resharding when recoverable errors occur
2. Keep resharding disabled for 2x the backoff duration
3. This prevents aggressive resharding during high error rates

**Recommended additional fixes**:

1. **Break Retry Lock Contention**:
   - Add lock-yielding in `Append()` retry loop to prevent tight RLock spinning
   - Use exponential backoff starting higher (e.g., 100ms instead of 5ms) to reduce retry frequency
   - Consider using `time.NewTimer` with select instead of tight Sleep loops

2. **Increase Flush Timeout**:
   - Make `flushDeadline` adaptive based on queue depth
   - At resharding time, estimate how long flushing will take based on pending sample count
   - Warn in logs when approaching timeout

3. **Decouple Resharding**:
   - Don't update `t.numShards` immediately; only update after resharding completes
   - This prevents new `Append()` calls from seeing stale shard count during transition

4. **Better Visibility**:
   - Log when hard shutdown is triggered (include pending sample count)
   - Add histogram metric for time spent in `reshardLoop()`
   - Track `prometheus_remote_storage_hard_shutdown_total` counter

### Diagnostic Steps

To confirm this is the root cause in a failing system:

1. **Check these metrics**:
   ```
   prometheus_remote_storage_samples_pending{job="prometheus"}  # Should be 0
   prometheus_remote_storage_enqueue_retries_total               # High during failure
   prometheus_remote_storage_shards                              # Changing during failure
   prometheus_remote_storage_samples_failed_total                # Sudden spike
   ```

2. **Check logs for**:
   ```
   "Remote storage resharding from=X to=Y"         # Reshard triggered
   "Currently resharding, skipping."                # Reshard blocked (buffered channel full)
   "Skipping resharding, resharding is disabled"   # Recoverable error disable
   ```

3. **Look for pattern**:
   - `Resharding` log appears
   - `enqueue_retries_total` counter starts increasing rapidly
   - After ~flushDeadline (~5s), `samples_failed_total` increases suddenly
   - `samples_pending` drops to 0 (hard shutdown completed)
   - No logs from samples being sent

4. **Network condition correlation**:
   - Check if failures correlate with 429/503 errors from remote endpoint
   - Verify if target discovery changes happened around failure time
   - Compare `last_send_timestamp` vs current time (>10s indicates send stall)

### Prevention

1. Monitor `prometheus_remote_storage_samples_pending` - alert if stuck for >1 minute
2. Monitor `prometheus_remote_storage_hard_shutdown_samples` - should always be 0
3. Monitor `prometheus_remote_storage_samples_failed_total` growth rate - should be slow
4. Set `max_shards` conservatively to reduce resharding frequency
5. Configure appropriate `flush_deadline` (default may be too low for high-volume scenarios)
