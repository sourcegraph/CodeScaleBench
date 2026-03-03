# Kubernetes CRD Lifecycle: Cross-Repository Architectural Analysis

## Files Examined

### Foundation Layer (apimachinery)
- `staging/src/k8s.io/apimachinery/pkg/runtime/scheme.go` — Central Scheme type that maps GVK↔Go types and manages version conversions
- `staging/src/k8s.io/apimachinery/pkg/runtime/schema/group_version.go` — GroupVersionKind, GroupVersionResource, and GroupKind definitions
- `staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/types.go` — TypeMeta, ListMeta definitions (required metadata for all API objects)
- `staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/unstructured/unstructured.go` — Unstructured type enabling dynamic object representation without compiled Go structs
- `staging/src/k8s.io/apimachinery/pkg/runtime/interfaces.go` — Core runtime interfaces (Object, Encoder, GroupVersioner)

### Type Definition Layer (apiextensions-apiserver)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/types.go` — Internal hub types for CustomResourceDefinition
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go` — External v1 CustomResourceDefinitionSpec with OpenAPI schema, conversion, and subresources
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1beta1/types.go` — Legacy v1beta1 types (deprecated)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/register.go` — Scheme registration for internal hub types
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/register.go` — Scheme registration for v1 types with defaulting functions
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/install/install.go` — Install function that registers all versions and sets version priorities

### Server-Side Lifecycle (apiextensions-apiserver)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/customresource_handler.go` — HTTP handler (crdHandler) for `/apis` endpoint, routes custom resource requests
- `staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/etcd.go` — ETCD storage backend for custom resource instances
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/validation/validation.go` — OpenAPI schema validation for custom resources
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/schema/` — Structural schema handling (defaulting, pruning, validation)

### Client-Side Access Layer (client-go)
- `staging/src/k8s.io/client-go/dynamic/interface.go` — DynamicClient Interface and ResourceInterface for untyped access to Unstructured objects
- `staging/src/k8s.io/client-go/dynamic/simple.go` — DynamicClient implementation using REST client with JSON serialization
- `staging/src/k8s.io/client-go/tools/cache/shared_informer.go` — SharedIndexInformer interface and sharedIndexInformer implementation for client-side caching and event watching
- `staging/src/k8s.io/client-go/dynamic/dynamicinformer/informer.go` — DynamicSharedInformerFactory for creating informers for arbitrary CRD types
- `staging/src/k8s.io/client-go/dynamic/dynamiclister/lister.go` — DynamicLister for querying cached Unstructured objects with namespace support

---

## Dependency Chain

### 1. Foundation: apimachinery Runtime & Schema Types

**Layer:** Base types and mechanisms

The entire CRD lifecycle depends on three foundational concepts from apimachinery:

1. **Scheme** (`scheme.go:46-85`)
   - Maps `GroupVersionKind (GVK)` ↔ Go struct types
   - Maintains bidirectional mappings: `gvkToType` and `typeToGVK`
   - Stores conversion functions between versions
   - **Critical role:** All type registration flows through the Scheme; it is the authoritative registry for "what is what" in Kubernetes

2. **GVK/GVR Types** (`schema/group_version.go`)
   - `GroupVersionKind`: Uniquely identifies a type (e.g., `apiextensions.k8s.io/v1/CustomResourceDefinition`)
   - `GroupVersionResource`: Uniquely identifies a resource kind (e.g., `apiextensions.k8s.io/v1, resource=customresourcedefinitions`)
   - **Critical role:** These types are the addressing keys for all runtime operations, HTTP routing, and client lookups

3. **TypeMeta & ObjectMeta** (`meta/v1/types.go:42-56`)
   - `TypeMeta`: Holds `Kind` and `APIVersion` as strings
   - Embedded in all Kubernetes API objects
   - **Critical role:** Every object serialized to JSON includes this metadata for identification

