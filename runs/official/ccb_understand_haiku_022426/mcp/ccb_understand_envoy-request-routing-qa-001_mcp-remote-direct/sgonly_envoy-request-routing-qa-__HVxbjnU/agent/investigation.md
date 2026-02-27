# Envoy Request Routing Flow

This document traces the complete path of a single HTTP request from the moment a downstream client TCP connection is accepted through filter chain processing, route resolution, upstream cluster selection, and connection establishment.

## Q1: Listener Accept to Network Filter Chain

### TCP Socket Accept

When a downstream client establishes a TCP connection to Envoy, the following occurs:

**Entry Point: TcpListenerImpl (source/common/network/tcp_listener_impl.cc)**
- The kernel delivers accepted sockets to `TcpListenerImpl::onAccept()`
- `TcpListenerImpl` is a `Network::ReadFilter` that wraps the raw socket accept mechanism
- When the kernel triggers the accept event, the listener calls its callback with the accepted socket

**Connection Handler Routing: ActiveTcpListener (source/common/listener_manager/active_tcp_listener.cc:80)**
- `ActiveTcpListener::onAccept(Network::ConnectionSocketPtr&& socket)` receives the accepted socket
- Line 90: Calls `onAcceptWorker()` which optionally rebalances connections across worker threads
- Line 126-127: Creates `ActiveTcpSocket` object to track the socket during listener filter processing
- Line 129: Calls `onSocketAccepted()` to process listener filters

### Listener Filter Chain Processing

**Listener Filters: ActiveTcpSocket (source/common/listener_manager/active_tcp_socket.cc:111-173)**
- Listener filters iterate through accept filters via `continueFilterChain()`
- Each listener filter's `onAccept()` is called (line 121) to inspect/modify the socket before protocol determination
- Listener filters can stop iteration (e.g., for protocol detection like SNI/ALPN)
- When all listener filters complete: Line 220 calls `listener_.newConnection(std::move(socket), ...)`

### Network Filter Chain Creation

**Filter Chain Selection & Network Filter Creation: ActiveStreamListenerBase (source/common/listener_manager/active_stream_listener_base.cc:38-76)**
- `newConnection()` finds the matching filter chain (line 41)
- Creates a `ServerConnection` (transport socket layer) - line 59
- **Critical:** Calls `createNetworkFilterChain()` (line 68) which instantiates network filters
- The **HTTP Connection Manager (HCM)** is a network filter that processes HTTP on this connection
- Line 75: Calls `newActiveConnection()` to track the established connection

### HTTP Connection Manager Activation

**HTTP Connection Manager: ConnectionManagerImpl (source/common/http/conn_manager_impl.h:60-64)**
- `ConnectionManagerImpl` is a `Network::ReadFilter` that implements `onData()` callback
- When bytes arrive on the downstream connection, the network layer calls `onData(Buffer::Instance& data, bool end_stream)`
- The HCM uses lazy codec creation: first `onData()` call at line 496 of conn_manager_impl.cc creates the appropriate codec (HTTP/1.1 or HTTP/2)

**Data Reception Trigger: Network::ReadFilter::onData()**
- Once the ServerConnection is established, the event loop registers a read interest
- When downstream bytes arrive on the socket, they're buffered and `ConnectionManagerImpl::onData()` is invoked

---

## Q2: HTTP Parsing and Filter Chain Iteration

### HTTP Codec Initialization and Parsing

**Codec Creation: ConnectionManagerImpl::createCodec() (source/common/http/conn_manager_impl.cc:465-484)**
- Line 467: Calls `config_->createCodec()` which instantiates the appropriate codec
- For HTTP/1.1: `Http1::CodecImpl` (source/common/http/http1/codec_impl.h)
- For HTTP/2: `Http2::CodecImpl` (source/common/http/http2/codec_impl.h)
- The codec is passed `*this` (ConnectionManagerImpl) as the `ServerConnectionCallbacks`

**HTTP Byte Stream Parsing: ConnectionManagerImpl::onData() (source/common/http/conn_manager_impl.cc:486-542)**
- Line 503: Calls `codec_->dispatch(data)` which parses the byte buffer
- The codec's `dispatch()` method:
  - Parses HTTP/1.1 request line + headers or HTTP/2 headers frame
  - Extracts headers into `RequestHeaderMapSharedPtr`
  - When headers are complete, invokes callback: `ServerConnectionCallbacks::newStream(ResponseEncoder&, bool)`

