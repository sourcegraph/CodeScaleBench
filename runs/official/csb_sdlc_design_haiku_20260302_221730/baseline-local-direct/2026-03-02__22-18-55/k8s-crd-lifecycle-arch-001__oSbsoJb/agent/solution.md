# Kubernetes CRD Lifecycle: Cross-Repo Architectural Trace

## Files Examined

### apimachinery (Foundation Layer)
- `staging/src/k8s.io/apimachinery/pkg/runtime/types.go` — TypeMeta, RawExtension, Unknown types (base for all objects)
- `staging/src/k8s.io/apimachinery/pkg/runtime/schema/group_version.go` — GroupVersionKind, GroupVersionResource, GVK/GVR types
- `staging/src/k8s.io/apimachinery/pkg/runtime/scheme.go` — Scheme (type registry, GVK↔Type mappings, versioning)
- `staging/src/k8s.io/apimachinery/pkg/runtime/interfaces.go` — Encoder, Decoder, GroupVersioner interfaces
- `staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/types.go` — TypeMeta, ListMeta, ObjectMeta (core metadata)
- `staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/unstructured/unstructured.go` — Unstructured, UnstructuredList (dynamic object representation)

### apiextensions-apiserver (CRD Type Definitions & Server-Side Processing)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/types.go` — Internal hub types (CustomResourceDefinition, CustomResourceDefinitionSpec)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go` — External v1 types, v1beta1 types (serializable forms)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/register.go` — Scheme registration (GVK→Type mapping for CRD)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/customresource_handler.go` — Dynamic HTTP handler for custom resources (routes, CRUD)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/apiserver.go` — API server initialization, Scheme setup
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/validation/validation.go` — CRD validation rules and constraints
- `staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/etcd.go` — Custom resource storage in etcd
- `staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/strategy.go` — Create/Update/Delete strategy (validation, defaulting, CEL rules)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/crdserverscheme/unstructured.go` — UnstructuredObjectTyper (GVK extraction from unstructured)

### client-go (Client-Side Access Layer)
- `staging/src/k8s.io/client-go/dynamic/simple.go` — DynamicClient (REST client for unstructured resources)
- `staging/src/k8s.io/client-go/dynamic/dynamicinformer/informer.go` — DynamicSharedInformerFactory, DynamicInformer (watches+caches)
- `staging/src/k8s.io/client-go/dynamic/dynamiclister/lister.go` — DynamicLister, DynamicNamespaceLister (cached queries)
- `staging/src/k8s.io/client-go/tools/cache/listers.go` — GenericLister, cache indexing (base lister implementation)

### api (Internal Hub Types)
- `staging/src/k8s.io/api/` — Contains internal versions of all API groups (used for conversion hub, not directly in CRD flow but referenced)

---

## Dependency Chain

### 1. Foundation Layer: apimachinery Types
```
apimachinery/runtime/types.go:TypeMeta, RawExtension
         ↓
apimachinery/runtime/schema/group_version.go:GroupVersionKind (GVK), GroupVersionResource (GVR)
         ↓
apimachinery/runtime/scheme.go:Scheme
  (Maps GVK ↔ Go Type, handles versioning, serialization)
         ↓
apimachinery/apis/meta/v1/types.go:ObjectMeta, ListMeta
         ↓
apimachinery/apis/meta/v1/unstructured/unstructured.go:Unstructured
  (Generic map[string]interface{} representation of any resource)
```

**Key Insight**: The Scheme is the central registry. Every resource type must be registered with:
- A GVK (e.g., `apiextensions.k8s.io/v1/CustomResourceDefinition`)
- Its Go type (e.g., `*apiextensions.CustomResourceDefinition`)
- Conversion functions between versions

---

### 2. Type Definitions: apiextensions-apiserver CRD Types
```
apiextensions/types.go (internal hub)
  - CustomResourceDefinition (internal version, no serialization suffix)
  - CustomResourceDefinitionSpec
  - CustomResourceValidation, CustomResourceNames, etc.
         ↓
apiextensions/v1/types.go (external versioned)
  - CustomResourceDefinition (v1, has JSON tags, protobuf tags)
  - Re-exports CustomResourceValidation, etc.
         ↓
apiextensions/register.go
  - SchemeGroupVersion = "apiextensions.k8s.io/__internal"
  - addKnownTypes() registers CustomResourceDefinition to Scheme
  - Enables Scheme.New(GVK) → *CustomResourceDefinition{}
```

**Key Insight**: CRD types follow Kubernetes' internal/external versioning pattern:
- Internal types (no version suffix) are the conversion hub
- External types (v1, v1beta1) are for wire format
- The Scheme bridges all versions through conversion functions

---

### 3. Server-Side Lifecycle: Validation → Storage → HTTP Handler

