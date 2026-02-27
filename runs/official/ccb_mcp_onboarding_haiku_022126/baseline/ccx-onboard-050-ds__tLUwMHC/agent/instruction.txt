# End-to-End: How Kubernetes Creates a Deployment

## Your Task

You are onboarding to the Kubernetes project. A senior engineer has asked you to produce
a technical explanation of how a Kubernetes Deployment gets created — tracing the full
request flow from a client application through the API server and into persistent storage.

**Your question**: Explain how a Kubernetes client application creates a Deployment from
start to finish. Your explanation must trace through all three layers:

1. **Client library** — What type/function in `kubernetes-client-go` sends the HTTP request?
2. **API server** — What function in `kubernetes/kubernetes` receives and validates the create request?
3. **Storage** — What function in `etcd-io/etcd` persists the Deployment to the key-value store?

For each step, cite the specific repository, file path, and function/type name.

## Context

You are working in a Kubernetes ecosystem with the following repos:

- Local `/workspace/kubernetes/` — `kubernetes/kubernetes` (the core orchestrator)
- Accessible via Sourcegraph MCP:
  - `sg-benchmarks/kubernetes-client-go` (go-client-library)
  - `sg-benchmarks/kubernetes-api` (api-type-definitions)
  - `etcd-io/etcd` (distributed-kv-store)

This question is specifically designed to benefit from cross-repo synthesis. Use your
search tools to trace the full path across repositories.

## Output Format

Create a file at `/workspace/answer.json` with your findings:

```json
{
  "chain": [
    {
      "repo": "sg-benchmarks/kubernetes-client-go",
      "path": "relative/path/to/file.go",
      "symbol": "FunctionOrTypeName",
      "description": "What this step does in the flow"
    }
  ],
  "text": "Comprehensive narrative explaining the end-to-end flow, citing specific files and functions from each repo."
}
```

**Important**: Use exact repo identifiers as they appear in Sourcegraph. The oracle expects `repo` values of `sg-benchmarks/kubernetes-client-go` (client layer), `kubernetes/kubernetes` (API server layer), and `etcd-io/etcd` (storage layer). The `repo` field must match these exactly.
**Note**: Sourcegraph MCP tools return repo names with a `github.com/` prefix (e.g., `github.com/sg-benchmarks/kubernetes-client-go`). Strip this prefix in your answer — use `sg-benchmarks/kubernetes-client-go`, NOT `github.com/sg-benchmarks/kubernetes-client-go`.

The `chain` should contain at least 3 steps representing the 3 layers described above.

## Evaluation

Your answer will be scored on:
- **Flow coverage**: Does the chain include key steps from all 3 layers (client → server → storage)?
- **Technical accuracy**: Are the cited file paths and function names correct?
- **Provenance**: Does your narrative reference all three repositories?
- **Synthesis quality** (supplementary): Does the explanation connect the layers clearly?
