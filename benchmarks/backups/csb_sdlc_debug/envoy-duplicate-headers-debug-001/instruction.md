# Investigation: Duplicate Response Headers in Envoy Filter Pipeline

**Repository:** envoyproxy/envoy
**Task Type:** Deep Causal Chain (investigation only — no code fixes)

## Scenario

An Envoy proxy operator reports that response headers configured via `response_headers_to_add` in route configuration are being **duplicated** in certain responses. Specifically, when the router filter generates a local reply (e.g., upstream timeout, connection failure, or request too large), custom response headers like `x-request-id-echo` appear twice in the HTTP response.

The issue is intermittent — it only affects responses where the router itself generates the reply (local replies) rather than forwarding an upstream response. Normal proxied responses have headers added exactly once.

Access log snippet showing the problem (using `%RESPONSE_CODE_DETAILS%` formatter):

```
[2025-08-15T10:23:45.001Z] "GET /api/v1/data HTTP/1.1" 504 UT
response_code_details=upstream_response_timeout
x-custom-trace: abc123
x-custom-trace: abc123
```

The header `x-custom-trace` appears twice. The route config has:

```yaml
response_headers_to_add:
  - header:
      key: "x-custom-trace"
      value: "%REQ(x-request-id)%"
    append_action: OVERWRITE_IF_EXISTS_OR_ADD
```

Despite using `OVERWRITE_IF_EXISTS_OR_ADD`, the header is duplicated on local replies but not on proxied upstream responses.

## Your Task

Investigate the root cause of this duplicate header behavior and produce a report at `/logs/agent/investigation.md`.

Your report MUST cover:

1. **How the router filter processes response headers** — specifically the `finalizeResponseHeaders()` call chain and the `modify_headers_` callback
2. **How local replies are generated** — the `sendLocalReply` code path in the router and how it differs from the upstream response path
3. **The specific mechanism causing double processing** — which PR/change moved `finalizeResponseHeaders()` into the `modify_headers_` callback, and why this causes double invocation for local replies
4. **The interaction between `sendLocalReply` and `modify_headers_`** — how `sendLocalReply` calls `finalizeResponseHeaders()` directly, AND the `modify_headers_` callback also calls it, resulting in headers being added twice
5. **The role of the `append_action` / `append` proto fields** — how `HeaderValueOption` config is parsed in `header_parser.cc`, including the deprecated `append` BoolValue field vs the newer `append_action` enum, and how proto default values affect behavior
6. **The filter manager's encode path** — how `FilterManager::encodeHeaders()` iterates through filters in reverse order and how the header mutation filter interacts with route-level header additions
7. **Which files and functions form the full causal chain** from symptom (duplicate headers in access log) to root cause (double `finalizeResponseHeaders()` call)

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

## Causal Chain
<Ordered list: symptom → intermediate hops → root cause>

## Recommendation
<Fix strategy and diagnostic steps>
```

## Constraints

- Do NOT write any code fixes
- Do NOT modify any source files
- Your job is investigation and analysis only
- The causal chain spans at least 4 packages: `source/common/router/`, `source/common/http/`, `source/extensions/filters/http/header_mutation/`, and `api/envoy/config/core/v3/`
