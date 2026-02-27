# Istio Pilot xDS Serving Architecture

## Q1: Config Ingestion Pipeline

### How Pilot watches and ingests Kubernetes custom resources

**ConfigStoreController Interface**
The config ingestion pipeline is built on the `ConfigStoreController` interface (pilot/pkg/model/config.go:188), which extends `ConfigStore` with three key methods:
- `RegisterEventHandler(kind config.GroupVersionKind, handler EventHandler)` - Registers callbacks for config change events
- `Run(stop <-chan struct{})` - Starts the controller to watch and replicate config state
- `HasSynced() bool` - Indicates when initial sync is complete

**Implementation: Kubernetes CRD Controller**
The concrete implementation is `Client` in pilot/pkg/config/kube/crdclient/client.go:99, which:
- Watches Kubernetes CRDs using dynamic informers
- Maintains handlers map at client.go:82 mapping GroupVersionKind to EventHandler slices
- Dispatches events via AddFunc, UpdateFunc, DeleteFunc at client.go:388

**Event Queuing Mechanism**
Events flow through a worker queue pattern:
1. ConfigEvent is scheduled via monitor.ScheduleProcessEvent (pilot/pkg/config/memory/controller.go:94)
2. Events are processed by configStoreMonitor (pilot/pkg/config/memory/monitor.go:104)
3. Handlers are invoked with (old config, new config, Event) tuples (pilot/pkg/model/config.go:173)

**Event Handler Registration in Server**
The Pilot server registers event handlers during initialization (pilot/pkg/bootstrap/server.go:875):
- `initRegistryEventHandlers()` is called at server.go:362
- For each CRD schema, a configHandler is registered at server.go:919
- The handler creates a `PushRequest` and calls `s.XDSServer.ConfigUpdate(pushReq)` at server.go:901

**Aggregate Service Registry**
Multiple config sources are merged into a single logical store:
- `MakeWriteableCache()` in pilot/pkg/config/aggregate/config.go:63 creates an aggregate store
- Multiple `ConfigStoreController` instances are provided as caches
- The aggregate store queries each backend in order: if first store has a resource, it is used
- Event handlers are propagated to all backing controllers at config.go:191

### Key Flow

1. **Detection**: Kubernetes API server observes CRD changes
2. **Informer**: Dynamic informer delivers changes to CRD client
3. **Handler Dispatch**: Event handlers (registered via RegisterEventHandler) are invoked
4. **Push Trigger**: Event handler calls `DiscoveryServer.ConfigUpdate()` with a PushRequest
5. **Debounce**: PushRequest enters pushChannel (discovery.go:317) for debouncing
6. **Propagation**: Debounced requests are delivered to `handleUpdates()` which calls `Push()` after stabilization

---

## Q2: Internal Service Model

### Key Internal Model Types

**Service Type**
The `Service` struct (pilot/pkg/model/service.go:69) represents an Istio service with:
- `Hostname host.Name` - FQDN of the service (e.g., catalog.mystore.com)
- `Ports PortList` - Network ports where service listens
- `ClusterVIPs AddressMap` - Virtual IP in each cluster
- `DefaultAddress string` - Default service IP
- `ServiceAccounts []string` - Accounts running the service
- `Attributes ServiceAttributes` - Additional metadata for RBAC

**IstioEndpoint Type**
Represents a single workload instance (pilot/pkg/model/service.go:484):
- `Addresses []string` - Instance IP addresses
- `EndpointPort uint32` - Port where workload listens
- `ServicePortName string` - Name of the service port
- `Labels labels.Instance` - Workload labels (for subset matching)
- `LbWeight uint32` - Load balancing weight
- `TLSMode string` - mTLS mode for the endpoint

**EndpointShards**
Organizational structure for storing endpoints (pilot/pkg/model/endpointshards.go:57):
- Maps ShardKey → service name/namespace → IstioEndpoint list
- ShardKey includes cluster and network identity
- Allows efficient incremental push when endpoints in one shard change

