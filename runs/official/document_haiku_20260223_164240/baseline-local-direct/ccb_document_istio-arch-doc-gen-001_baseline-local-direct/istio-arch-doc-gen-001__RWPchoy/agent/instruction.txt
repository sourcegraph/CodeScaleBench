# Architecture Document: Istio Pilot Discovery Service

**Repository:** istio/istio
**Output:** Write your document to `/workspace/documentation.md`

## Task

Produce an architecture document for **Istio Pilot's Discovery Service** subsystem. The document must explain how Pilot serves xDS (Envoy Discovery Service) configuration to proxies, translates Istio's high-level configuration into Envoy-specific resources, integrates with service registries, and supports multi-cluster deployments. Do not simply list APIs — explain the **design**, **data flow**, and **extension points**.

## Scope

Your document must cover these four components and how they work together:

### 1. DiscoveryServer — The xDS gRPC Server
The central component implementing Pilot's gRPC interface for Envoy's xDS APIs. Explain:
- How it implements Envoy's xDS v3 protocol (ADS, incremental/state-of-the-world modes)
- The role of `adsClients` in tracking active proxy connections
- How configuration pushes are coordinated: debouncing, rate limiting, concurrent push limits
- Cache management for xDS resources (CDS, LDS, RDS, EDS)
- The lifecycle: initialization, handling new connections, shutdown

### 2. ADS and the Connection Model
The Aggregated Discovery Service stream handler. Explain:
- How `Stream()` establishes a bidirectional gRPC stream with an Envoy proxy
- The `Connection` type: wrapping the stream with proxy metadata and state
- Request processing: how `processRequest()` determines what configuration to send
- Push coordination: how `pushConnection()` transmits updates to a single proxy
- The `StartPush()` broadcast mechanism for fleet-wide updates

### 3. PushContext — Configuration Snapshot and Translation
The immutable configuration snapshot used during a push. Explain:
- What `PushContext` holds: services, destination rules, virtual services, sidecars, gateways
- How `InitContext()` rebuilds the push context when Istio config changes (CRD watches)
- Config translation: how Pilot converts Istio's `VirtualService` and `DestinationRule` into Envoy's `RouteConfiguration` and `Cluster` resources
- The relationship between push triggers (config changes, service registry updates) and push context regeneration
- Metrics and error tracking during push generation

### 4. Service Registry and Multi-Cluster Support
The service discovery layer feeding the DiscoveryServer. Explain:
- How `ServiceRegistry` (Kubernetes controller) watches K8s Services, Endpoints, and Pods
- The aggregate controller pattern for multi-registry support (K8s services + `ServiceEntry` resources)
- Multi-cluster support: how Pilot aggregates services from multiple clusters
- How endpoint updates (pod scale-up, health changes) trigger EDS pushes
- The relationship between the service registry and xDS: when does a service change trigger CDS vs. EDS?

## Document Requirements

1. **Component Responsibilities** — what each component owns
2. **Data Flow** — the path from Istio config change → DiscoveryServer → xDS push to Envoy proxies
3. **Extension Points** — where users extend Istio (custom config translation, external service registries, telemetry plugins)
4. **Error Handling** — how errors at each stage (config validation, push failures, proxy disconnects) are handled
5. **relevant source files** — reference the actual source files in the istio/istio repository (e.g., `pilot/pkg/xds/discovery.go`, `pilot/pkg/model/push_context.go`)

## Anti-Requirements

- Do NOT generate a simple API listing or struct dump
- Do NOT fabricate type names or file paths that don't exist in the repository
- Do NOT cover Istio components outside the Pilot discovery path (e.g., Citadel, Galley, sidecar injection)
