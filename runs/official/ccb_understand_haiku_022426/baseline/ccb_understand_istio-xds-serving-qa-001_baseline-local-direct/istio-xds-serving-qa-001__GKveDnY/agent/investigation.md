# Istio Pilot xDS Serving Architecture

## Q1: Config Ingestion Pipeline

### How does Pilot watch and ingest Kubernetes custom resources?

Istio Pilot watches Kubernetes CRDs (VirtualService, DestinationRule, ServiceEntry, Gateway, etc.) through the **`ConfigStoreController` interface**, implemented by `Client` in `/workspace/pilot/pkg/config/kube/crdclient/client.go` (lines 63-174).

#### ConfigStoreController Interface
**Location**: `/workspace/pilot/pkg/model/config.go`, lines 188-201

The `ConfigStoreController` extends `ConfigStore` with lifecycle management:
- `RegisterEventHandler(ConfigType, handler)` - Registers callbacks per resource type
- `Run(ctx context.Context)` - Starts the controller
- `HasSynced()` - Checks if initial sync is complete

#### Kubernetes Informer Implementation
**Location**: `/workspace/pilot/pkg/config/kube/crdclient/client.go`, lines 63-174

The implementation uses **Kubernetes informers** for efficient incremental watching:
- One informer per CRD GVK (GroupVersionKind)
- Incremental sync only pushes changed resources
- Handles initial list + watch pattern automatically
- Deduplicates rapid changes before notifying handlers

#### Config Change Event Flow

1. **Config Resource Changes**: VirtualService, DestinationRule, ServiceEntry CRDs are updated in Kubernetes
2. **Informer Notification**: Kubernetes informer detects the change (Add/Update/Delete)
3. **Event Handler Invocation**: Registered event handler is called for that resource type
4. **ConfigUpdate Call**: Handler calls `DiscoveryServer.ConfigUpdate(PushRequest)` (/workspace/pilot/pkg/xds/discovery.go, lines 297-318)
5. **Push Channel**: PushRequest is sent to the debounce channel for batching

#### Aggregate Service Registry

**Location**: `/workspace/pilot/pkg/model/context.go`, lines 97-144

The `Environment` struct holds:
- `ServiceDiscovery` - The aggregated service registry interface
- Multiple registry implementations (Kubernetes, ServiceEntries, etc.) are merged at this layer
- **`EndpointIndex`** (`/workspace/pilot/pkg/model/endpointshards.go`, lines 140-289) - Global endpoint index organizing endpoints by service/namespace
- Service discovery queries hit the aggregated registry, consolidating views from multiple sources

#### Endpoint Update Propagation

**Location**: `/workspace/pilot/pkg/xds/eds.go`, lines 47-60

When service endpoints change:
1. **EDSUpdate()** is called by the service registry (Kubernetes controller)
2. **EndpointIndex.UpdateServiceEndpoints()** updates the global endpoint shard (`/workspace/pilot/pkg/model/endpointshards.go`, lines 271-289)
3. **Returns PushType**: `NoPush`, `IncrementalPush`, or `FullPush`
4. If push needed, a PushRequest is created with the ServiceEntry ConfigKey
5. Flows through debounce → Push execution

---

## Q2: Internal Service Model

### How does Pilot translate platform-specific resources into its internal model?

#### Key Internal Model Types

**Service** - `/workspace/pilot/pkg/model/service.go`, lines 69-123
- Represents a mesh service (hostname)
- Fields:
  - `Hostname` - FQDN (e.g., "reviews.default.svc.cluster.local")
  - `Ports` - Service listening ports with protocols
  - `ClusterVIPs` - Service addresses per cluster
  - `ServiceAccounts` - Associated RBAC identities
  - `Attributes` - Labels, namespace, external flag
  - `Resolution` - Endpoint discovery type: EDS, STATIC, DNSLB, PASSTHROUGH
  - `MeshExternal` - Boolean flag for mesh-external services

Both Kubernetes Services and Istio ServiceEntries are converted to this unified `Service` model.

**IstioEndpoint** - `/workspace/pilot/pkg/model/service.go`, lines 484-551
- Represents a single service endpoint instance
- Fields:
  - `Addresses` - Endpoint IP (supports dual-stack)
  - `ServicePortName` - Port name referenced in Service
  - `EndpointPort` - Actual workload port
  - `ServiceAccount` - Workload identity
  - `Network` - Network ID for multi-cluster
  - `Locality` - Region/zone/sub-zone info
  - `TLSMode` - mTLS mode: ISTIO, PERMISSIVE, DISABLE
  - `Labels` - Workload labels (pod labels for K8s)
  - `HealthStatus` - Healthy/Unhealthy
  - `DiscoverabilityPolicy` - Mesh-wide or cluster-local visibility