### New Stream Creation and ActiveStream

**Stream Creation: ConnectionManagerImpl::newStream() (source/common/http/conn_manager_impl.cc:387-442)**
- Called by codec when request headers are parsed
- Line 407-408: Creates `ActiveStream` object with a `FilterManager`
- Line 431-432: Stores the response encoder and registers callbacks
- Line 441: Returns the `RequestDecoder` (which is the ActiveStream)
- The codec now has a reference to the stream for receiving decoded headers/data/trailers

**Header Decoding: ActiveStream::decodeHeaders() (source/common/http/conn_manager_impl.cc:1193-1447)**
- Called by codec when HTTP request headers are complete
- Lines 1227-1230: Validates headers
- Lines 1233-1244: Snapshots the route configuration
- Line 1401: Sets request headers in StreamInfo
- Line 1403: **Critical:** Calls `filter_manager_.createDownstreamFilterChain()` to instantiate HTTP filters
- Line 1439: Calls `filter_manager_.decodeHeaders(*request_headers_, end_stream)` to start filter iteration

### HTTP Filter Chain Iteration

**Filter Chain Creation: FilterManager::createDownstreamFilterChain()**
- Invokes filter factory callbacks to instantiate HTTP filters
- Typically instantiates: authentication filters → authorization filters → ... → router filter
- Filters are stored in order in `decoder_filters_` vector

**Header Decoding Through Filters: FilterManager::decodeHeaders() (source/common/http/filter_manager.cc:537-631)**
- Line 541: Determines the starting filter iterator
- Line 547: Iterates through decoder filters in order
- **Line 555:** Calls `(*entry)->decodeHeaders(headers, end_stream)` on each filter
  - Each filter's `decodeHeaders()` returns a `FilterHeadersStatus`:
    - `Continue`: Pass to next filter
    - `StopIteration`: Don't call next filter (but allow more data/trailers)
    - `StopAll`: Stop all iteration (e.g., filter sent local reply)
- Filters can modify headers, buffer data, or send local replies
- Router filter is typically the last decoder filter and doesn't return `Continue` (instead creates upstream request)

**Filter Return Value Processing:**
- Line 577: Calls `commonHandleAfterHeadersCallback()` to process the filter's return value
- If filter sent local reply via `sendLocalReply()`: iteration stops, response goes downstream
- If filter returned `StopIteration`: downstream continues receiving data but other filters pause
- If filter returned `Continue` and not terminal: continues to next filter
- If filter is terminal (e.g., router) and returned `Continue`: filter chain complete

---

## Q3: Route Resolution and Upstream Selection

### Route Lookup

**Route Retrieval: Filter::decodeHeaders() (source/common/router/router.cc:445-476)**
- Line 468: Calls `callbacks_->route()` to get the route
- Route lookup involves:
  - Virtual host matching (based on :authority header)
  - Route entry matching (based on path + methods from config)
  - Route configuration is snapped at stream creation time (Q2, line 1235)
- Line 469-476: If no route found, sends 404 and stops iteration

**Route Entry Analysis:**
- Line 480-503: Checks for direct responses (immediate HTTP responses without upstream)
- Line 506: Retrieves `route_entry_` which contains the destination cluster name

### Cluster Resolution

**Cluster Selection: Filter::decodeHeaders() (source/common/router/router.cc:518-530)**
- Line 519: Calls `config_->cm_.getThreadLocalCluster(route_entry_->clusterName())`
- The cluster manager maintains a mapping of cluster names to cluster objects
- Cluster object contains:
  - Upstream hosts (endpoints)
  - Load balancing policy
  - Connection pool factory
  - Health checking configuration

### Host Selection

**Load Balanced Host Selection: Filter::decodeHeaders() (source/common/router/router.cc:664)**
- Line 664: Calls `cluster->chooseHost(this)`
- The filter passes itself as `LoadBalancerContext` providing:
  - Metadata matching criteria (line 379-403)
  - Hash key for consistent hashing (line 363-378)
  - Priority load information (line 421-431)
  - Retry context (lines 410-418, 433-438)
