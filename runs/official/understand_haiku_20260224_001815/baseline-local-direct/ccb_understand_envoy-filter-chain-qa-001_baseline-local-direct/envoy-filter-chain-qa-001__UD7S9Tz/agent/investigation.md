# Envoy HTTP Filter Chain Architecture

## Q1: Listener to Connection Manager

### Network Filter Chain Selection

When a downstream client opens a TCP connection, Envoy uses a multi-layer selection mechanism:

1. **Connection Arrival**: A new socket connection arrives at the listener (source/common/listener_manager/active_stream_listener_base.cc:38-75, method `newConnection()`).

2. **Filter Chain Matching**: The listener calls `findFilterChain()` on the `FilterChainManager` to determine which network filter chain to use:
   - File: `source/common/listener_manager/filter_chain_manager_impl.h:148-149`
   - Method: `const Network::FilterChain* findFilterChain(const Network::ConnectionSocket& socket, const StreamInfo::StreamInfo& info) const;`
   - The selection is based on destination IP/port, server name (SNI), transport protocol, application protocols (ALPN), and source IP/port matching (source/common/listener_manager/filter_chain_manager_impl.h:174-295).

3. **Network Filter Instantiation**: Once a filter chain is found (source/common/listener_manager/active_stream_listener_base.cc:68-69):
   ```
   const bool empty_filter_chain = !config_->filterChainFactory().createNetworkFilterChain(
       *server_conn_ptr, filter_chain->networkFilterFactories());
   ```
   The network filter factories are instantiated and installed on the connection.

4. **HTTP Connection Manager Installation**: The HTTP connection manager (`ConnectionManagerImpl`) is installed as one of the network filters via the network filter chain (source/common/http/conn_manager_impl.h:60-64):
   - It implements `Network::ReadFilter` interface
   - Method: `Network::FilterStatus onData(Buffer::Instance& data, bool end_stream) override;` (line 94)

### onData() Processing

When the first bytes arrive on a TCP connection (source/common/http/conn_manager_impl.cc:486-536):

1. **Codec Creation**: If the codec hasn't been created yet, `createCodec()` is called to instantiate the appropriate HTTP codec (HTTP/1.1, HTTP/2, or HTTP/3).

2. **Codec Dispatch**: The connection manager calls `codec_->dispatch(data)` which parses incoming HTTP frames and invokes callbacks when complete messages are received.

3. **Stream Creation**: When HTTP headers are fully parsed, the codec calls `newStream()` on the connection manager (source/common/http/conn_manager_impl.cc:387-441):
   - An `ActiveStream` is created
   - The stream is registered with the connection
   - A response encoder is associated with the stream

4. **Headers Decoding**: The codec invokes the request decoder, which calls `decodeHeaders()` on the `ActiveStream` (source/common/http/conn_manager_impl.cc:1193-1447).

---

## Q2: HTTP Filter Chain Creation and Iteration

### Filter Chain Creation Point

The HTTP filter chain is created **lazily after route matching**, not immediately when headers arrive:

**File**: `source/common/http/conn_manager_impl.cc:1402-1403`
```cpp
const FilterManager::CreateChainResult create_chain_result =
    filter_manager_.createDownstreamFilterChain();
```

This occurs in `ActiveStream::decodeHeaders()` **after** the route has been determined via:
- `refreshCachedRoute()` at line 1392
- Validation of request headers
- All pre-filter setup (XFF handling, tracing setup, etc.)

**File**: `source/common/http/filter_manager.cc:1661-1703` - `FilterManager::createFilterChain()`

The filter chain creation:
1. Creates `StreamDecoderFilters` and `StreamEncoderFilters` containers (filter_manager.h:73-100)
2. Calls the `FilterChainFactory` callback which instantiates each filter
3. Each filter is wrapped in `ActiveStreamDecoderFilter` or `ActiveStreamEncoderFilter` objects
4. Stores iterators to allow bidirectional navigation during filter chain iteration

### Filter Order and Iteration