### Service Conversion: Kubernetes to Internal Model

**Kubernetes Service**
When a Kubernetes Service is discovered:
1. KubernetesController (pilot/pkg/serviceregistry/kube/controller/controller.go) watches Service and EndpointSlice resources
2. For each Service, a model.Service is created with:
   - Hostname = service.name.namespace.svc.cluster.local
   - Ports extracted from service.spec.ports[]
   - ClusterVIP = service.spec.clusterIP
3. Endpoints come from EndpointSlice resources, converted to IstioEndpoint instances
4. The endpointSliceController (controller.go:40) maintains an endpointSliceCache to group endpoints by service
5. Updates trigger EDSUpdate() (pilot/pkg/xds/eds.go:47) which:
   - Updates EndpointIndex via UpdateServiceEndpoints()
   - Triggers a PushRequest for EDS (endpoint discovery)

**ServiceEntry**
ServiceEntry resources provide platform-independent service definitions (pilot/pkg/serviceregistry/serviceentry/conversion.go):
- Uses serviceentry.Controller to watch ServiceEntry and WorkloadEntry resources
- `serviceEntryHandler` registered at controller.go:157 processes ServiceEntry changes
- Conversion (conversion.go:364) transforms ServiceEntry to internal Service model:
  - Each host in ServiceEntry.hosts becomes a separate Service
  - Endpoints from ServiceEntry.endpoints or WorkloadSelector converted to IstioEndpoint
  - ServiceRegistry attribute set to provider.External
- For DNS-type ServiceEntry with no endpoints: hostnames are synthetic services without fixed endpoints

### PushContext: Configuration Snapshot

**Structure**
`PushContext` (pilot/pkg/model/push_context.go:206) is an immutable snapshot containing:

**Service Indexes**
- `ServiceIndex serviceIndex` (line 216) - Efficient service lookups
  - Indexes services by hostname, namespace, labels
  - Provides O(1) lookups for service discovery

**Resource Indexes**
- `virtualServiceIndex virtualServiceIndex` (line 222) - VirtualService lookup by host/namespace
- `destinationRuleIndex destinationRuleIndex` (line 225) - DestinationRule lookup
- `gatewayIndex gatewayIndex` (line 228) - Gateway resource index
- `sidecarIndex sidecarIndex` (line 234) - Sidecar policy index

**Policy & Config Storage**
- `AuthnPolicies *AuthenticationPolicies` (line 243) - Authentication policies by namespace
- `AuthzPolicies *AuthorizationPolicies` (line 247) - Authorization policies
- `Telemetry *Telemetries` (line 250) - Telemetry configurations
- `ProxyConfigs *ProxyConfigs` (line 253) - Proxy-specific configurations

**Push Metadata**
- `PushVersion string` (line 262) - Identifies this snapshot version
- `Mesh *meshconfig.MeshConfig` (line 259) - Global mesh configuration
- `ProxyStatus` (line 210) - Tracking push status per proxy

**Initialization**
`InitContext()` method (called in ads.go:85, delta.go:85, discovery.go:507) populates indexes:
- Scans config store for all VirtualServices, DestinationRules, Gateways
- Builds aggregated lookup tables
- Lock-free after initialization (all reads are concurrent-safe snapshots)

---

## Q3: xDS Generation and Dispatch

### Config Update Flow and Debouncing

**ConfigUpdate Entry Point**
`DiscoveryServer.ConfigUpdate()` (discovery.go:298) is called by event handlers with a PushRequest:
- Increments InboundUpdates counter (discovery.go:311)
- Pushes PushRequest into pushChannel (discovery.go:317)

**Debouncing Mechanism**
The `debounce()` function (discovery.go:330) implements smart batching:
- Maintains minQuiet time (DebounceAfter feature flag) before processing changes
- Enforces maxDelay (debounceMax flag) to prevent indefinite delays
- Merges rapid consecutive PushRequests into single push
- freeCh semaphore prevents concurrent pushes (line 342)

