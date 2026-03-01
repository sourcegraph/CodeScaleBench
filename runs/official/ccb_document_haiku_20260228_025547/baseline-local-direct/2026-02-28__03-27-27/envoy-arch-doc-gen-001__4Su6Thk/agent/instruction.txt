# Architecture Document: Envoy HTTP Connection Manager

**Repository:** envoyproxy/envoy
**Output:** Write your document to `/workspace/documentation.md`

## Task

Produce an architecture document for Envoy's **HTTP Connection Manager** (HCM) subsystem. The document must explain how the major components interact to process an HTTP request from arrival on a downstream connection through to upstream dispatch. Do not simply list APIs — explain the **design**, **data flow**, and **extension points**.

## Scope

Your document must cover these four components and how they work together:

### 1. ConnectionManagerImpl
The central network filter that owns the connection lifecycle. Explain:
- How it implements `Network::ReadFilter` to receive raw bytes
- How it creates and manages `ActiveStream` objects for each HTTP request
- Its role in codec creation (lazy codec instantiation for H1/H2 vs. H3)
- Connection-level concerns: drain decisions, overload management, watermark-based flow control

### 2. FilterManager and the HTTP Filter Chain
The per-stream filter chain execution engine. Explain:
- The decoder filter chain (request path) and encoder filter chain (response path)
- How `FilterChainFactory` creates filters for each stream
- Filter iteration: how `decodeHeaders`/`decodeData`/`decodeTrailers` propagate through decoder filters
- How filters can stop iteration, modify headers, or send local replies
- The distinction between `StreamDecoderFilter`, `StreamEncoderFilter`, and `StreamFilter` (dual)

### 3. Router Filter
The terminal decoder filter that forwards requests upstream. Explain:
- Route selection: how the router uses `RouteConfiguration` to pick a cluster
- How it obtains an HTTP connection pool from `ClusterManager`
- Upstream request lifecycle: `UpstreamRequest` creation, retry logic, timeout handling
- Shadow routing and hedged request support (if applicable)

### 4. Cluster Manager and Upstream Connectivity
The upstream connection pool and cluster management layer. Explain:
- How `ClusterManagerImpl` provides connection pools per cluster
- Load balancing: how the router obtains a host from the cluster's load balancer
- Connection pool mechanics: the relationship between logical connection pools and physical connections
- How health checking and outlier detection feed back into the load balancer

## Document Requirements

1. **Component Responsibilities** — what each component owns
2. **Data Flow** — the path of an HTTP request from downstream bytes to upstream dispatch, and the response path back
3. **Extension Points** — where users extend Envoy (HTTP filters, cluster extensions, load balancers, access loggers)
4. **Error Handling** — how errors at each stage (codec errors, filter errors, upstream failures) are handled
5. **relevant source files** — reference the actual source files in the envoyproxy/envoy repository

## Anti-Requirements

- Do NOT generate a simple API listing or header-file dump
- Do NOT fabricate class names or file paths that don't exist in the repository
- Do NOT cover Envoy components outside the HCM request path (e.g., xDS config delivery, listener management)
