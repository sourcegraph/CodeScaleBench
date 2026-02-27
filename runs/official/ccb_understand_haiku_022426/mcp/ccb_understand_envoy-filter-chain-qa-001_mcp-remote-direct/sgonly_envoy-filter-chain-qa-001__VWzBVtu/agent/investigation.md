# Envoy HTTP Filter Chain Architecture

## Q1: Listener to Connection Manager

When a downstream client opens a TCP connection to Envoy, the connection flows through the listener system to the HTTP connection manager using a layered filter architecture:

### Network Filter Chain Selection

**FilterChainManager** (`source/common/listener_manager/filter_chain_manager_impl.h:127-149`) selects which network filter chain to use for an incoming connection:

1. **Socket Creation** (`source/common/listener_manager/active_tcp_socket.h:28-36`): When a TCP connection arrives, `ActiveTcpSocket` is created to manage the accepted socket and apply listener filters (for inspection/preprocessing).

2. **Filter Chain Selection** (`source/common/listener_manager/filter_chain_manager_impl.h:148-149`): The `FilterChainManager::findFilterChain()` method uses connection socket properties (destination port, source IP, server name, TLS alpn, etc.) to select the matching network filter chain from a hierarchical tree structure (`DestinationPortsMap`, `ServerNamesMap`, `TransportProtocolsMap`, etc.).

3. **Network Filter Chain Installation** (`source/common/listener_manager/active_tcp_listener.cc:108-129`): Once listener filters complete, `ActiveTcpListener::onAcceptWorker()` creates an `ActiveTcpSocket` which continues through listener filter chain processing via `continueFilterChain()` (`source/common/listener_manager/active_tcp_socket.cc:111-160`). After listener filters pass, `newConnection()` is called.

### HTTP Connection Manager Installation

**ConnectionManagerImpl** (`source/common/http/conn_manager_impl.h:60-73`) is installed as the **first network filter** in the network filter chain:

- The HTTP connection manager implements `Network::ReadFilter` (line 61), making it a network filter.
- When the network connection is established, `ConnectionManagerImpl::onNewConnection()` is called (line 95).
- For HTTP/1 and HTTP/2, the codec is created lazily when `onData()` is first invoked (line 94).

### onData() Processing

`ConnectionManagerImpl::onData()` (`source/common/http/conn_manager_impl.cc:486-542`) handles incoming HTTP bytes:

1. **Codec Creation** (line 488-497): If the codec doesn't exist, it's created from the incoming data.
2. **Codec Dispatch** (line 503): Calls `codec_->dispatch(data)` which parses HTTP frames and invokes callbacks for headers, body, and metadata.
3. **Stream Creation**: When the codec parses request headers, it calls `ConnectionManagerImpl::newStream()` (line 102), which creates an `ActiveStream` containing a `DownstreamFilterManager`.

---

## Q2: HTTP Filter Chain Creation and Iteration

Once HTTP request headers are parsed, the HTTP filter chain is built and traversed through decoder and encoder filters:

### Filter Chain Creation

The HTTP filter chain is created **when request headers are processed**:

- **ActiveStream Creation** (`source/common/http/conn_manager_impl.h:141-532`): Each HTTP stream creates an `ActiveStream` struct which owns a `DownstreamFilterManager` (line 457).
- **Filter Chain Factory** (`source/common/http/filter_manager.h:681-683`): The `FilterManager` implements `FilterChainManager` and manages HTTP filters.
- **applyFilterFactoryCb** (`source/common/http/filter_manager.cc:520-521`): The `FilterManager::applyFilterFactoryCb()` method is called by the HTTP connection manager config to instantiate filters via `FilterChainFactoryCallbacksImpl`.
- **createDownstreamFilterChain** (`source/common/http/filter_manager.cc:1086-1087`): The filter chain is explicitly created after headers are received, instantiating all configured HTTP filters in order.

### Decoder Filter Chain Iteration

**Decoder filters** (`source/common/http/filter_manager.h:73-81`) iterate **forward through filters** in the order configured:

- **Headers**: `FilterManager::decodeHeaders()` (line 745-748) starts at the first filter and iterates forward.
- **Data**: `FilterManager::decodeData()` sends body bytes through filters in forward order.
- **Trailers**: `FilterManager::decodeTrailers()` sends trailers through filters in forward order.
- **Router Filter**: The terminal decoder filter is the `Router::Filter` (`source/common/router/router.h:52-150`), which does not pass further downstream.