#### A. Validation Phase
```
apiextensions/validation/validation.go:ValidateCustomResourceDefinition()
  ├─ Static validation of CRD spec (names, group, scope)
  ├─ CEL rule validation (x-kubernetes-validations)
  ├─ OpenAPI schema validation (via structuralschema)
  └─ Generates validation.SchemaValidator + cel.Validator

                    ↓

apiserver/customresource_handler.go:CustomResourceHandler
  ├─ Accepts HTTP requests for custom resources
  ├─ Uses validator to validate incoming resources
  └─ Calls structuraldefaulting + structuralpruning
```

#### B. Storage Phase
```
apiserver/customresource_handler.go
  → registry/customresource/etcd.go:NewStorage()
      ├─ Creates genericregistry.Store{
      │   NewFunc: → &unstructured.Unstructured{}
      │   (Resources stored as unstructured)
      ├─ Uses customResourceStrategy for CRUD operations
      └─ Registers in etcd under key:
           /registry/customresources/<group>/<plural>/<namespace>/<name>

            ↓

registry/customresource/strategy.go:customResourceStrategy
  ├─ Implements Create(), Update(), Delete()
  ├─ Calls validator.ValidateObject() on mutations
  ├─ Applies CEL validation rules (structuraldefaulting, pruning)
  └─ Manages managed fields (structured merge diff)
```

**Key Insight**: Custom resources are stored as `unstructured.Unstructured` in etcd, not as typed Go structs. The Scheme is NOT used for CRD storage because CRDs don't have registered Go types in the apiserver.

#### C. HTTP Handler Phase
```
customresource_handler.go:(*CustomResourceHandler).ServeHTTP()
  ├─ Routes GET /apis/<group>/<version>/<resource>
  ├─ Routes POST, PUT, DELETE, PATCH for CRUD
  └─ Uses REST interface pattern (handlers.Handlers)
       → rest.GetterUpdater
           → genericregistry.Store
               → etcd backend

Note: The handler is DYNAMIC—it's created per-CRD when a CRD is created
      by introspecting the CRD spec (group, version, names, scope).
```

---

### 4. Client-Side Lifecycle: Typed Client → Informer → Lister → Dynamic Client

#### A. DynamicClient (Low-Level REST Interface)
```
client-go/dynamic/simple.go:DynamicClient
  ├─ Wraps rest.Interface (raw HTTP client)
  ├─ Resource() → dynamicResourceClient
  ├─ Implements Interface:
  │   ├─ Get(ctx, name, opts) (*unstructured.Unstructured, error)
  │   ├─ List(ctx, opts) (*unstructured.UnstructuredList, error)
  │   ├─ Create(ctx, obj, opts) (*unstructured.Unstructured, error)
  │   ├─ Update(ctx, obj, opts) (*unstructured.Unstructured, error)
  │   └─ Watch(ctx, opts) (watch.Interface, error)
  └─ Serializes to JSON, deserializes to unstructured.Unstructured

Uses GVR (GroupVersionResource) to construct REST paths:
  /apis/<group>/<version>/<plural>
  /apis/<group>/<version>/namespaces/<ns>/<plural>/<name>
```

**Key Insight**: The DynamicClient bridges between the Scheme-based server and schemaless clients. It uses GVR, not GVK (resources vs. kinds).

#### B. DynamicSharedInformerFactory (Watch + Cache)
```
client-go/dynamic/dynamicinformer/informer.go
  ├─ NewDynamicSharedInformerFactory(dynamicClient, resyncPeriod)
  ├─ Creates shared informers for resources
  ├─ Maintains map[GVR]GenericInformer
  └─ Start() → launches watch goroutines

                    ↓

dynamicinformer.NewFilteredDynamicInformer()
  ├─ Creates cache.SharedIndexInformer backed by:
  │   ├─ Reflector (watches API server)
  │   ├─ Store (in-memory cache)
  │   └─ Indexers (namespace index, custom indexes)
  ├─ Watches: dynamicClient.Watch(GVR)
  └─ Caches: unstructured.Unstructured objects
```

**Key Insight**: The informer is GVR-based (not GVK), uses standard cache.Indexer for local caching, and implements the GenericInformer interface.

#### C. DynamicLister (Cached Queries)
```
client-go/dynamic/dynamiclister/lister.go
  ├─ dynamicLister implements Lister interface
  ├─ Wraps cache.Indexer (from informer)
  └─ Methods:
      ├─ List(selector) → []*unstructured.Unstructured
      ├─ Get(name) → *unstructured.Unstructured
      └─ Namespace(ns) → NamespaceLister
                          ├─ List(selector)
                          └─ Get(name)

Uses cache.NamespaceIndex to efficiently query by namespace.
```