- Key method `IsDiscoverableFromProxy()` checks if endpoint is visible from a proxy

#### PushContext - The Computed Model

**Location**: `/workspace/pilot/pkg/model/push_context.go`, lines 206-279

`PushContext` is the computed state for a single push operation. It contains all derived configurations indexed for fast lookup:

- **ServiceIndex**: Indexed services by hostname, namespace, etc.
- **virtualServiceIndex**: Indexed VirtualServices by hostname/namespace
- **destinationRuleIndex**: Indexed DestinationRules by hostname/namespace
- **sidecarIndex**: Indexed SidecarScopes
- **AuthnPolicies**: Authentication policy configuration
- **AuthzPolicies**: Authorization policy configuration
- **ProxyStatus**: Per-proxy state tracking
- **PushVersion**: Version ID for this push (monotonically increasing)
- **JwtKeyResolver**: JWKS key cache for JWT validation

#### PushContext Initialization

**Location**: `/workspace/pilot/pkg/model/push_context.go`, line 713

`NewPushContext()` creates new context, then `InitContext()` method:
- Iterates all Services from ServiceDiscovery
- For each service, builds indexed maps
- For each service, fetches endpoints from EndpointIndex
- Collects all Istio resources (VirtualService, DestinationRule, etc.)
- Indexes them by hostname/namespace
- Computes derived state (route conflicts, ambiguities, etc.)
- Caches results in memory for fast queries during xDS generation

#### Kubernetes Service → Internal Service Model

The conversion happens in service registry implementations:
- Kubernetes Service with ClusterIP becomes Service with `Resolution: EDS`
- Endpoints are fetched separately and stored in EndpointIndex
- ServiceEntry CRD directly creates a Service with specified resolution type
- Both flow through `ServiceDiscovery` interface for unified access

#### Proxy Model

**Location**: `/workspace/pilot/pkg/model/context.go`, lines 294-390

The `Proxy` struct represents a connected xDS client:
- `Type` - NodeType (SidecarProxy, Router, Waypoint)
- `ID` - Unique ID (e.g., "pod.namespace")
- `IPAddresses` - Pod/VM IPs
- `Metadata` - NodeMetadata (cluster, namespace, labels)
- `SidecarScope` - Scoped VirtualServices and DestinationRules visible to this proxy
- `ServiceTargets` - Services this proxy implements
- `WatchedResources` - Resource types client has subscribed to
- `XdsResourceGenerator` - Custom generator if proxy-specific
- `LastPushContext` - Most recent PushContext used for this proxy

The `SidecarScope` limits configuration to only relevant services and rules based on selector matching.

---

## Q3: xDS Generation and Dispatch

### How does Pilot generate and deliver xDS responses?

#### DiscoveryServer - Core xDS Server

**Location**: `/workspace/pilot/pkg/xds/discovery.go`, lines 64-135

The `DiscoveryServer` struct:
- Implements gRPC ADS (Aggregated Discovery Service)
- **Fields**:
  - `Env` - Environment reference
  - `Generators` - Map of XdsResourceGenerator implementations (CDS, EDS, LDS, RDS)
  - `Cache` - XDS resource cache (model.XdsCache)
  - `pushChannel` - Debounce buffer for config change batching
  - `pushQueue` - Ordered queue for push execution
  - `adsClients` - Active gRPC connections
  - `DebounceOptions` - Timing parameters (DebounceAfter, debounceMax)
  - `InboundUpdates` - Atomic counter
  - `CommittedUpdates` - Atomic counter

#### Config Update Reception

**Location**: `/workspace/pilot/pkg/xds/discovery.go`, lines 297-318

`ConfigUpdate()` method:
1. Called when ConfigStoreController detects a config change
2. Creates PushRequest with changed ConfigKey objects
3. Sends to pushChannel (buffers up to 100 items)
4. Returns immediately (non-blocking)

#### Debouncing Logic

**Location**: `/workspace/pilot/pkg/xds/discovery.go`, lines 325-427

`handleUpdates()` runs in a separate goroutine:
1. Receives requests from pushChannel
2. Waits for quiet period (DebounceAfter - default 100ms)
3. **OR** waits for max delay (debounceMax - default 10s)
4. Merges multiple PushRequests during debounce window
5. Consolidates ConfigsUpdated sets
6. Calls `Push()` when debounce completes

