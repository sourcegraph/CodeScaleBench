# Service Deployment Pattern Discovery

## Your Task

You are a platform engineer onboarding new service teams to the Kubernetes ecosystem.
You need to identify and document **the canonical patterns for deploying new services**
and how these patterns are defined and documented across the Kubernetes repos.

**Your question**: Find the canonical patterns for deploying new services and how
they are documented across repos. Specifically:

1. **API type definition** — Where is the authoritative `Deployment` struct defined
   in the Kubernetes API types repo? Identify the file and the struct name.
2. **Client-side code pattern** — Where is the canonical Go code example showing
   how to create a Deployment using the client library? Identify the file with the
   programmatic create pattern.
3. **Developer documentation** — Where is the README or documentation file that
   explains the deployment workflow (Create, Update, List, Delete)?

For each, cite the specific repository, file path, and the key type/function/document.

## Context

You are working with the Kubernetes ecosystem in a cross-org environment:

- Local `/workspace/kubernetes/` — `kubernetes/kubernetes` (core orchestrator)
- Accessible via Sourcegraph MCP:
  - `sg-benchmarks/kubernetes-client-go` (go-client-library)
  - `sg-benchmarks/kubernetes-api` (api-type-definitions)
  - `etcd-io/etcd` (distributed-kv-store)

This question is specifically designed to benefit from cross-repo synthesis. The
deployment pattern spans the API types repo, the client library repo, and documentation
— none of which is fully visible from any single repo.

## Output Format

Create a file at `/workspace/answer.json` with your findings:

```json
{
  "files": [
    {
      "repo": "sg-benchmarks/kubernetes-api",
      "path": "relative/path/to/file.go",
      "description": "What this file contains and its role in the deployment pattern"
    }
  ],
  "text": "Comprehensive narrative explaining the canonical deployment patterns, citing specific files, types, and functions from each repo. Mention the deploymentsClient pattern, the Deployment struct with its replicas field, and the documented workflow."
}
```

**Important**: Use exact repo identifiers as they appear in Sourcegraph. The oracle expects entries for `sg-benchmarks/kubernetes-api` (API type definitions) and `sg-benchmarks/kubernetes-client-go` (client examples and docs). The `repo` field must match these exactly.
**Note**: Sourcegraph MCP tools return repo names with a `github.com/` prefix (e.g., `github.com/sg-benchmarks/kubernetes-client-go`). Strip this prefix in your answer — use `sg-benchmarks/kubernetes-client-go`, NOT `github.com/sg-benchmarks/kubernetes-client-go`.

The `files` list should include at least 3 files across 2+ repos that together define
the canonical service deployment pattern.

## Evaluation

Your answer will be scored on:
- **File coverage**: Does the answer identify the key files from the API types repo and client-go examples?
- **Keyword accuracy**: Does your narrative mention `deploymentsClient`, `Deployment`, `replicas`, and `Create`?
- **Provenance**: Does your narrative reference the specific repos and file paths?
- **Synthesis quality** (supplementary): Does the explanation synthesize these into a cohesive deployment pattern a new team could follow?