4. **Unstructured** (`unstructured/unstructured.go:31-46`)
   - `map[string]interface{}` wrapper enabling dynamic field access without compiled Go structs
   - Implements `runtime.Object` interface (has GetObjectKind())
   - Implements `metav1.Object` and `metav1.ListInterface`
   - **Critical role:** The bridge between server-side storage (any JSON) and client-side code (no generated classes needed)

---

### 2. Type Definitions: apiextensions CRD Types & Registration

**Layer:** Type schema layer

CRD types exist in a three-level hierarchy:

1. **Internal Hub Types** (`apiextensions/types.go:379-389`)
   ```go
   type CustomResourceDefinition struct {
       metav1.TypeMeta
       metav1.ObjectMeta
       Spec   CustomResourceDefinitionSpec
       Status CustomResourceDefinitionStatus
   }
   ```
   - Registered in internal scheme (`apiextensions.k8s.io/__internal`)
   - Server-side canonical representation
   - Not serialized to wire format
   - **Role:** Central hub for all version conversions

2. **External v1 Types** (`apiextensions/v1/types.go:386-391`)
   ```go
   type CustomResourceDefinition struct {
       metav1.TypeMeta `json:",inline"`
       metav1.ObjectMeta
       Spec   CustomResourceDefinitionSpec
       Status CustomResourceDefinitionStatus
   }
   ```
   - Registered in v1 scheme (`apiextensions.k8s.io/v1`)
   - Serialized to HTTP responses; clients receive this format
   - All field definitions in spec (group, names, versions, validation schema)

3. **Legacy v1beta1 Types** (`apiextensions/v1beta1/types.go:434-436`)
   - Deprecated but still supported
   - Converted to/from v1 via Scheme's conversion functions

**Registration Process:**

- **Internal Hub Registration** (`apiextensions/register.go:40-50`):
  ```go
  var SchemeGroupVersion = schema.GroupVersion{Group: GroupName, Version: runtime.APIVersionInternal}
  func addKnownTypes(scheme *runtime.Scheme) error {
      scheme.AddKnownTypes(SchemeGroupVersion,
          &CustomResourceDefinition{},
          &CustomResourceDefinitionList{},
      )
      return nil
  }
  ```
  - Creates SchemeBuilder that registers internal hub types
  - AddToScheme function makes this registration automatic

- **v1 Registration** (`apiextensions/v1/register.go:47-54`):
  ```go
  var SchemeGroupVersion = schema.GroupVersion{Group: GroupName, Version: "v1"}
  func addKnownTypes(scheme *runtime.Scheme) error {
      scheme.AddKnownTypes(SchemeGroupVersion,
          &CustomResourceDefinition{},
          &CustomResourceDefinitionList{},
          &ConversionReview{},
      )
      metav1.AddToGroupVersion(scheme, SchemeGroupVersion)
      return nil
  }
  ```
  - Registers v1 types with their JSON serialization
  - Includes ConversionReview for webhook conversion

- **Install Function** (`apiextensions/install/install.go:28-33`):
  ```go
  func Install(scheme *runtime.Scheme) {
      utilruntime.Must(apiextensions.AddToScheme(scheme))
      utilruntime.Must(v1beta1.AddToScheme(scheme))
      utilruntime.Must(v1.AddToScheme(scheme))
      utilruntime.Must(scheme.SetVersionPriority(v1.SchemeGroupVersion, v1beta1.SchemeGroupVersion))
  }
  ```
  - Single entry point registering all versions
  - Sets version priority (v1 preferred over v1beta1)
  - Called during apiextensions-apiserver initialization

**Critical Checkpoint:** After registration, the Scheme knows:
- How to map `apiextensions.k8s.io/v1/CustomResourceDefinition` → `*apiextensionsv1.CustomResourceDefinition` Go type
- How to convert between internal hub and v1 representations
- How to serialize/deserialize CRD objects to JSON

---

### 3. Server-Side Lifecycle: HTTP Handler → Validation → Storage

**Layer:** Request handling and persistence

