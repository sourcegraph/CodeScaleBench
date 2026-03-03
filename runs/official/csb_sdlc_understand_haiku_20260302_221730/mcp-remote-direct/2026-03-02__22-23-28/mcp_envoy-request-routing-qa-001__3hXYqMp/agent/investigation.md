# Envoy Request Routing Flow

This document traces the complete path of a single HTTP request through Envoy from TCP accept through upstream connection establishment.

## Q1: Listener Accept to Network Filter Chain

### Socket Accept
When a downstream TCP connection arrives at Envoy, the flow begins at the Network Listener level:

1. **TCP Socket Accepted** (`source/common/listener_manager/active_listener_base.h`)
   - The listener's accept callback receives a new `Network::ConnectionSocket`
   - The socket is passed to `onAcceptWorker()` which creates an `ActiveTcpSocket` wrapper

2. **ActiveTcpSocket Creation** (`source/common/listener_manager/active_tcp_socket.cc:11-21`)
   - Constructor initializes the socket and creates stream info
   - Increments `downstream_pre_cx_active_` stat (line 20)
   - Iterator positioned at `accept_filters_.end()`
   - A timeout timer may be started for listener filters

3. **Listener Filter Chain Iteration** (`source/common/listener_manager/active_tcp_socket.cc:111-173`)
   - `continueFilterChain(bool success)` iterates through listener filters
   - For each filter: `(*iter_)->onAccept(*this)` is called
   - Filter can return `StopIteration` to wait for data or asynchronous events
   - If filter returns `Continue`, iteration proceeds to next filter
   - When filter returns `StopIteration` and `maxReadBytes() > 0`, a `ListenerFilterBuffer` is created (line 135)
     - This buffer polls the socket for incoming data via `onData()` callbacks
     - File events are activated to trigger reads: `listener_filter_buffer_->activateFileEvent(Event::FileReadyType::Read)` (line 150)

4. **Listener Filter Buffer** (`source/common/listener_manager/active_tcp_socket.cc:73-108`)
   - `createListenerFilterBuffer()` wraps the socket's IO handle
   - Registers an `onData` callback that calls the current filter's `onData(ListenerFilterBuffer&)` method
   - When listener filter data processing completes or socket closes, `continueFilterChain(false)` or `continueFilterChain(true)` is called

5. **All Listener Filters Pass** (`source/common/listener_manager/active_tcp_socket.cc:160-162`)
   - When iteration completes without early exit, `newConnection()` is called
   - This is the gateway to the actual server connection establishment

### Handoff to Network Filter Chain

6. **Create Server Connection** (`source/common/listener_manager/active_stream_listener_base.cc:38-76`)
   - `ActiveStreamListenerBase::newConnection()` is invoked with the socket and stream info
   - **Filter Chain Selection**: `findFilterChain(*socket, *stream_info)` (line 41)
     - Calls `config_->filterChainManager().findFilterChain()` to match the connection against configured filter chains
     - Returns the matching `Network::FilterChain` or nullptr if no match
   - **Transport Socket Creation**: `filter_chain->transportSocketFactory().createDownstreamTransportSocket()` (line 58)
     - Creates TLS/crypto layer if configured
   - **Server Connection Creation**: `dispatcher().createServerConnection()` (lines 59-60)
     - Network layer creates the actual server-side connection object
     - Connection wraps the socket and applies transport socket layer
   - **Network Filter Chain Creation**: `createNetworkFilterChain(*server_conn_ptr, filter_chain->networkFilterFactories())` (lines 68-69)
     - Instantiates all network filters (including HTTP Connection Manager) on the connection
     - Filters are created in order and added to the connection's filter chain
   - **Active Connection Tracking**: `newActiveConnection(*filter_chain, std::move(server_conn_ptr), ...)` (line 75)
     - Stores the connection in active connection tracking

### Key Component Boundaries
- **Listener Filters**: Work with raw sockets, may inspect/modify connection before HTTP
- **Network Filters**: Work with connections, see all bytes/frames
- **HTTP Connection Manager**: First network filter that understands HTTP protocol

---

## Q2: HTTP Parsing and Filter Chain Iteration

### Codec Creation and HTTP Parsing

1. **First Data Arrival** (`source/common/http/conn_manager_impl.cc:486-542`)
   - `ConnectionManagerImpl::onData(Buffer::Instance& data, bool)` is invoked when socket has readable data
   - If codec doesn't exist yet, `createCodec(data)` is called (line 496)
   - Codec is lazily created on first data arrival (for HTTP/1 and HTTP/2)