**Key Insight**: The lister is a thin wrapper around the cache indexer, enabling efficient queries without hitting the API server.

---

## Analysis

### Cross-Project Dependency Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ apimachinery (Foundation)                                       │
│  ├─ Scheme: GVK ↔ Go Type registry                              │
│  ├─ GVK/GVR: Type identifiers                                   │
│  ├─ Unstructured: Generic map representation                    │
│  └─ ObjectMeta: Common resource metadata                        │
└─────────────────────┬───────────────────────────────────────────┘
                      │ imports (runtime types, Scheme)
┌─────────────────────▼───────────────────────────────────────────┐
│ apiextensions-apiserver (Server)                                │
│  ├─ Types: Registers CRD types to Scheme                        │
│  ├─ Handler: Dynamic HTTP router for custom resources           │
│  ├─ Validation: Validates incoming CRs against CRD schema       │
│  ├─ Storage: Stores CRs as unstructured.Unstructured in etcd    │
│  └─ Strategy: Create/Update/Delete logic                        │
│                                                                  │
│ Checkpoint: CRD defines schema; CR stored as unstructured JSON  │
└─────────────────────┬───────────────────────────────────────────┘
                      │ defines + stores
                      ▼
            ┌──────────────────┐
            │ etcd Database    │
            │ /registry/...    │
            └────────┬─────────┘
                      │ serves
┌─────────────────────▼───────────────────────────────────────────┐
│ client-go (Client)                                              │
│  ├─ DynamicClient: REST interface for GVR → Unstructured        │
│  ├─ Informer: Watches + in-memory cache of Unstructured         │
│  ├─ Lister: Queries cache without API calls                     │
│  └─ All use GVR, not GVK (resources, not kinds)                 │
│                                                                  │
│ Note: No Scheme needed for reading (schemaless unstructured)    │
└─────────────────────────────────────────────────────────────────┘
```

### Role of Each Sub-Project

#### 1. **apimachinery** — Shared Runtime Foundations
- **Scheme**: Central type registry used by apiserver for ALL types (built-ins + CRDs)
  - Enables `Scheme.New(GVK)` → instantiate any type
  - Enables `Scheme.ObjectKinds(obj)` → extract GVK from object
  - Maps conversions between versions
- **GVK/GVR Types**: Identify resources across the system
- **Unstructured**: Enables server to store arbitrary resource shapes without Go type definitions
- **ObjectMeta**: Every object has metadata (name, namespace, labels, annotations, resourceVersion)

#### 2. **apiextensions-apiserver** — CRD Server Implementation
- **Registers CRD types to Scheme**: Makes CRD itself discoverable (e.g., `apiextensions.k8s.io/v1/CustomResourceDefinition`)
- **Defines custom resource schema**: Via OpenAPI v3 schema in CRD spec
- **Validates on write**: Applies CRD schema rules, CEL validation, field selectors
- **Stores as unstructured**: CRs stored as JSON in etcd, NOT as typed Go structs (because Go types don't exist for user-defined CRDs)
- **Serves HTTP dynamically**: Each CRD generates a new HTTP handler at `/apis/<group>/<version>/<plural>`

#### 3. **client-go** — Client-Side Access
- **DynamicClient**: REST client that works with ANY resource type (knows GVR, not GVK)
  - Serializes Go objects to JSON, deserializes to unstructured.Unstructured
  - No dependency on Scheme for reading (schemaless!)
- **DynamicInformer**: Caches resources in memory, enables efficient bulk reads
  - Uses standard Kubernetes watch pattern (Reflector → Store → Indexer)
- **DynamicLister**: Queries cache with label/field selectors
  - No API server calls, fast local access

#### 4. **api** — Internal Hub Types
- Contains internal (unversioned) types for all Kubernetes API groups
- Used as conversion target between external versions (e.g., v1 ↔ v1beta1)
- **Not directly used for CRDs** (since CRs don't have internal types in the Scheme), but pattern is similar

---

### How CRD Types Bridge the Four Sub-Projects

1. **CRD Object Lifecycle** (apiextensions-apiserver):
   ```
   User applies CustomResourceDefinition YAML
         ↓
   apiextensions/v1 types deserialize JSON → internal types
         ↓
   Scheme.AddKnownTypes() already registered these types
         ↓
   Validation rules applied (field names, scope, conversion strategy)
         ↓
   Stored in etcd as CustomResourceDefinition resource
   ```

2. **Custom Resource Lifecycle** (server → storage → client):
   ```
   User applies CustomResource instance (arbitrary YAML matching schema)
         ↓
   Handler validates against CRD schema (validation rules + CEL)
         ↓
   Stored as unstructured.Unstructured in etcd
         ↓
   DynamicClient.Watch() retrieves via GVR
         ↓
   Informer caches as unstructured.Unstructured
         ↓
   Lister queries cache (no Scheme needed—already unstructured!)
   ```

---

### The Role of Scheme and GVK in Type Registration

**Scheme in apiextensions-apiserver** (at line 70 in apiserver.go):
```go
var (
    Scheme = runtime.NewScheme()
    ...
)