#### 3A. HTTP Request Routing

The `crdHandler` (`customresource_handler.go:84-128`) serves as the central HTTP router for custom resources:

```go
type crdHandler struct {
    customStorage     atomic.Value  // stores crdStorageMap (map[name]*crdInfo)
    crdLister        listers.CustomResourceDefinitionLister
    delegate         http.Handler
    restOptionsGetter generic.RESTOptionsGetter
    admission        admission.Interface
    ...
}
```

**Workflow:**
1. Client sends HTTP request: `POST /apis/example.com/v1/widgets`
2. `crdHandler` intercepts request at filter level (before registered endpoints)
3. Extracts GroupVersionResource from URL path
4. Looks up storage in `customStorage` map by CRD name
5. Routes to appropriate handler (Create, Update, Delete, List, Watch, Get)

#### 3B. Validation

Before storage, requests pass through validation layer (`apiserver/validation/validation.go`):

1. **Structural Schema Validation:**
   - Extracts `spec.versions[].schema.openAPIV3Schema` from CRD
   - Validates incoming custom resource against this schema
   - Checks required fields, type constraints, constraints (minItems, maxLength, etc.)

2. **Server-Side Apply Field Validation** (Managed Fields):
   - Tracks which fields were set by which user/controller
   - Prevents field conflicts during concurrent updates

3. **Defaults & Pruning:**
   - Applies OpenAPI schema defaults to unspecified fields
   - Removes unknown fields if `preserveUnknownFields: false`

#### 3C. ETCD Storage

Custom resources are stored in ETCD via the storage backend (`registry/customresource/etcd.go`):

```go
type CustomResourceStorage interface {
    Backends() []storageInterface // etcd backend(s) per version
    List(ctx context.Context, ...) (*unstructured.UnstructuredList, error)
    Get(ctx context.Context, ...) (*unstructured.Unstructured, error)
    Create(ctx context.Context, ...) (*unstructured.Unstructured, error)
    Update(ctx context.Context, ...) (*unstructured.Unstructured, error)
    Delete(ctx context.Context, ...) error
}
```

**Key Points:**
- Storage operates on `*unstructured.Unstructured` (not typed CRD structs)
- Each CRD version has separate storage path in ETCD
- ETCD path: `/registry/example.com/widgets/<namespace>/<name>`
- ResourceVersion (optimistic locking) managed by ETCD backend

**Critical Checkpoint:** At this point, custom resources are persisted in ETCD as JSON blobs with only metadata structure guaranteed (TypeMeta, ObjectMeta). Field structure varies per CRD.

---

### 4. Client-Side Access: Dynamic Client → Informer → Lister → Cache

**Layer:** Client library access patterns

#### 4A. Dynamic Client Interface

The dynamic client provides untyped access to custom resources (`dynamic/interface.go:29-50`):

```go
type Interface interface {
    Resource(resource schema.GroupVersionResource) NamespaceableResourceInterface
}

type ResourceInterface interface {
    Create(ctx context.Context, obj *unstructured.Unstructured, ...) (*unstructured.Unstructured, error)
    Update(ctx context.Context, obj *unstructured.Unstructured, ...) (*unstructured.Unstructured, error)
    Delete(ctx context.Context, name string, ...) error
    List(ctx context.Context, opts metav1.ListOptions) (*unstructured.UnstructuredList, error)
    Watch(ctx context.Context, opts metav1.ListOptions) (watch.Interface, error)
    ...
}
```

**Workflow:**
1. Client calls `dynamicClient.Resource(schema.GroupVersionResource{...})`
2. Returns ResourceInterface for CRUD operations
3. All operations work with `*unstructured.Unstructured`
4. HTTP calls routed by REST client using GroupVersionResource to build URL path

#### 4B. DynamicClient Implementation

`simple.go` provides the concrete implementation:

```go
type DynamicClient struct {
    client rest.Interface  // underlying REST client
}

type dynamicResourceClient struct {
    client    *DynamicClient
    namespace string
    resource  schema.GroupVersionResource
}
```