2. **Codec Instantiation** (`source/common/http/conn_manager_impl.cc:465-483`)
   - `config_->createCodec(read_callbacks_->connection(), data, *this, ...)` creates protocol-specific codec
   - For HTTP/1: `Http1ServerConnectionImpl` with `ConnectionManagerImpl` as `ServerConnectionCallbacks`
   - For HTTP/2: `ConnectionImpl` with same callback interface
   - Codec type determined from magic bytes/protocol negotiation

3. **Dispatch and Parsing** (`source/common/http/conn_manager_impl.cc:503`)
   - `codec_->dispatch(data)` processes the buffer
   - Codec parses HTTP headers, body, trailers from the byte stream
   - For each complete request headers, codec invokes: `callbacks_->newStream(response_encoder)`

### ActiveStream Creation

4. **Stream Creation Callback** (`source/common/http/conn_manager_impl.cc:390-442`)
   - Codec calls `newStreamImpl(ResponseEncoder& response_encoder, ...)` (implicitly through callback)
   - This creates a new `ActiveStream` (line 407):
     ```cpp
     auto new_stream = std::make_unique<ActiveStream>(
         *this, response_encoder.getStream().bufferLimit(), downstream_stream_account);
     ```
   - Stream is added to `streams_` list (line 440): `LinkedList::moveIntoList(std::move(new_stream), streams_);`
   - Returns reference to the new stream: `return **streams_.begin();`

5. **ActiveStream Structure** (`source/common/http/conn_manager_impl.h:141-150`)
   - Implements multiple interfaces:
     - `RequestDecoder` (receives headers, data, trailers from codec)
     - `FilterManagerCallbacks` (receives filter chain callbacks)
     - `StreamCallbacks` (connection events)
     - `CodecEventCallbacks` (codec state changes)

### Filter Manager and Filter Chain Iteration

6. **Filter Manager Initialization** (`source/common/http/filter_manager.h`)
   - `FilterManager` is created with the stream
   - Maintains `decoder_filters_` list (HTTP request processing filters)
   - Maintains `encoder_filters_` list (HTTP response processing filters)

7. **Decoder Filter Iteration** (`source/common/http/filter_manager.cc:933-1050`)
   - `decodeHeaders()` calls `commonDecodePrefix()` to start iteration (line 936)
   - Iterates through `decoder_filters_` vector:
     ```cpp
     for (auto& filter : decoder_filters_) {
         status = filter->decodeHeaders(headers, end_stream);
         if (status == FilterHeadersStatus::StopIteration) break;
     }
     ```
   - Each filter's return value controls iteration:
     - `Continue` → move to next filter
     - `StopIteration` → stop, filter will call `continueDecoding()` later
     - `StopAllIteration` → stop entire filter chain
   - If filter modifies headers, all downstream filters see modified headers

8. **Key Filter: Router Filter** (`source/common/router/router.cc:445-704`)
   - Router filter's `decodeHeaders()` (line 445) is typically the last decoder filter
   - Returns `StopIteration` after initiating upstream request (does not continue to more filters)
   - Instead, creates upstream request and manages response flow

---

## Q3: Route Resolution and Upstream Selection

### Route Matching

1. **Route Resolution** (`source/common/router/router.cc:468`)
   - `route_ = callbacks_->route()` - invokes RDS/route matching
   - Actual matching happens in `Router::RouteConfig::findRoute(headers, ...)`
   - Scoped route config is snapped first via `snapScopedRouteConfig()`
   - Route selection considers:
     - HTTP method, path, authority from headers
     - Virtual host match
     - Route entry match within virtual host

2. **Route Entry Extraction** (`source/common/router/router.cc:506`)
   - `route_entry_ = route_->routeEntry()` gets the matched route entry
   - Route entry contains: cluster name, timeouts, retries, weighted clusters, etc.

### Cluster and Host Selection

3. **Get Cluster from Thread Local Storage** (`source/common/router/router.cc:518-530`)
   - `Upstream::ThreadLocalCluster* cluster = config_->cm_.getThreadLocalCluster(route_entry_->clusterName())` (line 519)
   - Returns thread-local view of cluster including current set of healthy hosts
   - Cluster name comes from route entry configuration

4. **Upstream Host Selection** (`source/common/router/router.cc:664`)
   - `auto host_selection_response = cluster->chooseHost(this)` (line 664)
   - `chooseHost()` uses load balancing algorithm to select a specific upstream host:
     - Round-robin, least request, ring hash, random, etc. based on cluster configuration
     - Filter state may influence selection (metadata match criteria, etc.)
     - Returns `HostConstSharedPtr` to specific upstream instance
   - Selection may be asynchronous (line 665-703):
     - If asynchronous, `host_selection_response.cancelable` is returned
     - Callback `on_host_selected_` registered to continue when host is selected
     - Returns `StopAllIterationAndWatermark` to pause decoding

