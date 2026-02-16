# big-code-cross-k8s-arch-001: Kubernetes CRD Lifecycle (Cross-Repo)

This task spans four logically separate sub-projects within the Kubernetes monorepo. Use comprehensive cross-project search to trace dependencies.

## Task Type: Architectural Understanding (Cross-Repo)

Your goal is to trace the CRD lifecycle across the Kubernetes ecosystem. Focus on:

1. **Foundation layer (apimachinery)**: Find the runtime Scheme, GVK/GVR types, TypeMeta/ObjectMeta, and Unstructured
2. **Type definitions (apiextensions)**: Map the CRD type hierarchy — internal hub types, external v1 types, Scheme registration
3. **Server-side (apiextensions-apiserver)**: Trace validation, etcd storage, and the dynamic HTTP handler
4. **Client-side (client-go)**: Map the typed clientset, informer, lister, and DynamicClient

## Sub-Projects to Search

All paths are under the `staging/src/k8s.io/` directory:

| Sub-Project | Staging Path | Sourcegraph Repo |
|-------------|-------------|------------------|
| apimachinery | `staging/src/k8s.io/apimachinery/` | `github.com/kubernetes/apimachinery` |
| apiextensions (types) | `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/` | `github.com/kubernetes/kubernetes` |
| apiextensions (server) | `staging/src/k8s.io/apiextensions-apiserver/pkg/` | `github.com/kubernetes/kubernetes` |
| client-go | `staging/src/k8s.io/client-go/` | `github.com/kubernetes/client-go` |

## Key Entry Points

**apimachinery:**
- `pkg/runtime/scheme.go` — Type registry mapping Go types to GVK
- `pkg/runtime/schema/group_version.go` — GroupVersionKind, GroupVersionResource definitions
- `pkg/apis/meta/v1/types.go` — TypeMeta, ObjectMeta, ListMeta
- `pkg/apis/meta/v1/unstructured/unstructured.go` — Generic map-based object representation

**apiextensions-apiserver:**
- `pkg/apis/apiextensions/types.go` — Internal hub CRD types
- `pkg/apis/apiextensions/v1/types.go` — External v1 CRD types
- `pkg/apis/apiextensions/v1/register.go` — v1 Scheme registration
- `pkg/apis/apiextensions/validation/validation.go` — CRD validation
- `pkg/registry/customresourcedefinition/etcd.go` — REST storage
- `pkg/apiserver/customresource_handler.go` — Dynamic HTTP handler

**client-go:**
- `pkg/client/clientset/clientset/typed/apiextensions/v1/customresourcedefinition.go` — Typed client
- `pkg/client/informers/externalversions/apiextensions/v1/customresourcedefinition.go` — Informer
- `pkg/client/listers/apiextensions/v1/customresourcedefinition.go` — Lister
- `dynamic/interface.go` — DynamicClient interface
- `dynamic/simple.go` — DynamicClient implementation

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- staging/src/k8s.io/.../file.go — role in the CRD lifecycle

## Dependency Chain
1. apimachinery foundation types
2. apiextensions type definitions
3. Server-side storage/handler
4. Client-side access layer

## Analysis
[Cross-project architectural analysis]
```

## Search Strategy

- Search `staging/src/k8s.io/apimachinery/` for foundational runtime types (Scheme, GVK)
- Search `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/` for CRD type definitions
- Search `staging/src/k8s.io/apiextensions-apiserver/pkg/registry/` for etcd storage
- Search `staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/` for the dynamic handler
- Search `staging/src/k8s.io/client-go/dynamic/` for the untyped client
- Use `find_references` on `CustomResourceDefinition` to trace cross-project usage
- Use `go_to_definition` on `Scheme`, `Unstructured`, `GroupVersionKind` to find their source
