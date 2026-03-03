# Kubernetes CRD Lifecycle Architecture Analysis

## Files Examined

### apiextensions-apiserver (CRD Type Definitions, Validation, Server-Side Storage & Handler)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/types.go` — Internal hub type definitions for CustomResourceDefinition, CustomResourceDefinitionSpec, CustomResourceConversion, and validation structs
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go` — External v1 types for CustomResourceDefinition with the same structure as internal types (for wire protocol)
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/register.go` — Internal group registration using SchemeGroupVersion with runtime.APIVersionInternal
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/register.go` — External v1 group registration with SchemeGroupVersion = {Group: "apiextensions.k8s.io", Version: "v1"}
- `staging/src/k8s.io/apiextensions-apiserver/pkg/apiserver/customresource_handler.go` — Dynamic HTTP handler (crdHandler) serving `/apis` endpoint; uses informers and listers to track CRDs and dynamically route requests
- `staging/src/k8s.io/apiextensions-apiserver/pkg/registry/customresource/etcd.go` — RESTful storage layer wrapping etcd through genericregistry.Store with Unstructured objects as NewFunc/NewListFunc
- `staging/src/k8s.io/apiextensions-apiserver/pkg/crdserverscheme/unstructured.go` — UnstructuredObjectTyper for extracting GVK from Unstructured objects at runtime (without Go type registry)

### apimachinery (Foundational Types & Runtime Scheme)
- `staging/src/k8s.io/apimachinery/pkg/runtime/scheme.go` — Scheme type registry; maps GroupVersionKind ↔ reflect.Type; handles type registration and conversion
- `staging/src/k8s.io/apimachinery/pkg/runtime/types.go` — TypeMeta (apiVersion, kind fields); base for all serialized objects
- `staging/src/k8s.io/apimachinery/pkg/runtime/interfaces.go` — Core runtime interfaces: Encoder, Decoder, ObjectTyper, GroupVersioner
- `staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/types.go` — ObjectMeta struct (name, namespace, uid, labels, annotations, owner references, deletion timestamp, etc.); standard metadata for all persisted resources
- `staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/unstructured/unstructured.go` — Unstructured type: a map[string]interface{} wrapper implementing runtime.Object, metav1.Object; enables dynamic access to objects without Go struct definitions

### client-go (Typed Clients, Informers, Listers, Dynamic Client)
- `staging/src/k8s.io/client-go/dynamic/interface.go` — Dynamic client interface: Resource(gvr) → NamespaceableResourceInterface with CRUD methods operating on Unstructured objects
- `staging/src/k8s.io/client-go/dynamic/dynamicinformer/informer.go` — DynamicSharedInformerFactory: creates DynamicInformers by GroupVersionResource; returns GenericInformers
- `staging/src/k8s.io/client-go/informers/factory.go` — SharedInformerFactory: typed informer factory using kubernetes.Interface clientset; creates SharedIndexInformers by type
- `staging/src/k8s.io/client-go/tools/cache/shared_informer.go` — SharedIndexInformer: local in-memory cache of objects; watches etcd via reflector and stores objects in thread-safe store
- `staging/src/k8s.io/client-go/kubernetes/clientset.go` — Typed Clientset: generated interface aggregating all version-specific client interfaces (e.g., AppsV1, CoreV1, etc.)

## Dependency Chain

### 1. Foundation: apimachinery Types
The four sub-projects depend on apimachinery's foundational types:

- **TypeMeta** (apimachinery/pkg/runtime/types.go): Contains `apiVersion` and `kind` fields; embedded in all serialized objects
- **ObjectMeta** (apimachinery/pkg/apis/meta/v1/types.go): Standardized metadata (name, namespace, UID, labels, annotations, owner references, deletion timestamps, etc.); all persisted resources carry ObjectMeta
- **Scheme** (apimachinery/pkg/runtime/scheme.go): Central type registry mapping GroupVersionKind → Go reflect.Type; enables serialization/deserialization; stores registered types, conversion functions, and field label converters
- **GVK/GVR** (apimachinery/pkg/runtime/schema): GroupVersionKind and GroupVersionResource types; unique identifiers for all API objects
- **Unstructured** (apimachinery/pkg/apis/meta/v1/unstructured): Map-based representation of objects without compiled Go types; critical for dynamic CR access

### 2. Type Definitions: apiextensions-apiserver Types
apiextensions-apiserver defines the CRD resource itself:

- **Internal Hub Types** (apiextensions/types.go):
  - `CustomResourceDefinition`: Hub type in __internal version; contains spec, status, metadata
  - `CustomResourceDefinitionSpec`: Defines group, names, scope (cluster/namespaced), validation schema, versions, conversion strategy
  - Registered in Scheme via `SchemeGroupVersion = {Group: "apiextensions.k8s.io", Version: "__internal"}`

- **External v1 Types** (apiextensions/v1/types.go):
  - `CustomResourceDefinition` v1: Mirrored structure with same fields for API wire protocol
  - `ConversionReview`: For webhook-based version conversion
  - Registered via `SchemeGroupVersion = {Group: "apiextensions.k8s.io", Version: "v1"}`
  - Conversion functions convert between internal and v1 representations

- **Scheme Registration Chain**:
  - Internal: `addKnownTypes(scheme)` registers `CustomResourceDefinition`, `CustomResourceDefinitionList` in __internal version
  - v1: `addKnownTypes(scheme)` registers same types in v1, plus `ConversionReview`
  - Both call `metav1.AddToGroupVersion(scheme, SchemeGroupVersion)` to register ObjectMeta helpers

### 3. Server-Side: Validation → Storage → HTTP Handler
Three-layer request path for custom resources:

**Validation Layer** (apiextensions/validation):
- Validates incoming CR against CRD's OpenAPI schema
- Enforces schema constraints, required fields, type checking
- Pruning of unknown fields (unless `preserveUnknownFields: true`)

**Storage Layer** (customresource/etcd.go):
- `CustomResourceStorage` wraps `genericregistry.Store`
- `NewFunc`: Creates empty `unstructured.Unstructured{}` objects (no compiled Go type)
- `NewListFunc`: Creates `unstructured.UnstructuredList{}`
- Storage strategy implements validation, field defaults, status subresource handling
- Uses etcd backend via `generic.RESTOptionsGetter`
- All CRs are stored as Unstructured; GVK set explicitly as hint to versioning decoder

**HTTP Handler** (customresource_handler.go):
- `crdHandler` serves `/apis` endpoint as a filter
- Maintains `crdLister` (informer-backed): watches CustomResourceDefinition objects
- For each CRD, dynamically creates/updates `crdStorage` in `customStorage` atomic.Value
- On API request: handler looks up CRD, routes to appropriate `crdStorage.CustomResource` REST handler
- Handler imports informers/listers from apiextensions-apiserver client; uses them to track CRD lifecycle

**Checkpoint**: Unstructured objects flow through etcd as JSON; schema validation ensures data consistency

### 4. Client-Side Access Layer: Typed Client → Informer → Lister → Dynamic Client

#### Typed Clientset Path (for built-in types):
- **Clientset** (client-go/kubernetes/clientset.go): Aggregated interface with version-specific clients (CoreV1, AppsV1, etc.)
- Each client is generated per API group/version
- Provides strongly-typed methods: `Pods()`, `Deployments()`, etc.

#### Typed Informer Path (for built-in types):
- **SharedInformerFactory** (client-go/informers/factory.go):
  - Takes `kubernetes.Interface` clientset and resync duration
  - Creates `SharedIndexInformer` per resource type
  - Internally uses cache.Indexers for fast lookups by namespace/name

- **SharedIndexInformer** (client-go/tools/cache/shared_informer.go):
  - Maintains local in-memory cache of objects
  - Uses **Reflector** pattern: watches API server via client.Watch()
  - Delta FIFO queue processes watch events
  - Stores updates in thread-safe `Store` (default: indexable store with namespace/name index)
  - Multiple event handlers can subscribe to object updates
  - Returns **Lister** for querying the local cache

- **Listers** (client-go/listers/):
  - Generated per type; queries local cache without hitting API server
  - Fast, eventually-consistent reads from in-memory store
  - Example: `podLister.Pods(namespace).Get(name)` queries cache

#### Dynamic Client Path (for CRDs):
- **Dynamic Interface** (client-go/dynamic/interface.go):
  - `Resource(gvr)` → `NamespaceableResourceInterface`
  - All operations on `unstructured.Unstructured` objects
  - Methods: Create, Update, Delete, Get, List, Watch, Patch, Apply

- **DynamicSharedInformerFactory** (client-go/dynamic/dynamicinformer/informer.go):
  - Takes `dynamic.Interface` client
  - Creates `DynamicInformer` per GroupVersionResource
  - Returns `GenericInformer` interface (List, Get)
  - Each informer watches that GVR and caches Unstructured objects
  - Enables controllers to watch arbitrary CRDs without compiled types

- **Dynamic Lister** (client-go/dynamic/dynamiclister/):
  - Queries cache of Unstructured objects by GVR
  - Method: `ByNamespace(ns).Get(name)` returns `unstructured.Unstructured`

#### The Bridge: Unstructured + Scheme
- Both typed and dynamic paths ultimately use **Scheme** for serialization
- Typed client: Scheme knows Go type → Unstructured mapping → can unmarshal JSON into typed struct
- Dynamic client: Scheme handles Unstructured → JSON → wire format; preserves unknown fields (if enabled in CRD)
- **DefaultUnstructuredConverter**: Converts between typed structs and Unstructured; handles nested field conversion

**Checkpoint**: Informers and listers decouple client-side caching from API server; watch events trigger handlers; cache provides eventually-consistent reads

## Analysis

### Cross-Project Dependency Flow

```
apimachinery
  ├─ runtime.Scheme (type registry)
  ├─ TypeMeta (apiVersion, kind)
  ├─ ObjectMeta (standard metadata)
  ├─ Unstructured (map-based dynamic objects)
  └─ runtime.Encoder/Decoder (serialization interfaces)
       ↑
       ├─ apiextensions-apiserver
       │  ├─ CustomResourceDefinition type
       │  ├─ CRD validation schemas
       │  ├─ etcd storage via Unstructured
       │  └─ HTTP handler routes requests to per-CRD storage
       │       ↑
       │       └─ uses client-go informers to watch CRDs
       │
       └─ client-go
          ├─ Typed Client (clientset, informers, listers)
          │  └─ Strongly typed access to built-in APIs
          ├─ Dynamic Client (dynamic.Interface)
          │  └─ Unstructured access to any resource (including CRDs)
          └─ SharedInformer/cache (local copy of objects)
             └─ Eventually consistent with server via watch