This batching prevents "thundering herd" on rapid config changes.

#### Push Execution

**Location**: `/workspace/pilot/pkg/xds/discovery.go`, lines 254-282

`Push()` method:
1. **For Full Push**:
   - Calls `initPushContext()` (lines 507-522) to create new PushContext
   - `initPushContext()` calls `NewPushContext()` and `InitContext()`
   - Calls `Env.SetPushContext()` to update global context
   - Calls `dropCacheForRequest()` to invalidate cache (all entries if full push)
   - Calls `AdsPushAll()` to notify all connected proxies

2. **For Incremental Push**:
   - Reuses current PushContext
   - Calls `dropCacheForRequest()` to invalidate only affected ConfigKey entries
   - Calls `AdsPushAll()` with partial resource list

#### Cache Invalidation

**Location**: `/workspace/pilot/pkg/xds/discovery.go`, lines 242-250

`dropCacheForRequest()`:
- If ConfigsUpdated is empty (endpoint-only update): clears entire cache
- Otherwise: iterates ConfigKey objects and clears specific cache entries
- Uses `Cache.Clear(key)` for granular invalidation

#### Generator Architecture

**Location**: `/workspace/pilot/pkg/xds/discovery.go`, lines 506

Generators are registered in a map:
- `CdsGenerator` - Cluster Discovery Service
- `EdsGenerator` - Endpoint Discovery Service
- `LdsGenerator` - Listener Discovery Service
- `RdsGenerator` - Route Discovery Service (HTTP routing)

#### Generator Selection and Dispatch

When `AdsPushAll()` is called for a proxy:
1. Iterates all proxies with active connections
2. For each proxy, gets `WatchedResources` (subscribed resource types)
3. For each watched resource type:
   - Selects the appropriate generator from the map
   - Calls `generator.Generate(proxy, WatchedResource, PushRequest)`
   - Returns `Resources` (xDS resources) and `XdsLogDetails` (for debugging)
   - Sends DiscoveryResponse back over gRPC

#### Generator Interface

**Location**: `/workspace/pilot/pkg/model/context.go`, lines 276-286

```go
type XdsResourceGenerator interface {
    Generate(proxy *Proxy, w *WatchedResource, req *PushRequest)
        (Resources, XdsLogDetails, error)
}

type XdsDeltaResourceGenerator interface {
    XdsResourceGenerator
    GenerateDeltas(proxy *Proxy, req *PushRequest, w *WatchedResource)
        (Resources, DeletedResources, XdsLogDetails, bool, error)
}
```

Delta generators support incremental updates (SoTW vs delta protocol).

#### PushRequest Structure

**Location**: `/workspace/pilot/pkg/model/push_context.go`, lines 357-391

- `Full` - Boolean: is this a full or incremental push?
- `ConfigsUpdated` - Set of ConfigKey objects that changed
- `Push` - PushContext (initially nil, filled during debounce)
- `Start` - Timestamp for metrics
- `Reason` - ReasonStats map tracking why push was triggered
  - EndpointUpdate, ConfigUpdate, ServiceUpdate, ProxyUpdate, GlobalUpdate

---

## Q4: Resource Translation

### How do Istio resources map to Envoy xDS?

#### DestinationRule → CDS (Cluster Settings)

**Entry Point**: `/workspace/pilot/pkg/xds/cds.go`, lines 26-28, 123-129

CdsGenerator.Generate() calls ConfigGenerator.BuildClusters()

**Translation**: `/workspace/pilot/pkg/networking/core/cluster.go`

- **Lines 52-65**: `BuildClusters()` main entry point, filters services by proxy type
- **Lines 211-282**: `buildClusters()` core logic
  - Line 217: Creates ClusterBuilder for proxy
  - Line 224 (sidecar): calls `buildOutboundClusters()`
  - Line 232 (sidecar): calls `buildInboundClusters()`
- **Lines 299-375**: `buildOutboundClusters()`
  - Line 330: Creates default cluster via `buildCluster()`
  - **Line 352: Applies DestinationRule via `applyDestinationRule()`** ← KEY POINT

**DestinationRule Application**: `/workspace/pilot/pkg/networking/core/cluster_builder.go`

