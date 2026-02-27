# Task: Generate Troubleshooting Runbook for Envoy Connection Pool Management

**Repository:** envoyproxy/envoy
**Output:** Write your runbook to `/workspace/documentation.md`

## Objective

Produce a troubleshooting runbook for Envoy's connection pool management. Envoy's connection pools manage upstream HTTP/1.1, HTTP/2, and TCP connections, and are a common source of production issues.

## Scope

Explore the connection pool implementation:
- `source/common/http/conn_pool_base.cc` and `source/common/http/conn_pool_base.h`
- `source/common/tcp/conn_pool.cc`
- `source/common/upstream/cluster_manager_impl.cc` — how pools are managed per cluster

## Required Sections

Your runbook at `/workspace/documentation.md` must include:

### 1. Architecture Overview
- How connection pools are organized (per-cluster, per-thread)
- The lifecycle of a connection in the pool (connecting, active, draining)
- HTTP/1.1 vs HTTP/2 pool differences

### 2. Common Failure Scenarios
Describe at least 4 failure scenarios with:
- **Symptom**: What the operator observes (metrics, logs, errors)
- **Root Cause**: What code path leads to this behavior
- **Diagnostic Steps**: Specific Envoy admin API calls or config checks
- **Fix**: Configuration change or code-level explanation

Scenarios to cover (at minimum):
1. Connection pool exhaustion (pending requests overflow)
2. Upstream connection reset / premature close
3. Circuit breaker triggering unexpectedly
4. HTTP/2 GOAWAY causing request failures

### 3. Diagnostic Commands
- Envoy admin API endpoints useful for diagnosing pool issues (`/clusters`, `/stats`)
- Key metrics: `upstream_cx_*`, `upstream_rq_*`, `circuit_breakers.*`
- How to read Envoy's access logs for connection pool errors

### 4. Configuration Fixes
- `max_connections` and `max_pending_requests` tuning
- `connect_timeout` and `per_connection_buffer_limit_bytes`
- Circuit breaker thresholds

### 5. Code References
- Key source files and functions for each failure mode

## Quality Bar

- Metric names must match actual Envoy stats (verify in source or admin API docs)
- Diagnostic steps must be actionable (specific curl commands to admin API)
- Configuration fixes must reference actual Envoy config field names