**IterationState Control** (`source/common/http/filter_manager.h:175-179`):
- `FilterHeadersStatus::Continue` — filter processed, continue to next filter
- `FilterHeadersStatus::StopIteration` — filter wishes to stop, will call `continueDecoding()` later
- `FilterDataStatus::Continue` — filter processed data, continue
- `FilterDataStatus::StopIterationAndBuffer` — stop and buffer data in the filter
- Filters can inspect and modify headers/body via the `StreamDecoderFilter` interface (envoy/http/filter.h)

### Encoder Filter Chain Iteration

**Encoder filters** (`source/common/http/filter_manager.h:92-100`) iterate **in reverse order** (last filter to first):

- Uses `reverse_iterator` to traverse from C → B → A (line 94-97).
- This allows filters to progressively unwrap the response as it flows back.
- Response headers/body/trailers flow through encoder filters in reverse of decoder order.

**Return Values** for encoder filters:
- `FilterHeadersStatus::Continue` — encoder processed, continue to previous filter
- `FilterHeadersStatus::StopIteration` — stop and resume via `continueEncoding()`

### Filter Chain Structure

```
Decoder Chain (forward):  A → B → C (Router)
Encoder Chain (reverse):  C → B → A
```

---

## Q3: Router and Upstream

The router filter forwards requests to upstream servers and manages the response path:

### Router Filter (Terminal Decoder Filter)

`Router::Filter` (`source/common/router/router.h:52+`) is the last filter in the decoder chain:

1. **Route Selection**: `decodeHeaders()` selects the target cluster and route based on request headers via the scoped route configuration.
2. **Upstream Host Selection**: Uses the `ClusterManager` to select a specific upstream host via load balancer.
3. **UpstreamRequest Creation** (`source/common/router/upstream_request.h:66-123`): Creates an `UpstreamRequest` object to manage communication with the upstream server.

### UpstreamRequest and Upstream Connection Pool

**UpstreamRequest** (`source/common/router/upstream_request.h:66-200`) encapsulates upstream request handling:

- Obtains a connection from the connection pool: `conn_pool_->newStream()` returns a `GenericUpstream` (line 195-198).
- **onPoolReady** (line 119-122): Called when the connection pool has allocated an upstream connection, providing the upstream host and connection.
- **acceptHeadersFromRouter** (line 80): Router passes request headers to the upstream request, which forwards them via the upstream filter chain.
- **acceptDataFromRouter** (line 81): Body data is passed through the upstream filter chain and sent to upstream.

### Upstream Filter Chain

**UpstreamFilterManager** and **UpstreamCodecFilter** (`source/common/router/upstream_request.h:38-39`, `source/common/router/upstream_codec_filter.h`):

- The `UpstreamCodecFilter` is the last filter in the upstream filter chain (like the router is the last in downstream).
- **Codec Bridge** (`source/common/router/upstream_codec_filter.cc:147-148`): When upstream response headers arrive via the HTTP codec, they're passed to `CodecBridge::decodeHeaders()` which invokes the upstream filter chain.
- The `UpstreamCodecFilter::decodeHeaders()` takes response headers and passes them to `UpstreamRequest::decodeHeaders()`.

### Response Flow Back to Downstream

**UpstreamRequest::decodeHeaders()** (`source/common/router/upstream_request.cc:267-269`):
- Called when response headers arrive from upstream via the codec.
- Passes response headers back to the `RouterFilterInterface` via `parent_.onUpstreamHeaders()`.
- The router filter then invokes `sendHeaders()` on the downstream stream, passing response headers to the **encoder filter chain**.

**Encoder Filter Chain Processing** (`source/common/http/filter_manager.h:750+`):
- Response headers flow through encoder filters in **reverse order** (C → B → A).
- Each encoder filter can modify or inspect the response.
- Finally, the HTTP codec encodes the response and sends it back to the downstream client.

---

## Q4: Architectural Boundaries

Envoy maintains two distinct "filter chain" concepts at different layers:

### Network-Level Filter Chain (FilterChainManager)

**FilterChainManager** (`envoy/network/filter.h:184-189`, `source/common/listener_manager/filter_chain_manager_impl.h:127-149`):

- **Scope**: Network layer, below HTTP.
- **Filters**: Network filters like TLS, proxy protocol, connection draining, the **HTTP connection manager itself** (first network filter).
- **Selection**: Uses connection socket metadata (destination port, source IP, TLS SNI, application protocol) to select which filter chain to install.
- **Lifecycle**: Attached to the network connection; exists for the lifetime of the TCP/QUIC connection.
- **Management**: Owned by `ListenerConfig` and managed by `FilterChainManagerImpl`.