- **Lines 219-277**: `applyDestinationRule()` handler
  - Line 222: Casts config to DestinationRule
  - Line 224: Extracts port-level traffic policy
  - **Line 248: Applies traffic policy to cluster** via `applyTrafficPolicy()`
  - Lines 270-275: Builds subset clusters for each DestinationRule subset

**Traffic Policy → Cluster Settings**: `/workspace/pilot/pkg/networking/core/cluster_traffic_policy.go`

- **Lines 41-66**: `applyTrafficPolicy()` dispatcher
  - Line 49: Calls `applyConnectionPool()`
  - Line 52: Calls `applyOutlierDetection()`
  - Line 53: Calls `applyLoadBalancer()`
  - Lines 54-60: Calls `applyUpstreamTLSSettings()`

**Connection Pool → Envoy Circuit Breaker**:
- **Lines 94-179**: `applyConnectionPool()`
  - Lines 108-125: HTTP settings (maxRequests, pendingRequests, retries, idleTimeout)
  - Lines 128-142: TCP settings (timeout, maxConnections, connectDuration)
  - Sets Envoy `CircuitBreaker` proto fields

**Load Balancer → Envoy LB Policy**:
- **Lines 235-277**: `applyLoadBalancer()`
  - Line 244: Gets locality LB settings
  - Lines 259-274: Simple policies (LEAST_CONN, RANDOM, ROUND_ROBIN, PASSTHROUGH)
  - Line 276: Consistent hashing (RingHash, Maglev)
  - Maps Istio LoadBalancerSettings to Envoy Cluster LbPolicy

**Outlier Detection**:
- **Lines 409-476**: `applyOutlierDetection()`
  - Lines 419-427: Consecutive 5xx errors
  - Lines 429-437: Consecutive gateway errors
  - Lines 440-445: Interval and base ejection time
  - Lines 446-448: Max ejection percent
  - Maps Istio OutlierDetection to Envoy OutlierDetection proto

**TLS Settings → Transport Socket**:
- **`/workspace/pilot/pkg/networking/core/cluster_tls.go`, lines 94-134**: `applyUpstreamTLSSettings()`
  - Line 101: Builds upstream TLS context
  - Lines 108-112: Sets transport socket with TLS config
  - Lines 115-133: Handles HBONE and auto-mTLS transport socket matches
  - Maps Istio ClientTLSSettings to Envoy UpstreamTlsContext

#### VirtualService → RDS (Route Configuration)

**Entry Point**: `/workspace/pilot/pkg/xds/rds.go`, lines 24-26, 64-70

RdsGenerator.Generate() calls ConfigGenerator.BuildHTTPRoutes()

**Translation**: `/workspace/pilot/pkg/networking/core/httproute.go`

- **Lines 58-113**: `BuildHTTPRoutes()` main entry point
  - Line 67-68 (sidecar): calls `buildSidecarOutboundHTTPRouteConfig()`
  - Line 98 (gateway): calls `buildGatewayHTTPRouteConfig()`
  - Returns route configurations as xDS resources

**VirtualService to Routes**: `/workspace/pilot/pkg/networking/core/route/route.go`

- **Lines 377-424**: `BuildHTTPRoutesForVirtualService()` main translator
  - Line 386: Extracts VirtualService spec
  - Lines 391-418: Processes `spec.http[]` array
    - For each HTTPRoute: calls `translateRoute()`
  - Line 408: Detects catch-all routes for optimization

- **Lines 447-550**: `translateRoute()` individual route translation
  - Line 478: Translates match conditions via `TranslateRouteMatch()`
  - Lines 486-493: Handles header operations
  - Line 502: **Applies destination via `applyHTTPRouteDestination()`** ← KEY POINT

- **Lines 552-654**: `applyHTTPRouteDestination()` destination processing
  - Line 563: Creates Envoy `RouteAction`
  - Lines 631-632 (single dest): calls `processDestination()`
  - Lines 636-650 (multiple dests): calls `processWeightedDestination()`
  - Maps VirtualService destinations to Envoy clusters

- **Lines 659-692**: `processDestination()`
  - **Line 667: Calls `GetDestinationCluster()`** to map destination to cluster name
  - Applies header operations and hash policies

- **Lines 334-359**: `GetDestinationCluster()` destination → cluster mapping
  - **Line 358: Returns cluster name in format: `outbound|<port>|<subset>|<hostname>`**
  - Handles subset and port resolution
  - This cluster name is used to lookup the CDS cluster built earlier

#### ServiceEntry → ClusterLoadAssignment (EDS)