**Decoder Filters** (source/common/http/filter_manager.h:66-81):
- Configured filter order: A, B, C
- Iteration order: **A → B → C** (forward iteration)
- Invoked when request headers/data/trailers arrive
- Method: `filter_manager_.decodeHeaders()` at line 1439

**Encoder Filters** (source/common/http/filter_manager.h:83-100):
- Configured filter order: A, B, C
- Iteration order: **C → B → A** (reverse iteration)
- Invoked when response headers/data/trailers are generated
- Uses `reverse_iterator` for backward iteration

### Filter Control: Return Values

**File**: `source/common/http/filter_manager.h:174-222` - Iteration state management

Filters control iteration using return statuses:

1. **`FilterHeadersStatus::Continue`**: Continue to next filter
2. **`FilterHeadersStatus::StopIteration`**: Stop current iteration, wait for callback to resume
3. **`FilterHeadersStatus::StopAllIteration`**: Stop all iterations and buffer all data
4. **`FilterHeadersStatus::ContinueAndDontEndStream`**: Continue but consume the end_stream flag

Iteration state enum (source/common/http/filter_manager.h:211-218):
```cpp
enum class IterationState : uint8_t {
    Continue,            // Iteration has not stopped
    StopSingleIteration, // Stopped for headers, 100-continue, or data
    StopAllBuffer,       // Stopped for all frame types, buffer data
    StopAllWatermark,    // Stopped for all, buffer until high watermark
};
```

**File**: `source/common/http/filter_manager.cc:537-621` - `decodeHeaders()` iteration

The decoder iterates through `decoder_filters_` (a vector of `ActiveStreamDecoderFilterPtr`), calling `decodeHeaders()` on each filter and handling the return status via `commonHandleAfterHeadersCallback()` (line 577).

---

## Q3: Router and Upstream

### Router Filter Selection

The router filter is the **terminal HTTP decoder filter** (it performs routing, not filtering):

**File**: `source/common/router/router.h:308-320` - `class Filter`
- Implements `Http::StreamDecoderFilter`
- Located as the final filter in the HTTP filter chain

### Route Matching and Cluster Selection

**File**: `source/common/router/router.cc:445-530` - `Filter::decodeHeaders()`

1. **Route Lookup**: `route_ = callbacks_->route();` (line 468)
   - Looks up the route from the route config (set in filter_manager during header validation)
   - If no route: sends 404, returns `StopIteration`

2. **Route Entry**: `route_entry_ = route_->routeEntry();` (line 506)
   - Contains the destination cluster name and routing configuration

3. **Cluster Lookup**:
   ```cpp
   Upstream::ThreadLocalCluster* cluster =
       config_->cm_.getThreadLocalCluster(route_entry_->clusterName());
   ```
   (line 518-519)
   - Resolves the cluster name to an actual cluster

### UpstreamRequest Creation

**File**: `source/common/router/router.cc:845-849`

```cpp
UpstreamRequestPtr upstream_request = std::make_unique<UpstreamRequest>(
    *this, std::move(generic_conn_pool), can_send_early_data, can_use_http3,
    allow_multiplexed_upstream_half_close_);
LinkedList::moveIntoList(std::move(upstream_request), upstream_requests_);
upstream_requests_.front()->acceptHeadersFromRouter(end_stream);
```

The router:
1. Selects an upstream connection pool via `getConnPool()` (which selects a host via load balancing)
2. Creates an `UpstreamRequest` object with the pool
3. Passes the request headers/data to the upstream request via `acceptHeadersFromRouter()`

### UpstreamRequest: Request Encoding and Response Decoding

**File**: `source/common/router/upstream_request.h:41-65`

The `UpstreamRequest` handles bidirectional communication:

1. **Request Path** (downstream → upstream):
   - Receives request headers/data/trailers via `acceptHeadersFromRouter()`, `acceptDataFromRouter()`, `acceptTrailersFromRouter()`
   - Passes through an upstream filter chain (file: filter_manager.h for upstream variant)
   - Final filter (`UpstreamCodecFilter`) encodes HTTP frames to the upstream server

