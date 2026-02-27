# CRD Lifecycle Across the Kubernetes Ecosystem

## Files Examined

### apimachinery (Foundation Layer)
- `staging/src/k8s.io/apimachinery/pkg/runtime/scheme.go` — Scheme type: registry mapping Go types to GVK, manages type registration
- `staging/src/k8s.io/apimachinery/pkg/runtime/schema/group_version.go` — GroupVersionKind and GroupVersionResource types
- `staging/src/k8s.io/apimachinery/pkg/runtime/schema/interfaces.go` — ObjectKind interface for serialization
- `staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/unstructured/unstructured.go` — Unstructured implementation for dynamic access
- `staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/unstructured/helpers.go` — Unstructured codec and conversion helpers
- `staging/src/k8s.io/apimachinery/pkg/runtime/converter.go` — Converter between typed and unstructured representations
- `staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/types.go` — ObjectMeta and TypeMeta definitions

### apiextensions-apiserver (Server-Side Type Definition & Validation)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/types.go` — Internal hub type definitions (CRD, CustomResourceDefinition, CustomResourceValidation)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go` — External v1 type definitions (stable API)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1beta1/types.go` — v1beta1 types (deprecated)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/register.go` — Scheme registration for CRD types
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/validation/validation.go` — CRD validation logic
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/validation/ratcheting.go` — Schema validation with ratcheting
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/validation/cel_validation.go` — CEL-based validation rules

### apiextensions-apiserver (Server-Side Storage & HTTP Handler)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/customresource_handler.go` — Dynamic HTTP handler for CRD requests (crdHandler)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/etcd.go` — etcd storage for custom resources (REST type)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresourcedefinition/etcd.go` — etcd storage for CRD definitions (REST type)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/strategy.go` — Custom resource validation and storage strategy

### client-go (Client-Side Access Layer)
- `staging/src/k8s.io/client-go/dynamic/interface.go` — DynamicClient interface and ResourceInterface
- `staging/src/k8s.io/client-go/dynamic/simple.go` — DynamicClient implementation
- `staging/src/k8s.io/client-go/dynamic/dynamicinformer/` — DynamicInformer for watching CRDs
- `staging/src/k8s.io/client-go/dynamic/dynamiclister/` — DynamicLister for querying CRDs
- `staging/src/k8s.io/client-go/tools/cache/shared_informer.go` — SharedIndexInformer: cache + watch coordination
- `staging/src/k8s.io/client-go/informers/factory.go` — SharedInformerFactory pattern
- `staging/src/k8s.io/apiextensions-apiserver/pkg/client/clientset/clientset/typed/apiextensions/v1/customresourcedefinition.go` — Typed CRD client
- `staging/src/k8s.io/apiextensions-apiserver/pkg/client/informers/externalversions/apiextensions/v1/customresourcedefinition.go` — CRD informer
- `staging/src/k8s.io/apiextensions-apiserver/pkg/client/listers/apiextensions/v1/customresourcedefinition.go` — CRD lister

---

## Dependency Chain

### Layer 1: Foundation (apimachinery)
The foundation is built on **runtime reflection and type registration**:

1. **Scheme** (`runtime.Scheme`): The central registry that maps between:
   - Go struct types (via `reflect.Type`)
   - GroupVersionKind identifiers (semantic meaning: which API group/version/kind)
   - Conversion and serialization functions

2. **GVK/GVR Types** (schema.GroupVersionKind, schema.GroupVersionResource):
   - `GroupVersionKind`: Identifies a resource type uniquely across all API groups
   - `GroupVersionResource` (GVR): Runtime lookup key for resources
   - Both implement the `ObjectKind` interface for serialization

3. **ObjectMeta** (`metav1.ObjectMeta`): Standardized metadata on all objects:
   - `Name`, `Namespace`, `UID`, `ResourceVersion` (for optimistic locking)
   - Labels, Annotations, Owner References (for controllers)
   - Timestamps: `CreationTimestamp`, `DeletionTimestamp`

4. **Unstructured** (`unstructured.Unstructured`): Generic representation:
   - Stores resources as `map[string]interface{}`
   - Implements `runtime.Object` interface
   - Enables dynamic access to any CRD without compile-time type definitions
   - `UnstructuredContent()` returns raw map; `SetUnstructuredContent()` mutates
   - Works with `UnstructuredJSONScheme` for codec-based conversions

5. **Converter** (`runtime.UnstructuredConverter`):
   - Bidirectional conversion: typed Go struct ⟷ `map[string]interface{}`
   - Used by apiserver to translate between stored CRD instances and external representations

---

### Layer 2: Type Definitions (apiextensions-apiserver)

CRD types are defined in two forms, bridging internal and external representations:

1. **Internal Hub Types** (`apiextensions.CustomResourceDefinition`):
   - Internal representation stored in Scheme's `gvkToType` map
   - Includes `Spec` (CRD definition), `Status` (conditions, accepted names)
   - Used internally for all conversions (hub-spoke model)

2. **External v1 Types** (`apiextensionsv1.CustomResourceDefinition`):
   - Stable, public API (apiextensions.k8s.io/v1)
   - Converted from internal type via `Scheme.Convert()`
   - Serialized to etcd as JSON

3. **Scheme Registration**:
   - `register.go` adds types to the Scheme:
     - Maps `apiextensionsv1.CustomResourceDefinition` → GVK `apiextensions.k8s.io/v1/CustomResourceDefinition`
     - Registers conversion functions between versions
   - When a CRD is created, the apiserver uses Scheme to:
     - Deserialize from JSON → `Unstructured` → internal hub type
     - Serialize from internal hub → external v1 → JSON for etcd

---

### Layer 3: Server-Side Lifecycle

#### 3a. Type Registration & Validation
When a CRD is created/updated:

1. **crdHandler** (`customresource_handler.go`):
   - Serves as an HTTP filter for `/apis` endpoints
   - Maintains a `crdStorageLock` and atomic `customStorage` map
   - Dynamically creates new HTTP handlers when a CRD is registered

2. **Validation** (`apiserver/validation/`):
   - `ValidationOptions`: Controls whether to ratchet validation errors (for upgrades)
   - `RatchetingSchemaValidator`: Validates new CRD instances against OpenAPI v3 schema
   - `CELSchemaContext`: Manages CEL (Common Expression Language) validation rules (`x-kubernetes-validations`)
   - Validation runs on both create and update operations

#### 3b. Storage in etcd

1. **CustomResource REST Handler** (`registry/customresource/etcd.go`):
   - `REST` struct implements generic registry storage interface
   - `CustomResourceStorage` wraps REST + Status + Scale subresources
   - Uses `genericregistry.Store` for CRUD operations against etcd
   - Works with **etcd key structure**: prefix like `apiextensions.k8s.io/customresources/{name}`

2. **Unstructured Codec** (`unstructured.UnstructuredJSONScheme`):
   - Custom codec that serializes/deserializes CRD instances
   - Stores everything as JSON in etcd without type information
   - On retrieval: JSON → `Unstructured` → concrete type (if registered) or stays `Unstructured`

3. **Storage Strategy** (`registry/customresource/strategy.go`):
   - Implements validation, defaulting, and field pruning during storage operations
   - Handles finalizers for graceful deletion

#### 3c. Dynamic HTTP Handler

1. **Request Flow in crdHandler**:
   - Incoming HTTP request (e.g., `POST /apis/mygroup.io/v1/myresources`)
   - crdHandler looks up CRD from lister
   - If CRD found: routes to `crdStorageMap[GVK]` (dynamically registered handler)
   - If not found: delegates to next handler

2. **Handler Creation**:
   - When CRD is established, a new `REST` handler is created and registered
   - Handler is tied to the CRD's schema for validation, defaulting, pruning
   - Uses the CRD's OpenAPI v3 schema from `spec.validation.openAPIV3Schema`

---

### Layer 4: Client-Side Access

#### 4a. Unstructured/Dynamic Client

The **DynamicClient** (`client-go/dynamic/simple.go`):
- Implements `Interface`: method `Resource(GVR) NamespaceableResourceInterface`
- Works with `*unstructured.Unstructured` directly
- **Does not require pre-generated client code**; can access any CRD at runtime

Operations (from `ResourceInterface`):
```
Create(ctx, obj *Unstructured, ...) (*Unstructured, error)
Get(ctx, name, ...) (*Unstructured, error)
List(ctx, ...) (*UnstructuredList, error)
Update(ctx, obj, ...) (*Unstructured, error)
Delete(ctx, name, ...) error
Watch(ctx, ...) (watch.Interface, error)
Patch(ctx, name, patchType, ...) (*Unstructured, error)
```

Request flow:
1. Client calls `dynamicClient.Resource(gvr).Namespace(ns).Get(name)`
2. DynamicClient constructs REST path: `/apis/{group}/{version}/namespaces/{ns}/{resource}/{name}`
3. Sends HTTP GET to APIServer
4. APIServer's crdHandler routes to registered handler
5. Handler retrieves from etcd (as `Unstructured`)
6. Response returned as `*unstructured.Unstructured`

#### 4b. SharedIndexInformer: Local Cache + Watch Coordination

`tools/cache/shared_informer.go` implements an **eventually consistent local cache**:

1. **Initialization**:
   ```go
   informer := cache.NewSharedIndexInformer(
       lw ListWatch,                    // source of truth
       &customResource{},               // example object
       resyncPeriod,
       indexers,
   )
   ```

2. **Internal Components**:
   - **Store**: Indexer cache holding objects by key (namespace/name)
   - **Reflector**: Watches the API server, feeds updates into DeltaFIFO
   - **DeltaFIFO**: Work queue of object deltas (Added, Updated, Deleted, Sync)
   - **Processor**: Event dispatching (calls registered EventHandlers)

3. **Watch Mechanism**:
   - Reflector calls API server's `Watch()` endpoint
   - Receives watch events as they occur
   - Updates local cache immediately
   - Broadcasts to registered handlers via processor

4. **Eventual Consistency**:
   - Informer may miss events if APIServer watch times out
   - Periodic resync (default 15 mins) refetches entire list to ensure consistency
   - Sync events notify handlers of current state

#### 4c. Listers: Read-Only View of Cache

`listers/` (and `dynamiclister/`):
- **CustomResourceDefinitionLister**: Simple read-only interface over cache
  ```go
  List(selector labels.Selector) ([]*CRD, error)
  Get(name string) (*CRD, error)
  ```
- Backed by an `Indexer` (from informer cache)
- No network calls: purely local cache lookups
- Used by controllers to retrieve CRDs without querying APIServer every time

#### 4d. SharedInformerFactory Pattern

`informers/factory.go`:
- Creates and manages multiple informers for different resources
- Single Reflector per resource type (shared watch connection)
- Reuses Store/cache across multiple informers for the same GVK
- Deduplicates watch subscriptions (only one watch to APIServer per GVK)

---

## Analysis: Cross-Project Integration

### How CRD Types Bridge Four Sub-Projects

1. **apimachinery provides the foundation**:
   - `Scheme`: Type registry used by all projects
   - `Unstructured`: Enables dynamic access without pre-generated types
   - `ObjectMeta`: Standard metadata on all objects
   - `GVK/GVR`: Identifiers recognized by all projects

2. **apiextensions-apiserver builds on apimachinery**:
   - Defines CRD types (internal hub + external v1)
   - Registers them in the Scheme
   - Validates instances against CRD schemas
   - Stores in etcd using Unstructured codec
   - Serves dynamic HTTP handler

3. **client-go consumes apiextensions-apiserver's HTTP layer**:
   - DynamicClient makes requests to `/apis/{group}/{version}/...` endpoints
   - Receives responses as `Unstructured` objects
   - SharedIndexInformer watches for changes
   - Listers cache results locally

4. **api (internal/core types)** provides well-known types:
   - Pod, Service, Deployment, etc.
   - Also registered in the Scheme
   - CRD system allows arbitrary custom resources alongside built-ins

### Critical Checkpoint: Server-Side Storage ↔ Client-Side Informer

The **Unstructured interface** is the checkpoint:

**Server-Side (Storage)**:
```
HTTP Request → crdHandler → REST handler → etcd query
→ UnstructuredJSONScheme.Decode(json) → *Unstructured
```

**Client-Side (Informer)**:
```
Watch() API → events → Reflector → DeltaFIFO
→ Processor calls handlers
→ Lister queries local cache (Indexer)
```

The Unstructured boundary enables:
- Loose coupling: apiextensions-apiserver doesn't need typed client-go code
- Dynamic access: Any CRD can be accessed without code generation
- Protocol compatibility: Server stores as JSON, client reads as map[string]interface{}

### Role of Scheme and Type Registration

The **Scheme** is woven through all layers:

1. **Type Registration**: Each project registers its types
   ```go
   scheme.AddKnownTypes(gv, &CRD{}, &Pod{}, ...)
   scheme.AddUnversionedTypes(gv, &Status{}, ...)
   ```

2. **Serialization**: Scheme determines codecs for each GVK
   - Internal types ↔ external types (conversion)
   - External types ↔ JSON (serialization)

3. **Deserialization**: Scheme reverses the process
   - JSON → TypeMeta extraction → GVK lookup → type instantiation

4. **Client-Go Use**: Typed clients are generated per resource
   - Each generated client uses the Scheme
   - DynamicClient uses Unstructured (agnostic to Scheme)

---

## Summary

The Kubernetes CRD lifecycle is a three-phase architecture across four sub-projects:

1. **Foundation (apimachinery)**: Scheme-based type registry, Unstructured for generic access, ObjectMeta for standard metadata.

2. **Server-Side (apiextensions-apiserver)**: CRD type definitions registered in Scheme, validated against schemas, stored in etcd as Unstructured JSON, served dynamically via HTTP handlers.

3. **Client-Side (client-go)**: DynamicClient for untyped access, SharedIndexInformer for watch-based caching, Listers for read-only cache queries. The Unstructured interface bridges server-side storage (JSON in etcd) and client-side access (map-based dynamic objects), enabling runtime CRD registration without code generation.