### Connection Pool Creation

5. **Continuous Decode Headers** (`source/common/router/router.cc:714-902`)
   - Either called directly (sync) or via callback (async) with selected host
   - `continueDecodeHeaders()` is called with:
     - `cluster`: the `ThreadLocalCluster`
     - `selected_host`: the chosen `HostConstSharedPtr`

6. **Connection Pool Creation** (`source/common/router/router.cc:905-948`)
   - `std::unique_ptr<GenericConnPool> generic_conn_pool = createConnPool(*cluster, selected_host)` (line 724)
   - `createConnPool()` implementation (line 905-948):
     - Gets upstream protocol (HTTP/TCP/UDP) from route config
     - Gets `GenericConnPoolFactory` from cluster or default
     - Calls `factory->createGenericConnPool(host, cluster, protocol, priority, ...)` (line 946)
     - Returns the constructed connection pool

7. **Connection Pool Characteristics**:
   - Connection pool maintains connections to a specific host
   - For HTTP: `HttpConnPoolImplBase` (HTTP/1 or HTTP/2)
   - Manages connection reuse, multiplexing limits, health checks
   - When `newStream()` called on pool, it either:
     - Attaches stream to existing ready connection
     - Creates new connection if needed and queues request
     - Queues request if all connections busy

---

## Q4: Upstream Connection and Data Flow

### Upstream Connection Establishment

1. **Connection Pool newStream Request** (`source/common/http/conn_pool_base.cc:59-63`)
   - Router calls `generic_conn_pool->newStream(response_decoder, callbacks, options)`
   - Creates a `PendingStream` and enqueues it (line 77: `newPendingStream()`)
   - If ready connection exists, attaches stream immediately
   - Otherwise, may trigger new connection creation (line 164: `tryCreateNewConnection()`)

2. **ActiveClient Creation** (`source/common/http/conn_pool_base.cc:164-201`)
   - `tryCreateNewConnection()` calls `instantiateActiveClient()` to create `ActiveClient`
   - For HTTP/1: Creates `Http1::ActiveClient`
   - For HTTP/2: Creates `Http2::ActiveClient`
   - Each `ActiveClient` owns one upstream TCP connection

3. **Network Connection Creation** (`source/common/http/conn_pool_base.h:52-55`)
   - `host->createConnection(dispatcher, options, transport_socket_options)` (line 171: `host_->canCreateConnection()` check)
   - Returns `CreateConnectionData` with:
     - `connection_`: The actual `Network::ClientConnection`
     - `host_description_`: The upstream host information
   - Connection is in connecting state, connection timer started

4. **Codec Client Wrapping** (`source/common/http/conn_pool_base.cc:92`)
   - `CodecClient` (HTTP codec wrapper) is created from the network connection
   - For HTTP/1: `CodecClientProd` with `Http1::ClientConnectionImpl`
   - For HTTP/2: `CodecClientProd` with `Http2::ConnectionImpl`
   - Codec client handles HTTP request/response encoding/decoding

5. **Connection Ready**
   - Network connection events (`Connected`, `Timeout`, `RemoteClose`) trigger `onConnected()` / `onConnectFailed()`
   - When connected, pending streams are attached to connection
   - `onPoolReady()` callback is invoked (line 181: `ConnPoolImpl::onPoolReady()`)

### Request Forwarding

6. **UpstreamRequest Creation** (`source/common/router/upstream_request.cc`)
   - `UpstreamRequest` is created per upstream attempt
   - Implements `GenericUpstream` and `Http::StreamDecoderFilterCallbacks`
   - Manages per-stream timeouts, retries, response processing

7. **Request Header Writing** (`source/common/router/router.cc:800-900`)
   - In `continueDecodeHeaders()`, after connection pool ready:
   - `generic_conn_pool->newStream()` returns connection attachment
   - `UpstreamRequest::acceptHeadersFromRouter()` encodes headers to upstream:
     - `request_encoder_->encodeHeaders(headers, end_stream)` (line 823)
     - Codec serializes HTTP headers into wire format
     - Writes to upstream socket

8. **Request Body Forwarding** (`source/common/router/router.cc:960-1040`)
   - `decodeData()` from downstream is forwarded upstream:
   - `upstream_requests_.front()->acceptDataFromRouter(data, end_stream)` (line 1010/1022)
   - `request_encoder_->encodeData(data, end_stream)` writes to upstream

### Response Flow (Reverse Path)

