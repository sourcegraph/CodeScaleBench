# Domain Lineage: Envoy xDS Configuration Discovery Service Flow

## Your Task

Trace how an xDS configuration update flows from the control plane to Envoy's data plane. Find: 1. In `envoyproxy/go-control-plane`: the Go source files that define the `DiscoveryRequest` and `DiscoveryResponse` types and the `StreamAggregatedResources` gRPC handler. 2. In `envoyproxy/data-plane-api`: the `.proto` files that define the `AggregatedDiscoveryService` and `DeltaDiscoveryService` RPCs. 3. In `envoyproxy/envoy`: the C++ source files under `source/common/config/` that implement the xDS client subscription logic (look for `GrpcSubscriptionImpl` or `XdsResourceDelegate`). Report the repo, file path, and key type/service name for each hop in the configuration delivery chain.

## Context

You are working on a codebase task involving repos from the domain domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/envoy--v1.31.2, sg-evals/data-plane-api--84e84367, sg-evals/go-control-plane--71637ad6, sg-evals/grpc--957dba5e.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/envoy--v1.31.2` (envoyproxy/envoy)
- `sg-evals/data-plane-api--84e84367` (envoyproxy/data-plane-api)
- `sg-evals/go-control-plane--71637ad6` (envoyproxy/go-control-plane)
- `sg-evals/grpc--957dba5e` (grpc/grpc)

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go"}
  ],
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?
