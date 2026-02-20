# Task: Write Integration Tests for Flipt Evaluation API

**Repository:** flipt-io/flipt
**Output:** Write your integration test file to `/workspace/integration/evaluation_integration_test.go`

## Objective

Author integration tests for Flipt's feature flag evaluation REST API. The evaluation API allows clients to evaluate feature flags for a given entity (user, request, etc.) and receive a variant or boolean response.

## Scope

Explore the Flipt codebase to understand the evaluation API handlers. Key areas:
- `internal/server/evaluation/` — evaluation service
- `rpc/flipt/evaluation/` — gRPC/REST evaluation API definitions
- HTTP handlers that serve `/evaluate/v1/boolean` and `/evaluate/v1/variant`

Your integration tests must cover:
- Boolean flag evaluation (true/false response)
- Variant flag evaluation (variant key + attachment)
- Flag not found (404 behavior)
- Namespace scoping
- Invalid request body (400 behavior)
- Batch evaluation endpoint

## Output Format

Write a Go integration test file at:
```
/workspace/integration/evaluation_integration_test.go
```

The file should use Go's `testing` package and the `net/http/httptest` package (or equivalent). Each test function must start with `Test`.

## Quality Bar

- At least 6 test functions
- Each function has at least one `t.Fatal` / `t.Error` assertion
- Cover both success and error paths
- Do not fabricate API paths — inspect the actual codebase first
- Do NOT run the tests yourself — write the test file and the evaluation system validates independently