**Key Operations:**
- `Create()`: POST to `/apis/<group>/<version>/<resource>`
- `Update()`: PUT to `/apis/<group>/<version>/<resource>/<name>`
- `Delete()`: DELETE to `/apis/<group>/<version>/<resource>/<name>`
- `List()`: GET to `/apis/<group>/<version>/<resource>?...` (returns UnstructuredList)
- `Watch()`: GET with `watch=true` (returns watch.Interface stream)

All serialization uses JSON codec with `unstructured.Unstructured` as the object type.

#### 4C. SharedIndexInformer for Caching

The SharedIndexInformer (`tools/cache/shared_informer.go:231-282`) provides local client-side caching:

```go
type SharedIndexInformer interface {
    AddEventHandler(handler ResourceEventHandler) ResourceEventHandlerRegistration
    AddIndexers(indexers Indexers) error
    GetIndexer() Indexer
    Run(stopCh <-chan struct{})
    WaitForCacheSync(stopCh <-chan struct{}) bool
    LastSyncResourceVersion() string
}

type sharedIndexInformer struct {
    indexer    Indexer                          // local cache (map[string]interface{})
    processor  *sharedProcessor                 // event handler dispatcher
    listerWatcher ListerWatcher                 // source of truth (API server)
    objectType runtime.Object                   // example object type (Unstructured)
}
```

**Workflow:**
1. Informer starts: calls `listerWatcher.List()` to fetch initial objects
2. Stores objects in local `indexer` (an Indexer is an in-memory cache.Index)
3. Starts `listerWatcher.Watch()` for incremental updates
4. On Add/Update/Delete events, updates indexer and dispatches to registered handlers
5. Handlers (like controllers) react to changes via callbacks

#### 4D. DynamicSharedInformerFactory

`dynamicinformer/informer.go` wraps SharedIndexInformer for multiple GVRs:

```go
type dynamicSharedInformerFactory struct {
    client        dynamic.Interface
    informers     map[schema.GroupVersionResource]informers.GenericInformer
    startedInformers map[schema.GroupVersionResource]bool
}

func (f *dynamicSharedInformerFactory) ForResource(gvr schema.GroupVersionResource) informers.GenericInformer {
    // Returns or creates a GenericInformer for this GVR
    informer := NewFilteredDynamicInformer(f.client, gvr, ...)
    return informer
}
```

**Critical Code (lines 150-172):**
```go
informer: cache.NewSharedIndexInformerWithOptions(
    &cache.ListWatch{
        ListFunc: func(options metav1.ListOptions) (runtime.Object, error) {
            return client.Resource(gvr).Namespace(namespace).List(context.TODO(), options)
        },
        WatchFunc: func(options metav1.ListOptions) (watch.Interface, error) {
            return client.Resource(gvr).Namespace(namespace).Watch(context.TODO(), options)
        },
    },
    &unstructured.Unstructured{},
    cache.SharedIndexInformerOptions{...},
)
```

**Key Point:** The ListWatch is built from the DynamicClient, so informers pull data through the same HTTP interface that stores CRDs.

#### 4E. DynamicLister for Querying Cache

`dynamiclister/lister.go` provides query interface to the informer's cache:

```go
type dynamicLister struct {
    indexer cache.Indexer
    gvr     schema.GroupVersionResource
}

func (l *dynamicLister) List(selector labels.Selector) (ret []*unstructured.Unstructured, err error) {
    err = cache.ListAll(l.indexer, selector, func(m interface{}) {
        ret = append(ret, m.(*unstructured.Unstructured))
    })
    return ret, err
}

func (l *dynamicLister) Get(name string) (*unstructured.Unstructured, error) {
    obj, exists, err := l.indexer.GetByKey(name)
    // ...
    return obj.(*unstructured.Unstructured), nil
}
```

