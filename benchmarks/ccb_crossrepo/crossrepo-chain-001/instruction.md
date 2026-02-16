Trace the definition of `TypeMeta` through a chain of Kubernetes package dependencies.

## Background

In the Kubernetes ecosystem, core API types are defined across multiple repositories forming a dependency chain. The `TypeMeta` struct is a fundamental type embedded in all Kubernetes resource objects (Pod, Deployment, Service, etc.).

## Repositories

Three repositories are available under `/workspace/`:

- `/workspace/kubernetes/` — kubernetes/kubernetes (main Kubernetes repo with controller implementations)
- `/workspace/api/` — kubernetes/api (API type definitions for core resources)
- `/workspace/apimachinery/` — kubernetes/apimachinery (shared machinery and meta types)

## Task

Trace the `TypeMeta` type from its **usage site** in the main Kubernetes repo through any **intermediate re-exports** to its **original definition**. Document each step in the chain.

Start from this usage site:
- **File**: `/workspace/kubernetes/staging/src/k8s.io/api/core/v1/types.go`
- **Usage**: The `Pod` struct embeds `metav1.TypeMeta`

For each link in the chain, record:
- `step`: sequence number (1 for usage, 2 for re-export, 3 for definition)
- `repo`: which repository (e.g., `kubernetes/kubernetes`, `kubernetes/api`, `kubernetes/apimachinery`)
- `file`: path relative to the repository root
- `line`: line number where the symbol appears (approximate is acceptable)
- `context`: what happens at this step (e.g., "Pod embeds TypeMeta", "api/core/v1 re-exports metav1", "TypeMeta defined here")

## Output

Write your results to `/workspace/chain.json`:

```json
[
  {
    "step": 1,
    "repo": "kubernetes/kubernetes",
    "file": "staging/src/k8s.io/api/core/v1/types.go",
    "line": 4500,
    "context": "Pod struct embeds metav1.TypeMeta"
  },
  {
    "step": 2,
    "repo": "kubernetes/api",
    "file": "core/v1/types.go",
    "line": 4500,
    "context": "api/core/v1 imports metav1 from apimachinery"
  },
  {
    "step": 3,
    "repo": "kubernetes/apimachinery",
    "file": "pkg/apis/meta/v1/types.go",
    "line": 50,
    "context": "TypeMeta struct definition with APIVersion and Kind fields"
  }
]
```

## Notes

- The kubernetes/kubernetes repository contains a staging directory (`staging/src/k8s.io/`) with code that is synced to separate repositories (kubernetes/api, kubernetes/apimachinery). For this task, treat them as separate codebases.
- Use cross-file search or definition lookup to trace imports and type references.
- You may encounter intermediate re-exports—document all steps.
- Line numbers are approximate; +/- 50 lines is acceptable if the symbol is in that region.