- Load balancer selects specific upstream host based on algorithm:
  - Round-robin, least request, ring hash, random, etc.
- Host selection can be:
  - Synchronous (line 673): host returned immediately
  - Asynchronous (line 683-702): callback registered for later completion

**Host Selection Response:**
- Returns `HostSelectionResponse` containing:
  - `host`: Selected upstream host (IP, port, metadata)
  - `details`: Human-readable selection details
  - `cancelable`: Optional handle to cancel async selection

### Connection Pool Creation

**Pool Lookup/Creation: Filter::continueDecodeHeaders() (source/common/router/router.cc:724)**
- Line 724: Calls `createConnPool(*cluster, selected_host)`
- Connection pool is looked up or created based on:
  - Cluster ID
  - Selected host address
  - Protocol (HTTP/1.1, HTTP/2, HTTP/3)
  - TLS configuration
- If no healthy connection pool can be created: sends upstream error response (line 726)

---

## Q4: Upstream Connection and Data Flow

### Connection Pool Operation

**Connection Pool Types:**
- HTTP/1.1: One connection per stream (request/response pair)
- HTTP/2: Multiplexed streams on single connection
- HTTP/3: QUIC-based multiplexing
- Pool manages: connection lifecycle, stream allocation, flow control

**Pool Selection:** (source/common/http/conn_pool_base.h, conn_pool_grid.h)
- Connection pool provides a `newStream()` method
- Takes request encoder callbacks (`GenericConnectionPoolCallbacks`)
- Returns immediately or through callback if connection available

### Upstream Request Creation

**UpstreamRequest Initialization: Filter::continueDecodeHeaders() continuation**
- After connection pool obtained:
  - Creates `UpstreamRequest` object to manage the upstream stream
  - Registers callbacks with the pool for connection events
  - Pool selects/creates upstream connection
  - Calls connection's `newStream()` to get an upstream request encoder

**Upstream Connection Establishment:**
- If pool already has healthy connection: reuses existing connection
- If pool needs new connection:
  - Gets cluster's connection factory
  - Creates TCP socket to selected host (IP + port)
  - Performs TLS handshake (if configured)
  - Sends HTTP/2 preface or HTTP/1.1 initial headers
- Connection stored in pool for potential future reuse

### Request Encoding and Transmission

**Upstream Request Headers:** (source/common/router/upstream_request.h/cc)
- Headers are modified (route rewrites, appended headers, removed headers)
- Request encoder encodes headers into wire format
- For HTTP/1.1: `VERB /path HTTP/1.1\r\nHeaders\r\n\r\n`
- For HTTP/2: HEADERS frame on stream ID
- Encoded bytes written to upstream socket's send buffer

**Upstream Request Body:**
- Downstream filter chain continues processing data frames
- Router filter passes data downstream to encoder
- Encoder writes data frames to upstream socket
- Flow control: respects upstream window limits, backpressures downstream

**Upstream Trailers:**
- After request body complete, trailers forwarded to upstream encoder
- Transmitted as additional header block (HTTP/2) or chunk trailer (HTTP/1.1)

### Response Flow (Reverse Direction)

**Upstream Response Reception:**
- Upstream connection reads response bytes from socket
- HTTP codec parses response headers, data, trailers
- Triggers `ClientConnectionCallbacks::onNewStream()` (upstreamCallbacks on UpstreamRequest)

**Upstream Response Decoding:**
- Response headers parsed and passed to `UpstreamRequest::decodeHeaders()`
- UpstreamRequest creates upstream filter manager with encoder filter chain
- **Line 265-327 of upstream_request.h:** Implements `FilterManagerCallbacks`
- Passes response through upstream encoder filters (reverse of decoder filters)
- Upstream filters can modify response headers/body before sending downstream

**Downstream Response Encoding:**
- After upstream filters process response:
  - Response encoder (stored in UpstreamRequest) encodes response
  - Calls downstream response encoder via `response_encoder_->encodeHeaders()` etc.
  - Response headers/body/trailers transmitted to downstream socket in wire format