Push Worker Logic (discovery.go:351):
```
If (timeElapsed >= maxDelay) OR (quietTime >= minQuiet):
    Execute push via s.Push(req)
    Increment CommittedUpdates counter
Else:
    Schedule next check via time.After()
```

**Special Case: EDS-Only Updates**
When `enableEDSDebounce` is disabled and `Full` is false (discovery.go:387):
- EDS updates bypass debounce and push immediately
- Allows endpoint updates to reach proxies faster

### Push Execution and PushContext Creation

**Push Method Flow**
`DiscoveryServer.Push()` (discovery.go:436+) processes the PushRequest:

1. **Initialize PushContext**
   - `initPushContext(req)` (discovery.go:507) creates new PushContext snapshot
   - Scans config store for all resources
   - Builds indexes for services, virtual services, destination rules
   - Sets PushVersion based on push counter

2. **Per-Proxy Push**
   - Iterates over all connected proxies
   - For each proxy, creates a per-proxy PushContext copy
   - Computes proxy state: SidecarScope, gateway configuration, service targets
   - Calls `pushConnectionDelta()` or `pushConnection()` depending on protocol

3. **Push Event Coordination**
   - Each proxy push wrapped in Event struct (ads.go:98) with done callback
   - Callbacks tracked for observability and testing

### Generator Architecture and xDS Dispatch

**Generator Registration**
Generators are registered in DiscoveryServer.Generators map during bootstrap:
- Key format: `"typeURL"` or `"generator/typeURL"` or `"proxyType/typeURL"`
- Built-in generators (pilot/pkg/xds/v3/):
  - `"cds"` → CdsGenerator for Cluster Discovery Service
  - `"rds"` → RdsGenerator for Route Discovery Service
  - `"eds"` → EdsGenerator for Endpoint Discovery Service
  - `"lds"` → LdsGenerator for Listener Discovery Service

**Generator Lookup and Selection**
`findGenerator()` (xdsgen.go:67) selects appropriate generator with priority:
1. Check for generator-specific override: `Generator+"/"+ typeURL` (line 68)
2. Check for proxy-type-specific override: `ProxyType+"/"+ typeURL` (line 71)
3. Fall back to generic generator for typeURL (line 75)
4. Use proxy's XdsResourceGenerator if all else fails (line 81)
5. Default to "api" generator for unknown types (xdsgen.go:87)

**pushXds Execution**
`pushXds()` (xdsgen.go:96) generates and sends xDS response:
1. Calls `gen.Generate(proxy, watchedResource, pushRequest)` (line 120)
2. Generator returns:
   - model.Resources: array of xDS resources (Clusters, Routes, Endpoints, etc.)
   - model.XdsLogDetails: debug information about what was generated
3. Encodes resources in Delta or State-of-World format
4. Sends DiscoveryResponse back to proxy via gRPC stream

### CDS Generator Example
`CdsGenerator` (pilot/pkg/xds/cds.go:26):
- Calls `ConfigGenerator.BuildClusters(proxy, pushRequest)`
- Checks `cdsNeedsPush()` to determine if clusters changed
- Skips push for configs that don't impact CDS (Gateway, WorkloadEntry, AuthorizationPolicy, etc.)
- Returns cluster configurations (Envoy Cluster protobuf)

### RDS Generator Example
`RdsGenerator` (pilot/pkg/xds/rds.go:24):
- Calls `ConfigGenerator.BuildHTTPRoutes(proxy, pushRequest, resourceNames)`
- Only handles full pushes (line 48-51)
- Skips push for unrelated configs (WorkloadEntry, AuthorizationPolicy, etc.)
- Returns route configurations (Envoy RouteConfiguration protobuf)

---

## Q4: Resource Translation

### DestinationRule → Envoy Cluster (CDS)

**DestinationRule Processing**
When a DestinationRule is applied, it modifies Cluster configuration via `applyDestinationRule()` (pilot/pkg/networking/core/cluster_builder.go:219):