2. **Response Path** (upstream → downstream):
   - Receives HTTP response frames from the upstream codec
   - Passes through the upstream filter chain for decoding
   - Calls `RouterFilterInterface::onUpstream1xxHeaders()`, `onUpstreamHeaders()`, etc.
   - These methods call back to the router filter's `StreamEncoderFilterCallbacks` to encode the response downstream

**File**: `source/common/router/upstream_request.h:90-97`
```cpp
// Http::StreamDecoder
void decodeData(Buffer::Instance& data, bool end_stream) override;
void decodeMetadata(Http::MetadataMapPtr&& metadata_map) override;

// UpstreamToDownstream (Http::ResponseDecoder)
void decode1xxHeaders(Http::ResponseHeaderMapPtr&& headers) override;
void decodeHeaders(Http::ResponseHeaderMapPtr&& headers, bool end_stream) override;
void decodeTrailers(Http::ResponseTrailerMapPtr&& trailers) override;
```

### Response Flow Back Through Filter Chain

Once the router receives upstream response headers:

1. Router filter encodes the response via `callbacks_->encodeHeaders()` (which are the decoder filter's callback methods)
2. The response is passed back through **encoder filters in reverse order** (C → B → A)
3. Each encoder filter can modify the response
4. Final encoder filter passes the response to the `ConnectionManagerImpl`
5. Response is encoded to the downstream client via the HTTP codec

---

## Q4: Architectural Boundaries

### Two Distinct Filter Chain Concepts

Envoy has two separate filter chain abstractions that operate at different layers:

#### Network-Level Filter Chain (ConnectionHandler)

**Managed by**: `FilterChainManagerImpl` (source/common/listener_manager/filter_chain_manager_impl.h:127-334)

**Purpose**: Select and instantiate network-layer filters based on connection properties

**Key Files**:
- `source/common/listener_manager/filter_chain_manager_impl.h`
- `source/common/listener_manager/active_stream_listener_base.cc:41` (findFilterChain call)

**Scope**:
- Operates at TCP/TLS connection level
- Selected once per connection based on:
  - Destination IP and port
  - Source IP and port
  - Server name (SNI from TLS)
  - Transport protocol (TCP, UDP)
  - Application protocols (ALPN)
- Factory method: `filterChainFactory().createNetworkFilterChain()` (active_stream_listener_base.cc:68)

**Filters Installed**:
- HTTP Connection Manager (`ConnectionManagerImpl`)
- TLS transport socket
- Listener filters (executed before this)
- Other network-level filters (compression, monitoring, etc.)

**Lifecycle**: One per TCP connection, selected at connection acceptance time

#### HTTP-Level Filter Chain (FilterManager)

**Managed by**: `FilterManager` / `DownstreamFilterManager` (source/common/http/filter_manager.h:681-896)

**Purpose**: Process HTTP-layer request/response through application logic filters

**Key Files**:
- `source/common/http/filter_manager.h`
- `source/common/http/filter_manager.cc:1661-1703` (createFilterChain)
- `source/common/http/conn_manager_impl.cc:1402-1403` (creation point)

**Scope**:
- Operates at HTTP message level (headers/body/trailers)
- Created **per HTTP request** (not per connection)
- Created **after route matching** (in `ActiveStream::decodeHeaders()`)
- Factory method: `filter_chain_factory.createFilterChain()` via `FilterChainFactory` callback

**Filters Installed**:
- Router filter (terminal filter for routing decisions)
- Application-level filters (lua, rate limit, auth, cache, etc.)
- Custom extension filters

**Lifecycle**: One per HTTP request stream, created lazily when first request headers arrive

### Why They Are Separate

**Separation of Concerns**:
1. **Network layer filters** handle connection-level concerns (TLS, protocol selection, raw data handling)
2. **HTTP filters** handle message-level concerns (routing, request transformation, response generation)

**Selection Timing**:
- Network chain: Selected at TCP accept (immediate, based on network properties)
- HTTP chain: Selected at first HTTP headers (delayed, after protocol negotiation and route matching)

**Reusability**:
- A single network filter chain can handle multiple HTTP requests
- Different routes can have different HTTP filter configurations (via route-specific filter configs in source/common/http/filter_manager.h:162-164)

**Efficiency**:
- Network filters instantiated once per connection
- HTTP filters instantiated per request (allows per-request customization)
- Connection pooling benefits from stable network filter chain

### Relationship Between the Two

**Flow**:
1. TCP connection arrives → Network filter chain selected (`FilterChainManagerImpl`)
2. HTTP Connection Manager installed as network filter
3. HTTP headers parsed by codec → First HTTP stream created
4. HTTP filter chain created after route matching (`FilterManager`)
5. HTTP filters process the request
6. Response encoded and sent back through HTTP encoder chain
7. Response written to downstream connection via HTTP codec (network layer)

**Data Flow**:
```
TCP Socket → [Network Filter Chain] → HTTP Connection Manager
                                            ↓
                                      HTTP Codec (H1/H2/H3)
                                            ↓
                                    [HTTP Filter Chain]
                                     (decoder filters)
                                            ↓
                                    Router Filter (selects upstream)
                                            ↓
                                    Upstream Connection
```

---

## Evidence

### Critical File References

#### Listener and Network Filter Chain
- `source/common/listener_manager/connection_handler_impl.h:40-72` - Listener addition and network filter chain installation
- `source/common/listener_manager/filter_chain_manager_impl.h:148-149` - Filter chain selection interface
- `source/common/listener_manager/active_stream_listener_base.cc:38-76` - Connection acceptance and filter chain application
- `source/common/listener_manager/filter_chain_manager_impl.h:86-122` - FilterChainImpl with network filter factories

#### HTTP Connection Manager
- `source/common/http/conn_manager_impl.h:60-96` - HTTP CM as network filter with onData()
- `source/common/http/conn_manager_impl.cc:486-536` - onData() codec creation and dispatch
- `source/common/http/conn_manager_impl.cc:387-441` - newStream() creates ActiveStream
- `source/common/http/conn_manager_impl.cc:1193-1447` - decodeHeaders() validates and routes

#### HTTP Filter Chain
- `source/common/http/filter_manager.h:66-100` - Decoder and encoder filter chain structures
- `source/common/http/filter_manager.h:681-896` - FilterManager main class
- `source/common/http/filter_manager.h:211-235` - Iteration state management
- `source/common/http/filter_manager.cc:1661-1703` - createFilterChain() instantiation
- `source/common/http/filter_manager.cc:537-621` - decodeHeaders() iteration through filters
- `source/common/http/conn_manager_impl.cc:1402-1403` - Filter chain creation trigger point

#### Router Filter
- `source/common/router/router.h:308-456` - Router::Filter class (terminal decoder filter)
- `source/common/router/router.cc:445-530` - decodeHeaders() route matching and cluster selection
- `source/common/router/router.cc:830-849` - UpstreamRequest creation and initiation
- `source/common/router/upstream_request.h:66-97` - UpstreamRequest interface

#### Return Values and Control Flow
- `source/common/http/filter_manager.h:174-222` - IterationState and canIterate()/stoppedAll()
- `source/common/http/filter_manager.h:240-330` - ActiveStreamDecoderFilter and return status handling
- `source/common/http/filter_manager.cc:520-523` - applyFilterFactoryCb() for individual filter creation

### Key Observations

1. **Network Filter Chain** is immutable after selection (line 68-69 of active_stream_listener_base.cc)
2. **HTTP Filter Chain** creation is deferred until after route is determined (line 1403 of conn_manager_impl.cc)
3. **Decoder filters** iterate forward; **encoder filters** iterate backward (filter_manager.h:73-100)
4. **Router filter** is the terminal decoder filter that doesn't return StopIteration for normal requests
5. **UpstreamRequest** manages bidirectional request/response with upstream (upstream_request.h:41-65)