### HTTP-Level Filter Chain (FilterManager)

**FilterManager** (`source/common/http/filter_manager.h:681-683`, `source/common/http/conn_manager_impl.h:457`):

- **Scope**: HTTP layer, above network.
- **Filters**: HTTP filters (router, auth, compression, etc.) which process HTTP semantics.
- **Selection**: Instantiated **per HTTP stream** by the HTTP connection manager via the filter factory.
- **Lifecycle**: Exists only for the lifetime of a single HTTP request/response pair.
- **Management**: Owned by `DownstreamFilterManager` (owned by `ActiveStream`), managed by the HTTP connection manager.

### Why They Are Separate

1. **Protocol Independence**: Network filters operate regardless of HTTP version (H/1, H/2, H/3); HTTP filters are HTTP-specific.
2. **Multiplexing**: HTTP/2 and HTTP/3 multiplex multiple HTTP streams over a single network connection. Each stream has its own HTTP filter chain but shares the network filter chain.
3. **Connection vs. Request Scope**: Network filters handle connection-level concerns (TLS, proxy protocol); HTTP filters handle request-level concerns (routing, transformation).
4. **Different Selection Criteria**: Network filter chains are selected based on socket properties once at connection time; HTTP filters are uniform for all streams on the connection.

### Relationship and Data Flow

```
TCP Connection arrives
       ↓
Network Filter Chain (FilterChainManager selects)
    - TLS Filter
    - HTTP Connection Manager (first network filter)
       ↓
       For each HTTP request on this connection:
       ↓
    HTTP Filter Chain (FilterManager instantiates per request)
       - Auth Filter
       - Router Filter
       - etc.
       ↓
    Response flows back through encoder filters
       ↓
    HTTP Connection Manager encodes and sends to network
```

---

## Evidence

### Key Files and References

**Q1: Listener to Connection Manager**
- `source/common/listener_manager/filter_chain_manager_impl.h:127-149` — FilterChainManager interface and implementation
- `source/common/listener_manager/active_tcp_socket.h:28-36` — ActiveTcpSocket creation
- `source/common/listener_manager/active_tcp_socket.cc:111-160` — Listener filter chain processing
- `source/common/listener_manager/active_tcp_listener.cc:108-129` — onAcceptWorker creates ActiveTcpSocket
- `source/common/http/conn_manager_impl.h:60-73` — ConnectionManagerImpl as Network::ReadFilter
- `source/common/http/conn_manager_impl.h:94-95` — onData() and onNewConnection()
- `source/common/http/conn_manager_impl.cc:486-542` — onData() implementation: codec dispatch

**Q2: HTTP Filter Chain Creation and Iteration**
- `source/common/http/filter_manager.h:73-100` — StreamDecoderFilters and StreamEncoderFilters
- `source/common/http/filter_manager.h:681-683` — FilterManager class
- `source/common/http/filter_manager.cc:520-521` — applyFilterFactoryCb()
- `source/common/http/filter_manager.cc:1086-1087` — createDownstreamFilterChain()
- `source/common/http/filter_manager.h:745-748` — decodeHeaders()
- `source/common/http/filter_manager.h:175-179` — IterationState and canIterate()
- `source/common/http/filter_manager.cc:50-100` — commonContinue() and filter iteration logic

**Q3: Router and Upstream**
- `source/common/router/router.h:52-150` — FilterConfig and router implementation
- `source/common/router/upstream_request.h:66-200` — UpstreamRequest class
- `source/common/router/upstream_request.h:80-82` — acceptHeadersFromRouter, acceptDataFromRouter
- `source/common/router/upstream_request.h:119-122` — onPoolReady
- `source/common/router/upstream_request.cc:267-269` — decodeHeaders (upstream response)
- `source/common/router/upstream_codec_filter.cc:147-148` — CodecBridge::decodeHeaders()
- `source/common/http/conn_manager_impl.h:141-532` — ActiveStream with DownstreamFilterManager

**Q4: Architectural Boundaries**
- `envoy/network/filter.h:184-189` — Network::FilterChainManager interface
- `source/common/listener_manager/filter_chain_manager_impl.h:127-149` — FilterChainManager implementation
- `source/common/http/filter_manager.h:681-683` — Http::FilterManager (HTTP-level)
- `source/common/http/conn_manager_impl.h:60-73` — ConnectionManagerImpl as bridge between layers
- `source/common/http/conn_manager_impl.h:457` — DownstreamFilterManager member of ActiveStream
