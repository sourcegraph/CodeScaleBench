# big-code-cross-k8s-arch-001: Kubernetes CRD Lifecycle (Cross-Repo)

## Task

Trace how a Custom Resource Definition (CRD) flows through the Kubernetes ecosystem: from CRD type definitions and validation, through etcd storage and the dynamic HTTP handler, to the generated client, informers, listers, and the dynamic client. Map the complete lifecycle across four logical sub-projects within the Kubernetes monorepo.

## Context

- **Repository**: kubernetes/kubernetes (Go, ~2.5M LOC)
- **Category**: Architectural Understanding (cross-repo)
- **Difficulty**: hard
- **Subsystem Focus**: staging/src/k8s.io/apiextensions-apiserver/, staging/src/k8s.io/client-go/, staging/src/k8s.io/apimachinery/, staging/src/k8s.io/api/

## Architecture Overview

Kubernetes uses a staging directory structure where four logically separate projects coexist in one monorepo:

1. **apiextensions-apiserver** — CRD type definitions, validation, etcd storage, dynamic HTTP handler
2. **client-go** — Generated typed clients, informers, listers, and the dynamic client
3. **apimachinery** — Runtime scheme, GVK/GVR types, ObjectMeta, Unstructured representation
4. **api** — Internal hub types and group registration

## Requirements

1. Trace the CRD type definition layer: internal hub types, external v1 types, and Scheme registration
2. Map the server-side lifecycle: validation, etcd storage, and the dynamic customresource_handler
3. Trace the client-side access layer: typed clientset, SharedIndexInformer, Lister, and DynamicClient
4. Identify the foundational types in apimachinery that everything depends on: Scheme, GVK/GVR, TypeMeta/ObjectMeta, Unstructured

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```markdown
## Files Examined
- path/to/file1.ext — role in architecture
- path/to/file2.ext — role in architecture
...

## Dependency Chain
1. Foundation: apimachinery types (Scheme, GVK, ObjectMeta, Unstructured)
2. Type definitions: apiextensions types (internal hub + external v1 + registration)
3. Server-side: validation -> etcd storage -> HTTP handler
4. Client-side: typed client -> informer -> lister -> dynamic client
...

## Analysis
[Detailed architectural analysis including:
- Cross-project dependency flow
- How CRD types bridge the four sub-projects
- The role of Scheme and GVK in type registration
- How Unstructured enables dynamic custom resource access
- The checkpoint between server-side storage and client-side informer caching]

## Summary
[Concise 2-3 sentence summary of the CRD lifecycle across the K8s ecosystem]
```

## Evaluation Criteria

- File recall: Did you find files across ALL four sub-projects?
- Dependency accuracy: Did you trace the correct cross-project dependency chain?
- Architectural coherence: Did you identify how the sub-projects integrate?