1. **Traffic Policy Application**
   - `applyTrafficPolicy()` (cluster_traffic_policy.go:43) applies settings to cluster:
   - Connection pool settings: max connections, max requests (line 45)
   - Load balancer: consistent hash, round-robin, etc.
   - Outlier detection: ejection thresholds
   - TLS/mTLS settings

2. **Subset Clusters**
   - For each subset in DestinationRule.subsets:
   - Creates subset-specific cluster named `<clusterName>|<subsetName>`
   - Subset labels (subset.labels) used to filter endpoints
   - Subset traffic policy merged with port-level and global policies (endpoint_builder.go:798)

3. **LoadBalancer & Outlier Detection**
   - DestinationRule.trafficPolicy.loadBalancer → Cluster.lbPolicy (Envoy LB algorithm)
   - DestinationRule.trafficPolicy.outlierDetection → Cluster.outlierDetection

**Example Flow**
```
DestinationRule:
  host: reviews
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 100
    outlierDetection:
      consecutiveErrors: 5

Result Cluster:
  name: "outbound|8080||reviews"
  connectTimeout: (from mesh config or defaults)
  maxRequests: 100
  outlierDetection: {...}
```

### VirtualService → Envoy Route (RDS)

**Route Configuration Building**
When VirtualService is processed, routes are built via `BuildHTTPRoutesForVirtualService()` (pilot/pkg/networking/core/route/route.go:377):

1. **HTTPRoute Generation**
   - For each `http[]` route in VirtualService:
   - Match conditions (uri, headers, etc.) → RouteMatch (line 645)
   - Route actions → destination clusters

2. **Destination Translation**
   - VirtualService.http[].route[].destination.host → target hostname
   - Destination.port → service port
   - Destination.subset → subset cluster key (if subset specified)
   - Destination.weight → weighted load balancing

3. **Route Actions**
   - Redirect rules, rewrite rules, timeouts
   - Retry policies
   - Request/response headers modifications
   - Fault injection (delays, aborts)

**Example Flow**
```
VirtualService:
  hosts:
  - reviews
  http:
  - match:
    - uri:
        prefix: "/v1"
    route:
    - destination:
        host: reviews
        subset: v1
      weight: 80
    - destination:
        host: reviews
        subset: v2
      weight: 20

Result RouteConfiguration:
  name: "10.0.0.1_8080"
  virtualHosts:
  - name: "reviews:8080"
    routes:
    - match: {prefix: "/v1"}
      route:
        weightedClusters:
        - name: "outbound|8080|v1|reviews"
          weight: 80
        - name: "outbound|8080|v2|reviews"
          weight: 20
```

### EDS Generation: ClusterLoadAssignment

**EndpointBuilder**
`EndpointBuilder` (pilot/pkg/xds/endpoints/endpoint_builder.go:60) constructs ClusterLoadAssignment via `BuildClusterLoadAssignment()`:

1. **Cluster Name Parsing**
   - Parses clusterName format: `"outbound|port|subset|hostname"`
   - Extracts traffic direction, subset, hostname, port

2. **Service & Destination Rule Lookup**
   - Finds Service by hostname via PushContext
   - Looks up DestinationRule for subset labels filtering
   - Applies traffic policy (load balancer, outlier detection)

3. **Endpoint Collection**
   - Queries EndpointIndex.GetEndpointShards() to fetch IstioEndpoint list
   - Filters endpoints by:
     - Subset labels: endpoint.Labels must match subset.labels from DestinationRule
     - Network locality: groups endpoints by geographic/network zones
     - TLS mode compatibility

4. **LocalityLbEndpoints Construction**
   - Groups endpoints by locality (zone, region, subzone)
   - Applies load balancing weights (from DestinationRule or endpoint metadata)
   - Constructs LbEndpoint for each endpoint with:
     - Address: IP and port
     - Weight: LoadBalancing.weight or health check weight
     - Metadata: zone info, canary status, etc.