9. **Upstream Response Reception**
   - Upstream codec client receives bytes on connection
   - Upstream codec parses HTTP response: `codec_->dispatch(data)`
   - For each response header frame: calls `response_decoder_->decodeHeaders(headers, end_stream)`
   - Response decoder is the `UpstreamRequest`

10. **Response to Encoder Filter Chain** (`source/common/router/upstream_request.cc`)
    - `UpstreamRequest::decodeHeaders()` invokes encoder filter chain
    - Encoder filters process response headers in order (inverse of decoder filters)
    - Response passes through encoder filters: compression, modification, etc.

11. **Response to Downstream Codec**
    - Final response headers/data/trailers encoded to downstream via:
    - `ActiveStream::encodeHeaders()` → `response_encoder_->encodeHeaders()`
    - Downstream codec serializes to downstream socket

### State and Timing

12. **Stream State Management** (`source/common/http/conn_manager_impl.h:344-383`)
    - `ActiveStream::state_` tracks codec and processing state:
      - `codec_saw_local_complete_`: Response fully sent to codec
      - `codec_encode_complete_`: Codec finished encoding response
      - `on_reset_stream_called_`: Stream was reset
    - Stream can be destroyed once `canDestroyStream()` is true (line 385)

13. **Cleanup and Logging**
    - `ActiveStream::completeRequest()` finalizes stream
    - Access logs are generated via `log(AccessLog::AccessLogType)`
    - Stream is removed from `streams_` list
    - Upstream host is released back to connection pool

---

## Evidence

### File References by Component

**Network Layer (TCP Accept)**
- `source/common/listener_manager/active_listener_base.h` - Listener base class
- `source/common/listener_manager/active_tcp_socket.h:11-36` - ActiveTcpSocket constructor, socket management
- `source/common/listener_manager/active_tcp_socket.cc:111-173` - continueFilterChain() filter iteration logic
- `source/common/listener_manager/active_tcp_socket.cc:73-108` - createListenerFilterBuffer() listener filter buffer management
- `source/common/listener_manager/active_tcp_socket.cc:185-222` - newConnection() handoff to server connection
- `source/common/listener_manager/active_stream_listener_base.h:22-76` - ActiveStreamListenerBase class, newConnection interface
- `source/common/listener_manager/active_stream_listener_base.cc:38-76` - newConnection() filter chain selection, transport socket, server connection, network filter chain creation

**HTTP Parsing and ActiveStream**
- `source/common/http/conn_manager_impl.h:60-72` - ConnectionManagerImpl network filter interface
- `source/common/http/conn_manager_impl.h:137-150` - ActiveStream struct definition
- `source/common/http/conn_manager_impl.cc:465-483` - createCodec() codec creation
- `source/common/http/conn_manager_impl.cc:486-542` - onData() codec dispatch
- `source/common/http/conn_manager_impl.cc:390-442` - newStreamImpl() ActiveStream creation and filter chain setup
- `source/common/http/filter_manager.h:72-77` - StreamDecoderFilters, decoder filter chain
- `source/common/http/filter_manager.cc:933-1050` - Filter iteration logic

**Router Filter and Route Selection**
- `source/common/router/router.h:46-347` - Filter class, decodeHeaders interface
- `source/common/router/router.cc:445-704` - Filter::decodeHeaders() route resolution, host selection
  - Line 468: route resolution
  - Line 506: route entry extraction
  - Line 519: cluster selection
  - Line 664: host selection via chooseHost()
- `source/common/router/router.cc:714-902` - continueDecodeHeaders() connection pool creation
- `source/common/router/router.cc:905-948` - createConnPool() connection pool instantiation

**Upstream Connection Pool**
- `source/common/http/conn_pool_base.h:52-90` - HttpConnPoolImplBase connection pool class
- `source/common/http/conn_pool_base.cc:59-63` - newStream() pending stream creation
- `source/common/http/conn_pool_base.cc:162-201` - tryCreateNewConnection() new connection creation
- `source/common/tcp/conn_pool.cc:176-194` - TCP ActiveClient instantiation

**UpstreamRequest and Response**
- `source/common/router/upstream_request.h:264-340` - UpstreamRequest class definition
- `source/common/router/upstream_request.cc:44-120` - Request encoding, data forwarding
- `source/extensions/upstreams/http/http/upstream_request.cc:28-40` - HTTP upstream stream creation

**Key Interfaces**
- `envoy/network/listener.h` - Network listener and connection acceptance
- `envoy/http/codec.h` - HTTP codec interface
- `envoy/http/filter.h` - HTTP filter interfaces (decoder/encoder)
- `envoy/http/conn_pool.h` - HTTP connection pool interface
- `envoy/upstream/upstream.h` - Cluster and host interfaces