```

### How CRD Types Bridge the Four Sub-Projects

1. **Definition to Registration**:
   - User creates a CRD object (a CustomResourceDefinition) using v1 types (apiextensions/v1)
   - apiextensions-apiserver validates, stores, and watches for CRD changes
   - When CRD is created, apiextensions-apiserver dynamically creates a REST handler for that resource

2. **Storage Abstraction**:
   - CRDs stored as Unstructured in etcd via genericregistry.Store
   - No compiled Go type needed; GVK drives deserialization
   - Unstructured objects maintain TypeMeta (apiVersion, kind) for proper typing

3. **Dynamic Routing**:
   - crdHandler in customresource_handler.go watches CustomResourceDefinition objects
   - Uses apiextensions client informers/listers to detect new/changed CRDs
   - For each CRD, builds a RESTful storage layer
   - Incoming API requests matched against CRD group/version/kind and routed to handler

4. **Client-Side Caching**:
   - Controllers use DynamicSharedInformerFactory to watch any CRD (no code generation needed)
   - Informers use dynamic.Interface to list/watch CRs from API server
   - Local cache of Unstructured objects enables efficient event-driven processing
   - Listers query cache; handlers react to watch events

### Role of Scheme and GVK

**Scheme** (apimachinery/pkg/runtime/scheme.go):
- Central registry for all serializable types
- Maps between GroupVersionKind and Go reflect.Type
- apiextensions-apiserver registers CustomResourceDefinition types
- client-go's Clientset registers all built-in API types
- Enables polymorphic serialization: same Scheme can encode/decode Pod, Deployment, CustomResource, etc.
- For CRDs: Unstructured type is registered with dynamic type detection via UnstructuredObjectTyper

**GVK/GVR** (apimachinery/pkg/runtime/schema):
- GroupVersionKind: (group, version, kind) uniquely identifies a type — e.g., ("apps", "v1", "Deployment")
- GroupVersionResource: (group, version, resource) for REST resources — e.g., ("apps", "v1", "deployments")
- apiextensions-apiserver uses GVK from CRD spec to route requests
- client-go uses GVR to construct REST paths and watch endpoints

### How Unstructured Enables Dynamic Custom Resource Access

**Unstructured Type** (apimachinery/pkg/apis/meta/v1/unstructured):
- Wraps a `map[string]interface{}` with accessors for TypeMeta and ObjectMeta fields
- Implements `runtime.Object`, `metav1.Object`, `metav1.ListInterface`
- Does NOT require a compiled Go struct definition
- JSON marshaling preserves unknown fields (depending on CRD's `preserveUnknownFields` setting)

**Why This Matters for CRDs**:
- CRD user defines schema in YAML; no Go code generation required
- apiextensions-apiserver stores CR data as Unstructured
- controller-gen not needed for CRD users (though it's used by Kubernetes itself)
- Dynamic client can create, read, update CRs at runtime without recompilation
- Unstructured objects still carry metadata (name, namespace, uid) via ObjectMeta helpers

### The Checkpoint: Server-Side Storage to Client-Side Caching

**Where Data Flows**:
1. **API Server (etcd)**: CR stored as Unstructured JSON document
   - Schema validation ensures conformance to CRD specification
   - ResourceVersion incremented on each change

2. **Watch Channel**: API server streams change events (Added, Modified, Deleted)
   - Events contain Unstructured object at new resource version

3. **Informer Reflector**: Client-side watcher (client-go/tools/cache/reflector.go)
   - Issues list request to get initial objects
   - Issues watch request for incremental updates
   - Updates local cache with each event

4. **Local Cache Store**: In-memory thread-safe store
   - Indexed by namespace/name (can also add custom indexes)
   - Listers query this store directly (no API call)
   - Event handlers notified of changes for downstream processing

**Consistency Guarantees**:
- Eventually consistent: lag between server change and local cache update
- No data loss (assuming no API server outage): watch event delivery is best-effort but reliable
- Ordered: events for a single object maintain ordering; cross-object ordering not guaranteed
- Stale reads possible: lister reads from cache snapshot taken at query time

## Summary

Kubernetes CRDs exemplify a layered architecture spanning four sub-projects: **apimachinery** provides the runtime foundation (Scheme, TypeMeta, ObjectMeta, Unstructured); **apiextensions-apiserver** implements the CRD type system, validation, etcd storage, and dynamic HTTP routing; **client-go** offers both typed and dynamic client abstractions, with informers and listers providing efficient, eventually-consistent local caching. The **Unstructured** type is the key bridge: it enables CRs to be stored, transmitted, and cached without compiled Go types, while still maintaining proper metadata and serialization semantics through the Scheme registry and GVK-driven type detection. This architecture decouples type definition (CRD YAML) from type implementation (Go code), allowing extensibility without rebuilding the API server.