**Workflow:**
1. Controller calls `lister.Get("my-widget")` or `lister.List(selector)`
2. Query hits the in-memory indexer (populated by informer from ETCD)
3. Returns `*unstructured.Unstructured` objects
4. No network call; all data is local cache

**Critical Checkpoint:** Informer and Lister provide the bridge from server-side ETCD storage to client-side in-memory cache, enabling high-performance local queries while staying synchronized with the API server.

---

## Analysis

### Cross-Project Dependency Flow

The CRD lifecycle flows through four logically separate sub-projects in a specific order:

```
[apimachinery]  ← Foundation
    ↓
[apiextensions-apiserver]  ← Type Defs & Server-side
    ↓
[ETCD Storage]  ← Persistence
    ↓
[client-go]  ← Client-side Access
```

However, the actual interactions are more nuanced:

1. **At Startup:**
   - apiextensions-apiserver calls `install.Install(scheme)` which registers all CRD types from apiextensions into a Scheme
   - This Scheme lives in the apiserver, not clients
   - The Scheme knows how to convert between internal and v1 CRD types

2. **During CRD Creation:**
   - User submits CustomResourceDefinition object to API server
   - HTTP handler validates it (OpenAPI schema from v1 type)
   - Stored in ETCD as Unstructured JSON

3. **During Custom Resource Create:**
   - Client sends untyped JSON to `/apis/example.com/v1/widgets`
   - Server's crdHandler intercepts, looks up CRD definition
   - Validates incoming JSON against `spec.versions[].schema.openAPIV3Schema` from stored CRD
   - Stores in ETCD as Unstructured JSON

4. **During Client Access:**
   - Client code uses DynamicClient to Create/Update/List
   - DynamicClient doesn't need Scheme registration (works with Unstructured)
   - Client builds SharedIndexInformer using DynamicClient
   - Informer's ListWatch uses DynamicClient to pull from API server
   - Cache stores Unstructured objects locally

### Key Architectural Insights

#### 1. **The Dual-Schema Problem**

Two Schemes operate in parallel:

- **Server-side Scheme (apiextensions-apiserver):**
  - Knows about CRD types (`apiextensions.k8s.io/v1/CustomResourceDefinition`)
  - Knows about built-in types (Pods, Services, etc.)
  - Converts between internal hub and external versions
  - Used during HTTP request handling and storage