**Entry Point**: `/workspace/pilot/pkg/xds/eds.go`, lines 84-87, 124-130

EdsGenerator.Generate() calls `buildEndpoints()`

- **Lines 174-235**: `buildEndpoints()` main EDS builder
  - Lines 192-230: For each requested cluster name:
    - Line 200: Creates `EndpointBuilder` for cluster
    - **Line 214: Calls `BuildClusterLoadAssignment()`** ← Returns endpoints

**EndpointBuilder**: `/workspace/pilot/pkg/xds/endpoints/endpoint_builder.go`

- **Lines 60-83**: `EndpointBuilder` struct
  - Lines 61-66: Cache key fields (cluster name, network, clusterID, etc.)
  - **Line 67: `destinationRule *model.ConsolidatedDestRule`** - For subset label matching
  - Line 68: `service *model.Service` - Service being built

- **Lines 85-99**: `NewEndpointBuilder()` constructor
  - Line 88: Gets service for hostname
  - **Lines 90-92: Gets DestinationRule for service** - For subset info
  - Returns builder with all context

- **Lines 144-152**: `WithSubset()` creates builder for specific subset
  - Clones builder with subset name
  - **Calls `populateSubsetInfo()`**

- **Lines 154-161**: `populateSubsetInfo()` extracts subset configuration
  - **Line 160: Gets subset labels from DestinationRule**
  - Sets up label matcher for subset filtering

**ClusterLoadAssignment Construction**:
The actual `BuildClusterLoadAssignment()` method uses:
1. **EndpointIndex.ShardsForService()** - Gets service endpoints from the global index
2. **Applies subset filtering** - Uses DestinationRule subset labels to filter endpoints
3. **Handles locality-aware routing** - Groups endpoints by locality (zone, region)
4. **Returns ClusterLoadAssignment** - Envoy proto with LocalityLbEndpoints structure

**Service Endpoint Update Flow**:
1. Kubernetes controller detects Pod addition/removal
2. **EDSUpdate()** called with service and endpoints `/workspace/pilot/pkg/xds/eds.go:47-60`
3. **EndpointIndex.UpdateServiceEndpoints()** updates global index `/workspace/pilot/pkg/model/endpointshards.go:271-289`
4. Returns PushType (IncrementalPush for EDS-only changes)
5. **ConfigUpdate()** called with ServiceEntry ConfigKey
6. Debounce merges endpoint updates
7. CdsGenerator checks `cdsNeedsPush()` (line 66 in cds.go) - skips CDS update
8. EdsGenerator generates new ClusterLoadAssignment with updated endpoints

#### ConfigGenerator Implementation

**Location**: `/workspace/pilot/pkg/networking/core/configgen.go`, lines 27-54

The `ConfigGenerator` interface provides three main methods:
- **BuildClusters()** - Called by CdsGenerator for CDS
- **BuildDeltaClusters()** - Delta variant of BuildClusters
- **BuildHTTPRoutes()** - Called by RdsGenerator for RDS

Implementation (`ConfigGeneratorImpl` in same file):
- **Line 57**: Contains `Cache model.XdsCache` for caching generated resources
- Methods use PushContext and Proxy to generate xDS resources
- Cache key typically includes: Proxy ID, resource type, version

#### Resource Translation Summary

| Istio Resource | xDS Type | Translation Entry | Key Methods |
|---|---|---|---|
| DestinationRule | CDS | `/pilot/pkg/xds/cds.go:123` | `BuildClusters()` → `applyDestinationRule()` |
| DestinationRule TrafficPolicy | CircuitBreaker | `/pilot/pkg/networking/core/cluster_traffic_policy.go:94-179` | `applyConnectionPool()` |
| DestinationRule LoadBalancer | LbPolicy | `/pilot/pkg/networking/core/cluster_traffic_policy.go:235-277` | `applyLoadBalancer()` |
| DestinationRule OutlierDetection | OutlierDetection | `/pilot/pkg/networking/core/cluster_traffic_policy.go:409-476` | `applyOutlierDetection()` |
| DestinationRule ClientTLS | TransportSocket | `/pilot/pkg/networking/core/cluster_tls.go:94-134` | `applyUpstreamTLSSettings()` |
| VirtualService HTTPRoute | Route | `/pilot/pkg/networking/core/route/route.go:447-550` | `translateRoute()` |
| VirtualService Destination | WeightedCluster | `/pilot/pkg/networking/core/route/route.go:552-654` | `applyHTTPRouteDestination()` |
| Service Endpoint | ClusterLoadAssignment | `/pilot/pkg/xds/eds.go:174-235` | `BuildClusterLoadAssignment()` |
| DestinationRule Subset | Endpoint Filtering | `/pilot/pkg/xds/endpoints/endpoint_builder.go:154-161` | `populateSubsetInfo()` |