**Example Flow**
```
Cluster: "outbound|8080|v1|reviews"
↓
EndpointBuilder parses: direction=Outbound, subset=v1, hostname=reviews, port=8080
↓
Find Service: reviews.default.svc.cluster.local
↓
Find DestinationRule: subset v1 has labels {version: v1}
↓
Query EndpointIndex: get all endpoints for reviews:8080 on ShardKey
↓
Filter: keep only endpoints where labels include {version: v1}
↓
Group by locality:
  - us-west/zone-a: [10.0.0.1:8080, 10.0.0.2:8080]
  - us-west/zone-b: [10.0.1.1:8080]
↓
Result ClusterLoadAssignment:
  clusterName: "outbound|8080|v1|reviews"
  endpoints:
  - locality: {region: "us-west", zone: "zone-a"}
    lbEndpoints:
    - endpoint: {address: "10.0.0.1", port: 8080}, weight: 1
    - endpoint: {address: "10.0.0.2", port: 8080}, weight: 1
  - locality: {region: "us-west", zone: "zone-b"}
    lbEndpoints:
    - endpoint: {address: "10.0.1.1", port: 8080}, weight: 1
```

---

## Evidence

### Core Files and References

**Configuration Ingestion:**
- pilot/pkg/model/config.go:188 - ConfigStoreController interface
- pilot/pkg/config/kube/crdclient/client.go:99 - Kubernetes CRD client implementation
- pilot/pkg/config/memory/controller.go:63 - RegisterEventHandler implementation
- pilot/pkg/config/aggregate/config.go:63 - MakeWriteableCache for config aggregation
- pilot/pkg/bootstrap/server.go:875 - initRegistryEventHandlers event handler setup

**Internal Model:**
- pilot/pkg/model/service.go:69 - Service type definition
- pilot/pkg/model/service.go:484 - IstioEndpoint type
- pilot/pkg/model/endpointshards.go:57 - EndpointShards organization
- pilot/pkg/model/push_context.go:206 - PushContext snapshot
- pilot/pkg/serviceregistry/serviceentry/conversion.go:364 - ServiceEntry to Service conversion
- pilot/pkg/serviceregistry/kube/controller/endpointslice.go:40 - Kubernetes endpoint slice handling

**xDS Generation and Dispatch:**
- pilot/pkg/xds/discovery.go:63 - DiscoveryServer struct
- pilot/pkg/xds/discovery.go:298 - ConfigUpdate entry point
- pilot/pkg/xds/discovery.go:330 - debounce function
- pilot/pkg/xds/xdsgen.go:67 - findGenerator selector
- pilot/pkg/xds/xdsgen.go:96 - pushXds execution
- pilot/pkg/xds/cds.go:26 - CdsGenerator
- pilot/pkg/xds/rds.go:24 - RdsGenerator
- pilot/pkg/xds/eds.go:47 - EDSUpdate triggering push

**Resource Translation:**
- pilot/pkg/networking/core/cluster_builder.go:219 - applyDestinationRule for CDS
- pilot/pkg/networking/core/cluster_traffic_policy.go:43 - applyTrafficPolicy
- pilot/pkg/networking/core/route/route.go:377 - BuildHTTPRoutesForVirtualService for RDS
- pilot/pkg/xds/endpoints/endpoint_builder.go:60 - EndpointBuilder for EDS
- pilot/pkg/xds/endpoints/endpoint_builder.go:798 - getSubsetTrafficPolicy for subset handling

### Key Architecture Patterns

1. **Event-Driven Updates**: Config changes trigger EventHandlers → PushRequests → debounced Push
2. **Snapshot-Based Generation**: PushContext is immutable snapshot enabling lock-free reads
3. **Generator Abstraction**: Pluggable generators allow custom xDS generation per proxy type
4. **Incremental Pushes**: EDS updates can skip debounce; other types require full push context
5. **Subset Filtering**: Endpoints filtered by subset labels from DestinationRule at push time
6. **Traffic Policy Merge**: Port-level > Subset > Global priority for DestinationRule settings
