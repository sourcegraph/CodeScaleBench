# Investigation: Remote-Write Queue Resharding Failure

**Repository:** prometheus/prometheus
**Task Type:** Cross-Service Debug (investigation only — no code fixes)

## Scenario

After a Prometheus upgrade, remote-write destinations intermittently stop receiving samples. The issue correlates with target discovery changes — when targets are added or removed, some remote-write shards stall.

Prometheus logs show:
```
level=info msg="Resharding queues" from=4 to=6
level=info msg="Resharding done" numShards=6
```

But after resharding, metrics show some shards have `prometheus_remote_storage_samples_pending` stuck at >0 with no progress.

## Your Task

Investigate the root cause and produce a report at `/logs/agent/investigation.md`.

Your report MUST cover:
1. How remote-write queue resharding works (which files/functions)
2. What changed in the resharding logic recently
3. The specific mechanism causing shards to stall
4. Why the issue is intermittent (timing/race condition)
5. Which metrics or logs would confirm the root cause

## Output Requirements

Write your investigation report to `/logs/agent/investigation.md` with these sections:

```
# Investigation Report

## Summary
<1-2 sentence finding>

## Root Cause
<Specific file, function, and mechanism>

## Evidence
<Code references with file paths and line numbers>

## Affected Components
<List of packages/modules impacted>

## Recommendation
<Fix strategy and diagnostic steps>
```

## Constraints

- Do NOT write any code fixes
- Do NOT modify any source files
- Your job is investigation and analysis only
- Focus on `storage/remote/` package, particularly queue management and shard calculation