---

## Evidence

### Core Configuration and Model Files
- `/workspace/pilot/pkg/model/config.go` - ConfigStore and ConfigStoreController interfaces (lines 137-201)
- `/workspace/pilot/pkg/model/context.go` - Environment, Proxy, XdsResourceGenerator interfaces (lines 97-390)
- `/workspace/pilot/pkg/model/service.go` - Service and IstioEndpoint models (lines 69-551)
- `/workspace/pilot/pkg/model/push_context.go` - PushContext, PushRequest, TriggerReason (lines 206-456)
- `/workspace/pilot/pkg/model/endpointshards.go` - EndpointIndex structure (lines 140-289)

### Configuration Management Layer
- `/workspace/pilot/pkg/config/kube/crdclient/client.go` - ConfigStoreController implementation with K8s informers (lines 63-174)

### xDS Discovery and Generation
- `/workspace/pilot/pkg/xds/discovery.go` - DiscoveryServer, ConfigUpdate, Push execution, debouncing (lines 64-527)
- `/workspace/pilot/pkg/xds/cds.go` - CdsGenerator for cluster discovery (lines 26-140)
- `/workspace/pilot/pkg/xds/eds.go` - EdsGenerator for endpoint discovery (lines 47-235)
- `/workspace/pilot/pkg/xds/lds.go` - LdsGenerator for listener discovery (lines 27-113)
- `/workspace/pilot/pkg/xds/rds.go` - RdsGenerator for route discovery (lines 24-70)

### Configuration Generation Layer
- `/workspace/pilot/pkg/networking/core/configgen.go` - ConfigGenerator interface (lines 27-64)
- `/workspace/pilot/pkg/networking/core/cluster.go` - Cluster building and DestinationRule application (lines 52-375)
- `/workspace/pilot/pkg/networking/core/cluster_builder.go` - ClusterBuilder with subset handling (lines 160-277)
- `/workspace/pilot/pkg/networking/core/cluster_traffic_policy.go` - Traffic policy application (lines 41-476)
- `/workspace/pilot/pkg/networking/core/cluster_tls.go` - TLS settings translation (lines 94-150)
- `/workspace/pilot/pkg/networking/core/httproute.go` - HTTP route building (lines 58-150)
- `/workspace/pilot/pkg/networking/core/route/route.go` - VirtualService to route translation (lines 334-692)

### Endpoint Building
- `/workspace/pilot/pkg/xds/endpoints/endpoint_builder.go` - EndpointBuilder with subset support (lines 60-161)

### Service Registry
- `/workspace/pilot/pkg/serviceregistry/instance.go` - Instance interface for multiple registries (lines 23-34)

---

## Architectural Patterns

**1. Incremental vs Full Pushes**
- Full push: Creates new PushContext, recomputes all indices from scratch
- Incremental push: Reuses PushContext, only invalidates affected cache entries
- Endpoint-only updates (EDS) skip CDS/LDS/RDS generation

**2. Debouncing and Batching**
- Config changes queue in pushChannel (100-item buffer)
- handleUpdates() waits for quiet period or max delay
- Multiple requests merged during window to batch rapid changes

**3. ConfigKey-Based Cache Invalidation**
- Each config has a ConfigKey (name, namespace, version)
- Cache stored by key, allowing granular invalidation
- Reduces CPU/memory on small changes

**4. Proxy Scoping**
- SidecarScope limits visible services and DestinationRules
- Reduces computation for each push
- Scoped config queries from PushContext

**5. Service Model Unification**
- Both Kubernetes Services and Istio ServiceEntries → same Service model
- Consolidated view via ServiceDiscovery interface
- Endpoints indexed globally in EndpointIndex

**6. Generator Architecture**
- XdsResourceGenerator interface allows pluggable implementations
- CDS, EDS, LDS, RDS generators registered in map
- Dispatched based on proxy WatchedResources

**7. Cluster Name as Linking Pin**
- VirtualService destinations translate to cluster names: `outbound|<port>|<subset>|<hostname>`
- RDS routes reference clusters built by CDS
- EDS cluster names match CDS cluster names
- Ensures routing and endpoint consistency