**Encoder Filter Chain Invocation:**
- **After upstream processing complete:**
  - Downstream encoder filter chain invoked (reverse order of decoder chain)
  - Example: router filter → authentication filter
  - Encoder filters can modify response before sending to client
  - Final encoded bytes written to downstream socket

### Connection Lifecycle Management

**Upstream Connection Reuse:**
- After stream complete:
  - If connection supports keep-alive: connection returned to pool for reuse
  - Pool maintains connection state and limits
  - Connection reused for next request to same host
  - If connection lost/unhealthy: created anew

**Downstream Connection Management:**
- HTTP/1.1: May close if response has `Connection: close` or max requests reached
- HTTP/2: Multiplexed streams managed independently
- Connection stays open until explicitly closed or idle timeout

---

## Evidence

### File References

**Q1 - Listener Accept to Network Filter Chain**
- `source/common/network/tcp_listener_impl.h:17-26` - TcpListenerImpl class
- `source/common/network/tcp_listener_impl.cc:60-126` - onAccept and listener callback loop
- `source/common/listener_manager/active_tcp_listener.h:32-82` - ActiveTcpListener lifecycle
- `source/common/listener_manager/active_tcp_listener.cc:80-130` - onAccept to socket creation
- `source/common/listener_manager/active_tcp_socket.h:33-103` - ActiveTcpSocket with listener filters
- `source/common/listener_manager/active_tcp_socket.cc:111-223` - Listener filter iteration
- `source/common/listener_manager/active_stream_listener_base.cc:38-76` - newConnection with filter chain
- `source/common/http/conn_manager_impl.h:60-96` - ConnectionManagerImpl as Network::ReadFilter
- `source/common/http/conn_manager_impl.cc:148-199` - initializeReadFilterCallbacks

**Q2 - HTTP Parsing and Filter Chain Iteration**
- `source/common/http/conn_manager_impl.cc:465-484` - createCodec
- `source/common/http/conn_manager_impl.cc:486-542` - onData calls codec_->dispatch
- `source/common/http/conn_manager_impl.h:622-635` (envoy/http/codec.h) - ServerConnectionCallbacks::newStream
- `source/common/http/conn_manager_impl.cc:387-442` - ConnectionManagerImpl::newStream creates ActiveStream
- `source/common/http/conn_manager_impl.cc:1193-1447` - ActiveStream::decodeHeaders with filter chain creation
- `source/common/http/filter_manager.h:71-112` - FilterManager and decoder filter structures
- `source/common/http/filter_manager.cc:537-631` - FilterManager::decodeHeaders filter iteration

**Q3 - Route Resolution and Upstream Selection**
- `source/common/router/router.h:308-456` - Router Filter class definition
- `source/common/router/router.cc:444-476` - Filter::decodeHeaders route lookup
- `source/common/router/router.cc:505-539` - Route entry and cluster resolution
- `source/common/router/router.cc:664-704` - Host selection synchronous and asynchronous
- `source/common/router/router.cc:714-758` - continueDecodeHeaders with connection pool creation

**Q4 - Upstream Connection and Data Flow**
- `source/common/http/conn_pool_base.h` - Connection pool interface
- `source/common/router/upstream_request.h:33-430` - UpstreamRequest managing upstream stream
- `source/common/router/upstream_request.cc:45-300` - Upstream request encoding/decoding
- `source/common/router/upstream_request.h:265-327` - FilterManagerCallbacks for upstream filters
- `envoy/http/filter.h:622-654` - ServerConnectionCallbacks and ClientConnection interfaces

### Key Data Structures

- **Connection**: `Network::ServerConnection` - downstream TCP+TLS
- **Codec**: `Http::ServerConnection` - HTTP protocol parser/encoder
- **Stream**: `ConnectionManagerImpl::ActiveStream` - downstream HTTP stream
- **FilterManager**: `Http::FilterManager` - filter chain executor
- **Route**: `Router::Route` - route matching result
- **Cluster**: `Upstream::ThreadLocalCluster` - upstream cluster info
- **Host**: `Upstream::HostConstSharedPtr` - specific upstream endpoint
- **ConnPool**: `Http::GenericConnPool` - manages upstream connections
- **UpstreamRequest**: `Router::UpstreamRequest` - upstream HTTP stream

