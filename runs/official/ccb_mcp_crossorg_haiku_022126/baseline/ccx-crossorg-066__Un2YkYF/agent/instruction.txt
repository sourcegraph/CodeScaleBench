# Authoritative Repo Identification for a Cross-Org Dependency

## Your Task

Your team is resolving a dependency conflict and needs to identify the authoritative
source of truth for a widely-used Go module. Multiple repos in your ecosystem vendor
or depend on `go.etcd.io/etcd/client/v3`, but only one GitHub repository contains
the **authoritative module declaration** for this package.

**Specific question**: Which GitHub repository (org/repo format) is the authoritative
source of truth for the Go module `go.etcd.io/etcd/client/v3`? Provide evidence by
identifying the exact file path that contains the `module go.etcd.io/etcd/client/v3`
declaration.

## Context

In Go, every module has a canonical `go.mod` file that declares the module path with
`module <path>`. The repo that declares `module go.etcd.io/etcd/client/v3` is the
authoritative source. Other repos may vendor or depend on it but are NOT the source
of truth.

The `kubernetes/kubernetes` repo (available locally) vendors this module — you can
see this at `vendor/go.etcd.io/etcd/client/v3/`. However, this is a vendored copy,
not the authoritative source. Your task is to find where this module is authoritatively
maintained.

## Available Resources

The local `/workspace/` directory contains all repositories:
- `kubernetes/kubernetes` at v1.32.0 → `/workspace/kubernetes`
- `etcd-io/etcd` at v3.5.17 → `/workspace/etcd`
- `grafana/grafana` at v11.4.0 → `/workspace/grafana`

## Output Format

Create a file at `/workspace/answer.json` with your findings:

```json
{
  "text": "The authoritative source for go.etcd.io/etcd/client/v3 is the <org>/<repo> repository. The module declaration `module go.etcd.io/etcd/client/v3` is at <file_path> in the <org>/<repo> repository. Evidence: [cite the specific file and module declaration]."
}
```

## Evaluation

Your answer is evaluated on:
- **Keyword presence**: Does your answer contain the exact module declaration string `module go.etcd.io/etcd/client/v3`?
- **Provenance**: Does your answer correctly cite the authoritative repository (`etcd-io/etcd`) and the module declaration file (`client/v3/go.mod`)?