- **Client-side Scheme (client-go, optional):**
  - May not include CRD types (they're dynamic)
  - Typed clientsets don't include CRD types
  - Dynamic client doesn't use Scheme at all

**Implication:** CRD definitions are not "baked into" client binaries. They're discovered at runtime from the API server via CRD objects themselves.

#### 2. **Unstructured as the Bridge**

Unstructured is the critical piece enabling dynamic types:

- **Server-side:** Stores custom resources as Unstructured in ETCD (flexible JSON)
- **Network:** HTTP responses include Unstructured wrapped in JSON
- **Client-side:** DynamicClient works with Unstructured directly
- **Informer/Lister:** Cache stores Unstructured objects

This allows:
- Custom resources to have arbitrary schemas
- New CRD versions without recompiling client code
- Dynamic field access via `obj.Object["field"]`

**Limitation:** Type safety is lost; all field access is via string keys and type assertions.

#### 3. **GroupVersionResource as Addressing**

GVR is the universal address for custom resources:

- **HTTP routing:** URL path is `/apis/<group>/<version>/<resource>`
- **Informer creation:** `factory.ForResource(gvr)` creates informer for a specific GVR
- **Client calls:** `dynamicClient.Resource(gvr)` returns handler for that resource
- **Storage:** ETCD path includes GVR components

**Why three parts (Group, Version, Resource)?**
- **Group:** Namespace for API (example.com)
- **Version:** Enables schema evolution (v1, v2alpha1, etc.)
- **Resource:** Plural name for REST operations (widgets, customresources)

#### 4. **Validation as the Compatibility Layer**

The OpenAPI v3 schema in CRD spec is the compatibility contract:

- **Server validates:** Every custom resource must match `spec.versions[].schema.openAPIV3Schema`
- **Client documents:** Schema is published via OpenAPI discovery
- **Tools understand:** kubectl, kubebuilder, etc. read schema for autocompletion, validation

This decouples:
- Old clients from new CRD versions (schema compatibility checked server-side)
- New clients from old instances (schema may reject unknown fields if `preserveUnknownFields: false`)

#### 5. **Information Flow During Informer Sync**

When a controller watches custom resources:

```
[API Server ETCD]
      ↓ (Watch stream)
[Informer's ListWatch]
      ↓ (deserialized Unstructured)
[Informer's Indexer/Cache]
      ↓ (event callbacks)
[Controller EventHandler]
      ↓ (controller processes event)
[Lister Query]
      ↓ (returns cached Unstructured)
[Controller Logic]
```

**Critical property:** The Indexer is a local in-memory cache. The Lister queries only the Indexer, never the API server. This enables high-frequency queries (e.g., checking if a sibling pod exists) without API server load.

### Version Handling Across Projects

The Kubernetes ecosystem handles CRD versions through conversions:

1. **CRD Type Version Management:**
   - Multiple versions of CRD spec can coexist (v1, v1beta1)
   - API server stores in internal hub representation (version-agnostic)
   - Client receives preferred version (v1) based on `SetVersionPriority`

2. **Custom Resource Version Management:**
   - Each CRD lists supported versions in `spec.versions[]`
   - Different versions can have different schemas
   - API server can automatically convert between versions if `spec.conversion.strategy=Webhook`
   - etcd storage per version (separate objects per schema generation)

3. **Client-side Version Awareness:**
   - DynamicClient doesn't enforce version
   - Client can request any version via GroupVersionResource
   - API server returns requested version (or error if not supported)

### Storage & Persistence Boundary

The ETCD storage layer (`registry/customresource/etcd.go`) is the boundary where:

- **Above:** REST HTTP semantics (Create, Update, Delete, List, Watch)
- **Below:** ETCD key-value operations (Serialization, Transactions, Versioning)

**Custom resources in ETCD:**
- Stored as Unstructured JSON
- Metadata (TypeMeta, ObjectMeta) guaranteed
- Spec/Status structure varies by CRD
- ResourceVersion used for optimistic locking

This design means:
- The ETCD serialization doesn't need Go struct definitions
- Custom resources are "opaque" to the core apiserver
- Schema evolution is managed via CRD updates, not apiserver code changes

---

## Summary

The Kubernetes CRD lifecycle flows through a carefully layered architecture:

1. **Foundation (apimachinery):** Provides Scheme (type registry), GVK/GVR (addressing), TypeMeta/ObjectMeta (required metadata), and Unstructured (dynamic representation). These types enable the entire system to work with unknown schemas.

2. **Type Definition (apiextensions-apiserver):** Registers CRD types in three versions (internal hub, v1, v1beta1) with explicit registration and installation functions. The Install() function is the single entry point for all CRD type registration.

3. **Server-Side (apiextensions-apiserver):** HTTP handler routes custom resource requests to validation (OpenAPI schema from CRD spec) and storage (ETCD backend storing Unstructured JSON). This layer enforces schema constraints but remains agnostic to actual field structure.

4. **Client-Side (client-go):** DynamicClient provides untyped HTTP access, SharedIndexInformer caches objects locally via ListWatch, and DynamicLister queries the cache. This layer enables controllers to work with arbitrary CRD types without generated code, accessing everything as Unstructured.

The architecture's key insight: **Unstructured is the universal serialization format that bridges all four sub-projects.** The server doesn't need to understand custom fields (validation is schema-based, not code-based); clients don't need generated code (they query Unstructured maps); the informer cache stores Unstructured objects. This enables CRDs to extend the Kubernetes API without modifying apiserver code or client binaries—only CRD definitions change.

