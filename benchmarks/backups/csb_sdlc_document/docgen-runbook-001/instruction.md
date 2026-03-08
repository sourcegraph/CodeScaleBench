# Task: Generate Operational Runbook for Prometheus TSDB Compaction

**Repository:** prometheus/prometheus
**Output:** Write your runbook to `/workspace/documentation.md`

## Objective

Produce an operational runbook for Prometheus's TSDB (Time Series Database) compaction process. TSDB compaction merges overlapping time blocks, removes tombstoned series, and maintains query performance over time.

## Scope

Explore the TSDB compaction implementation in:
- `tsdb/compact.go` — core compaction logic
- `tsdb/head_read.go` and `tsdb/head.go` — head block behavior
- `tsdb/db.go` — database lifecycle and compaction triggering

## Required Sections

Your runbook at `/workspace/documentation.md` must include:

### 1. Overview
- What compaction does and why it is needed
- Compaction levels and block structure
- When compaction is triggered (time-based, size-based)

### 2. Monitoring Indicators
- Key Prometheus metrics to watch during compaction (e.g., `prometheus_tsdb_compactions_total`, `prometheus_tsdb_compaction_duration_seconds`)
- Alert thresholds and what they indicate
- How to distinguish healthy vs. stuck compaction

### 3. Failure Modes
- At least 4 failure modes with symptoms and causes:
  - Disk space exhaustion
  - Compaction stuck / not progressing
  - Block corruption
  - OOM during compaction
- For each: symptom, likely cause, and diagnostic steps

### 4. Recovery Procedures
- Step-by-step recovery for each failure mode
- When to restart Prometheus vs. manual block manipulation
- How to use `promtool tsdb` commands for inspection/repair

### 5. Code Reference
- Key functions in the codebase relevant to each failure mode

## Quality Bar

- Metric names must be real (verify in the codebase)
- Recovery steps must be numbered and actionable
- Each failure mode must link to a specific code location