func init() {
    install.Install(Scheme)  // Registers CRD types, etc.
    ...
}
```

- **For CRD objects themselves**: GVK = `apiextensions.k8s.io/v1/CustomResourceDefinition`
  - Registered in Scheme so apiserver can instantiate and serialize CRDs
- **For custom resources** (user-defined CRs): NO GVK registration
  - Because Go types don't exist for arbitrary user schemas
  - Instead, stored/retrieved as `unstructured.Unstructured`
  - Validation rules defined in CRD schema (OpenAPI v3)

**Scheme in client-go** (for reading CRs):
- DynamicClient doesn't require Scheme for unstructured resources
- Unstructured objects are self-describing (kind + apiVersion in object)
- Informer/Lister work purely on the cache (no type registry needed)

---

### How Unstructured Enables Dynamic Custom Resource Access

**Storage Layer** (apiextensions-apiserver/registry/customresource/etcd.go):
```go
store := &genericregistry.Store{
    NewFunc: func() runtime.Object {
        ret := &unstructured.Unstructured{}
        ret.SetGroupVersionKind(kind)
        return ret
    },
    ...
}
```
- All custom resources created via `NewFunc()` → `unstructured.Unstructured`
- No Go struct needed; validation rules come from CRD schema

**Client Layer** (client-go/dynamic/simple.go):
```go
type DynamicClient struct {
    client rest.Interface
}

func (dc *DynamicClient) Resource(gvr).Get(...) -> unstructured.Unstructured
```
- Client sends GET request to `/apis/<group>/<version>/<resource>/<name>`
- Server returns JSON; client unmarshals to `unstructured.Unstructured`
- No Scheme needed—JSON structure matches CRD schema

**Caching Layer** (client-go/dynamic/dynamicinformer/informer.go):
```go
NewFilteredDynamicInformer(client, gvr, ...)
  ├─ Reflector watches: dynamicClient.Watch(gvr)
  ├─ Cache stores: []*unstructured.Unstructured
  └─ Lister queries: cache.Indexer.List() → []*unstructured.Unstructured
```
- Entire workflow is schemaless; validation is server-side only

---

### The Checkpoint: From Server Storage to Client Caching

```
┌─────────────────────────────────────────────┐
│ Server-Side (apiextensions-apiserver)       │
│                                             │
│ Validation: Check against CRD schema        │
│ Storage: unstructured.Unstructured → etcd   │
│ HTTP: Serve /apis/<group>/<version>/<res>  │
└─────────┬───────────────────────────────────┘
          │ JSON over HTTP
          ▼
    ┌─────────────────┐
    │ Network Boundary│  ← Checkpoint: Server sends JSON
    └─────────────────┘
          │ JSON over HTTP
          ▼
┌──────────────────────────────────────────────────┐
│ Client-Side (client-go)                          │
│                                                  │
│ DynamicClient: Parse JSON → unstructured         │
│ Informer: Cache unstructured objects            │
│ Lister: Query cache (no validation needed)       │
│                                                  │
│ Note: Client never sees Go types, never uses     │
│       Scheme for reading (only for built-ins)    │
└──────────────────────────────────────────────────┘
```

The checkpoint is **at the HTTP JSON boundary**. Validation happens server-side; clients receive pre-validated JSON matching the CRD schema.

---

## Summary

The Kubernetes CRD lifecycle spans four tightly integrated sub-projects:

1. **apimachinery** provides foundational runtime types (Scheme, GVK, Unstructured, ObjectMeta) that enable any shape of resource to be stored and transmitted without pre-defined Go structs.

2. **apiextensions-apiserver** implements the server-side CRD layer: type definitions, dynamic validation against CRD schemas, and HTTP handlers for custom resources. CRs are stored as JSON-serialized `Unstructured` objects in etcd, with validation rules (OpenAPI v3 + CEL) applied at write time.

3. **client-go** provides client-side access through the DynamicClient (schemaless REST interface), DynamicInformer (watch + cache), and DynamicLister (efficient queries). These work entirely with `Unstructured` objects and GVR identifiers, requiring no Scheme or type registration.

4. **api** (internal types) provides the conversion hub pattern for built-in resources, though not directly used in CRD flows since user-defined CRs don't have registered Go types.

The key architectural insight: **CRDs decouple storage from typing**—the server stores arbitrary JSON shapes validated against CRD schemas, while clients read these unstructured objects without knowledge of the schema, enabling full extensibility without modifying core Kubernetes code.
