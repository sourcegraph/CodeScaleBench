# Envoy Request Routing Flow

## Q1: Listener Accept to Network Filter Chain

### Which component accepts the incoming TCP connection?

The **TcpListenerCallbacks interface** (`/workspace/envoy/network/listener.h:310-335`) defines the callback for TCP socket acceptance. The **ActiveTcpListener** class (`/workspace/source/common/listener_manager/active_tcp_listener.h:25-99`) implements this interface and is the primary component that accepts incoming TCP connections through its `onAccept(Network::ConnectionSocketPtr&& socket)` method (line 54).

When a socket accepts a connection, the event loop calls `TcpListener::onAccept()`, which delegates to `ActiveTcpListener::onAccept()` (`/workspace/source/common/listener_manager/active_tcp_listener.cc:80-91`). This method:
1. Checks listener connection limits
2. Calls `onAcceptWorker(socket, config_->handOffRestoredDestinationConnections(), false)` (line 91)

### How does Envoy select which network filter chain to apply based on connection properties?

The network filter chain selection occurs after listener filters complete, in the **ActiveStreamListenerBase::newConnection()** method (`/workspace/source/common/listener_manager/active_stream_listener_base.cc:38-76`). This method calls:

```cpp
config_->filterChainManager().findFilterChain(*socket, *stream_info)
```

The **FilterChainManager::findFilterChain()** method (`/workspace/source/common/listener_manager/filter_chain_manager_impl.h:148-149`) uses connection properties to select the appropriate filter chain:
- Destination port/IP address
- Server name (SNI for TLS connections)
- Transport protocol
- Application protocols
- Source IPs and ports
- Connection source type (from proxy protocol, etc.)

### At what point does the connection get handed to the HTTP Connection Manager (HCM)?

The handoff occurs during network filter chain creation in **ListenerImpl::createNetworkFilterChain()** (`/workspace/source/common/listener_manager/listener_impl.cc:942-952`). This method calls:

```cpp
Configuration::FilterChainUtility::buildFilterChain(connection, filter_factories)
```

The filter factories list contains the HTTP Connection Manager factory. The **HttpConnectionManagerFilterConfigFactory::createFilterFactoryFromProtoTyped()** (`/workspace/source/extensions/filters/network/http_connection_manager/config.cc`) creates a filter factory callback that instantiates the HTTP Connection Manager network filter. Once instantiated, the HCM becomes a **Network::ReadFilter** on the connection and receives all subsequent data.

### What triggers the initial onData() call when bytes arrive?

Once the connection is fully established with all network filters instantiated, the underlying **Network::Connection** object's read event loop triggers when bytes arrive from the TCP socket. The network event dispatcher calls the registered **Network::ReadFilter::onData(Buffer::Instance& data, bool end_stream)** method on each filter in the filter chain.

For the HTTP Connection Manager, this triggers **ConnectionManagerImpl::onData()** (`/workspace/source/common/http/conn_manager_impl.cc:486-542`). This is the entry point where raw TCP bytes are handed to the HTTP parsing layer.

---

## Q2: HTTP Parsing and Filter Chain Iteration

### How does the codec parse the byte stream into HTTP headers/body?

The HTTP codec is created lazily in **ConnectionManagerImpl::onData()** (line 496 of `conn_manager_impl.cc`) on first data arrival via:
```cpp
codec_ = config_->createCodec(connection_, data, *this, overload_manager_)
```

The codec factory creates either:
- **Http1::ServerConnectionImpl** (`/workspace/source/common/http/http1/codec_impl.h:465-583`) for HTTP/1.1
- **Http2::ServerConnectionImpl** (`/workspace/source/common/http/http2/codec_impl.h:815-879`) for HTTP/2

Once created, `codec_->dispatch(data)` is called repeatedly in `onData()` (line 503). The codec uses internal state machines to parse bytes:

**For HTTP/1.1** (`/workspace/source/common/http/http1/codec_impl.cc`):
- Parser callbacks invoke `onMessageBeginBase()` (line 1266) when HTTP message starts
- `onHeadersCompleteBase()` (line 1251) after headers parsed
- `onBody()` (line 1290) for body data
- `onMessageCompleteBase()` (line 1325) when message complete

**For HTTP/2** (`/workspace/source/common/http/http2/codec_impl.h`):
- Http2Visitor implements frame callbacks: `OnBeginHeadersForStream()`, `OnHeaderForStream()`, `OnEndHeadersForStream()`, `OnDataForStream()`, `OnEndStream()` (lines 191-258)

### When is the ActiveStream created and how does it relate to filter iteration?

When the codec detects a new HTTP message, it calls the **ServerConnectionCallbacks::newStream()** method. This is implemented by **ConnectionManagerImpl::newStream()** (`/workspace/source/common/http/conn_manager_impl.cc:387-442`).

The `newStream()` method:
1. Creates an **ActiveStream** struct (line 407), which is a private struct inside ConnectionManagerImpl (`/workspace/source/common/http/conn_manager_impl.h:141-532`)
2. Initializes the stream's filter manager (line 430)
3. Sets up response encoder callbacks (lines 431-434)
4. Adds the stream to the active streams list (line 440)
5. Returns a reference to the newly created ActiveStream

The **ActiveStream** implements:
- `Http::RequestDecoder` - receives decoded headers/data/trailers from codec
- `Http::StreamCallbacks` - stream lifecycle callbacks
- `FilterManagerCallbacks` - interface for filter manager to send responses back

### How does the FilterManager determine the order of decoder filter execution?

The **FilterManager** class (`/workspace/source/common/http/filter_manager.h:600-1090`) maintains a list of decoder filters called **StreamDecoderFilters** (lines 73-81):

```cpp
struct StreamDecoderFilters {
  using Element = ActiveStreamDecoderFilter;
  using Iterator = std::vector<ActiveStreamDecoderFilterPtr>::iterator;
  std::vector<ActiveStreamDecoderFilterPtr> entries_;
};
```

The filter order is determined during HTTP filter chain creation. The **HttpConnectionManagerConfig::createFilterChain()** method (`/workspace/source/extensions/filters/network/http_connection_manager/config.cc`) instantiates filters in the order specified in the configuration and adds them to the filter manager via **FilterChainUtility::buildFilterChain()**.

When **FilterManager::decodeHeaders()** is called (`/workspace/source/common/http/filter_manager.cc:537-636`), it iterates through `decoder_filters_` in forward order (A→B→C):
```cpp
for (; entry != decoder_filters_.end(); entry++) {
  FilterHeadersStatus status = (*entry)->handle_->decodeHeaders(headers, ...);
```

### What filter return values can stop or continue iteration?

The **FilterHeadersStatus** enum (`/workspace/envoy/http/filter.h:38-110`) defines return values:

1. **Continue** - Continue iteration to next filter
2. **StopIteration** (line 49) - Stop headers iteration, but continue with other filters for body data
3. **StopAllIterationAndBuffer** (line 98) - Stop all filters, buffer body data for later resumption
4. **StopAllIterationAndWatermark** (line 109) - Stop all filters, apply flow control watermarks
5. **ContinueAndDontEndStream** (line 86) - Continue iteration but ignore end_stream flag

The **FilterDataStatus** enum defines data phase return values:
1. **Continue** - Continue to next filter
2. **StopIterationAndBuffer** (line 144) - Stop iteration, buffer remaining data
3. **StopIterationAndWatermark** (line 155) - Stop iteration, apply watermarks
4. **StopIterationNoBuffer** (line 164) - Stop iteration without buffering

When a filter returns a "Stop*" status, the **ActiveStreamFilterBase::commonHandleAfterHeadersCallback()** method (`/workspace/source/common/http/filter_manager.h:130-162`) sets the iteration state:
```cpp
switch (status) {
case FilterHeadersStatus::StopIteration:
  iteration_state_ = IterationState::StopSingleIteration;
  break;
case FilterHeadersStatus::StopAllIterationAndBuffer:
  iteration_state_ = IterationState::StopAllBuffer;
  break;
```

If `stoppedAll()` returns true, iteration stops and returns false to halt the loop.

---

## Q3: Route Resolution and Upstream Selection

### How does the router determine which route configuration to use?

The **Router filter** (`/workspace/source/common/router/router.h:347`) is a **Http::StreamDecoderFilter** that implements **decodeHeaders()** (`/workspace/source/common/router/router.cc:445-704`). In this method (line 468-477), the router calls:

```cpp
const Router::RouteConstSharedPtr route = callbacks_->route();
```

This delegates to **FilterManagerCallbacks::route()**, which queries the **ConfigImpl** (the route configuration object). The ConfigImpl uses the **RouteMatcher** to select among multiple virtual hosts and then match routes within the virtual host. The matching occurs in **ConfigImpl::route()** (`/workspace/source/common/router/config_impl.h:1653-1660`), which takes request headers and stream info and returns the best-matching route entry.

The route matching logic is implemented in **RouteEntryImplBase::matchRoute()** (`/workspace/source/common/router/config_impl.cc:913`), which checks:
- Request path (prefix, exact, regex, or URI template match)
- Request method (GET, POST, etc.)
- Request headers (header-matching conditions)
- Query parameters
- Runtime conditions

### What is the sequence of operations that resolves a route entry to a specific upstream cluster?

Once a route is matched, the router accesses its cluster name via **RouteEntryImplBase::clusterName()** (`/workspace/source/common/router/config_impl.cc:965`), which returns a `const std::string&`.

Then (router.cc line 519):
```cpp
const Upstream::ThreadLocalCluster* cluster =
    config_->cm_.getThreadLocalCluster(route_entry_->clusterName());
```

This looks up the cluster in the thread-local cluster manager cache. If the cluster is not found, the router sends a 503 Service Unavailable response (line 528). The cluster object contains load balancer state, connection pools, and health information for all upstream hosts.

For dynamic cluster selection (using cluster specifier plugins), the **DynamicRouteEntry** class (`/workspace/source/common/router/config_impl.h:834-983`) is used instead, which determines the cluster name dynamically at request time.

### How does the router select a specific upstream host from the cluster?

In **Filter::decodeHeaders()** (router.cc line 664), after the cluster is found, the router calls:

```cpp
auto host_selection_response = cluster->chooseHost(this);
```

The **Filter** class extends **Upstream::LoadBalancerContextBase** (router.h line 310) and implements the LoadBalancerContext interface with methods like:
- `computeHashKey()` (line 363) - For hash-based load balancing
- `metadataMatchCriteria()` (line 379) - For subset load balancing
- `downstreamConnection()` (line 404) - Provides downstream connection context
- `downstreamHeaders()` (line 408) - Provides request headers for matching
- `shouldSelectAnotherHost()` (line 410) - Retry host selection

The cluster's load balancer uses these context methods to select an upstream **Upstream::HostConstSharedPtr** from the cluster's healthy hosts. The load balancer may use various algorithms: round-robin, least request, ring hash, maglev, random, etc., depending on the cluster configuration.

### What triggers the creation of the upstream connection?

After host selection, the router calls **Filter::continueDecodeHeaders()** (router.cc line 714). This method:

1. **Creates the connection pool** (line 724):
```cpp
std::unique_ptr<GenericConnPool> generic_conn_pool =
    createConnPool(*cluster, selected_host);
```

2. The **GenericConnPool** is created by the **GenericConnPoolFactory** (`/workspace/envoy/router/router.h:1595-1613`), which calls:
```cpp
factory->createGenericConnPool(host, cluster, upstream_protocol, ...)
```

3. This factory is either from the cluster's per-cluster factory or the default HTTP/TCP factory

4. **Creates UpstreamRequest** (router.cc lines 845-847):
```cpp
UpstreamRequestPtr upstream_request = std::make_unique<UpstreamRequest>(
    *this, std::move(generic_conn_pool), can_send_early_data,
    can_use_http3, allow_multiplexed_upstream_half_close_);
```

5. **Initiates the connection** (line 849):
```cpp
upstream_requests_.front()->acceptHeadersFromRouter(end_stream);
```

The UpstreamRequest's `acceptHeadersFromRouter()` method (`/workspace/source/common/router/upstream_request.cc:380-434`) calls:
```cpp
conn_pool_->newStream(this)
```

This call to `GenericConnPool::newStream()` (`/workspace/envoy/router/router.h:1438`) triggers the connection pool to either reuse an existing upstream connection or create a new one. The pool returns a callback interface, and when the connection is ready (or fails), it invokes **GenericConnectionPoolCallbacks::onPoolReady()** or **onPoolFailure()**.

---

## Q4: Upstream Connection and Data Flow

### How does the connection pool provide or create an upstream connection?

The **ConnPoolImplBase::tryCreateNewConnection()** method (`/workspace/source/common/conn_pool/conn_pool_base.cc:164-201`) handles upstream connection creation. When `newStream()` is called on the pool:

1. The pool checks if it can reuse an existing connection or must create a new one
2. If a new connection is needed, `tryCreateNewConnection()` is called
3. This calls the pure virtual `instantiateActiveClient()` method (line 182), which is overridden by HTTP and TCP pool implementations
4. For HTTP pools, **HttpConnPoolImplBase** (`/workspace/source/common/http/conn_pool_base.h:49-103`) creates an **ActiveClient** (lines 107-124)
5. The ActiveClient's constructor initiates a network connection to the upstream host

The **ConnectionImpl::onEvent()** callback in the upstream socket notifies the pool when the connection is established. Once established, the pool transitions the ActiveClient to the **Ready** state and invokes the waiting stream's **onPoolReady()** callback.

### What component actually writes the HTTP request to the upstream socket?

The **UpstreamRequest** class implements **RequestDecoder** for receiving upstream responses, but for sending requests, it receives an **Http::RequestEncoder** from the connection pool's `onPoolReady()` callback.

In **HttpConnPoolImplBase::onPoolReady()** (`/workspace/source/common/http/conn_pool_base.cc:84-94`):
```cpp
void HttpConnPoolImplBase::onPoolReady(...) {
  ActiveClient* http_client = static_cast<ActiveClient*>(&client);
  Http::RequestEncoder& new_encoder = http_client->newStreamEncoder(response_decoder);
  callbacks.onPoolReady(new_encoder, ...);
}
```

The `newStreamEncoder()` creates an encoder for the upstream codec (HTTP/1 or HTTP/2). The UpstreamRequest then:

1. Calls **UpstreamRequest::acceptHeadersFromRouter()** (`/workspace/source/common/router/upstream_request.cc:380-434`), which forwards the request headers through the **UpstreamFilterManager**
2. The filter manager's `decodeHeaders()` call encodes the headers via the RequestEncoder
3. The RequestEncoder writes to the underlying HTTP codec (HTTP1::ServerConnection or HTTP2::ServerConnection)
4. The codec writes the HTTP-formatted request to the upstream **Network::Connection**'s write buffer
5. The network connection's write event loop transmits the data via the TCP socket

### How does the response flow back from upstream through the filter chain?

When the upstream server sends a response:

1. The TCP socket receives data and calls the HCM's **onData()** callback
2. The HCM's codec (on the upstream connection) parses the response headers/body
3. The codec invokes its `ServerConnectionCallbacks::newStream()` method, which creates an UpstreamRequest acting as a ResponseDecoder
4. The UpstreamRequest's **decodeHeaders()** method (`/workspace/source/common/router/upstream_request.cc:267-307`) receives the response headers
5. This method calls `parent_.onUpstreamHeaders()` to notify the Router filter
6. The Router filter invokes **ActiveStream::encodeHeaders()** to start the downstream encoder filter chain
7. The encoder filter chain processes the response headers in **reverse order** (C→B→A)
8. Each encoder filter's `encodeHeaders()` method is called, and the final result is written to the downstream ResponseEncoder
9. The downstream codec (HTTP/1 or HTTP/2) formats the headers and writes them to the downstream connection

Similarly for body data and trailers, UpstreamRequest's **decodeData()** and **decodeTrailers()** methods invoke the encoder filter chain via **ActiveStream::encodeData()** and **encodeTrailers()**.

### At what points does the encoder filter chain get invoked vs. the decoder filter chain?

**Decoder Filter Chain** (Request Path - Forward Order A→B→C):
- Invoked in **FilterManager::decodeHeaders()** (`/workspace/source/common/http/filter_manager.cc:537-636`)
- Invoked in **FilterManager::decodeData()** (`/workspace/source/common/http/filter_manager.cc:638-762`)
- Invoked in **FilterManager::decodeTrailers()** (`/workspace/source/common/http/filter_manager.cc:764-844`)
- Entry point: Codec signals new request → **ActiveStream::decodeHeaders()** → **FilterManager::decodeHeaders()**

**Encoder Filter Chain** (Response Path - **REVERSE Order** C→B→A):
- Invoked in **FilterManager::encodeHeaders()** (`/workspace/source/common/http/filter_manager.cc:1225-1314`)
- Invoked in **FilterManager::encodeData()** (`/workspace/source/common/http/filter_manager.cc:1316-1399`)
- Invoked in **FilterManager::encodeTrailers()** (`/workspace/source/common/http/filter_manager.cc:1401-1480`)
- Entry point: Upstream response received → **UpstreamRequest::decodeHeaders()** → **Router::onUpstreamHeaders()** → **ActiveStream::encodeHeaders()** → **FilterManager::encodeHeaders()**

The **StreamEncoderFilters** structure (`/workspace/source/common/http/filter_manager.h:92-100`) uses a **reverse_iterator**, and `begin()` calls `rbegin()`, iterating from last filter to first:
```cpp
Iterator begin() { return entries_.rbegin(); }  // Reverse iteration!
```

The **commonEncodePrefix()** method (`/workspace/source/common/http/filter_manager.cc:900-932`) explicitly returns `encoder_filters_.begin()` which is the reverse begin, starting iteration from the end of the configured filter list.

---

## Evidence

### Critical File References

#### Network Listener and Filter Chain Selection
- `/workspace/envoy/network/listener.h:310-335` - TcpListenerCallbacks interface
- `/workspace/source/common/listener_manager/active_tcp_listener.h:25-99` - ActiveTcpListener class definition
- `/workspace/source/common/listener_manager/active_tcp_listener.cc:80-91` - onAccept() and onAcceptWorker() implementation
- `/workspace/source/common/listener_manager/active_tcp_socket.h:28-107` - ActiveTcpSocket listener filter wrapper
- `/workspace/source/common/listener_manager/active_stream_listener_base.h:28-144` - ActiveStreamListenerBase newConnection flow
- `/workspace/source/common/listener_manager/active_stream_listener_base.cc:38-76` - Filter chain selection and network filter creation
- `/workspace/source/common/listener_manager/filter_chain_manager_impl.h:127-334` - FilterChainManager and filter chain selection
- `/workspace/source/common/listener_manager/filter_chain_manager_impl.h:86-122` - FilterChain implementation
- `/workspace/source/common/listener_manager/listener_impl.cc:942-952` - ListenerImpl::createNetworkFilterChain()
- `/workspace/source/extensions/filters/network/http_connection_manager/config.h:127-373` - HttpConnectionManagerConfig
- `/workspace/source/extensions/filters/network/http_connection_manager/config.cc` - Factory implementation

#### HTTP Parsing and Codec
- `/workspace/source/common/http/conn_manager_impl.h:60-210` - ConnectionManagerImpl and ActiveStream definition
- `/workspace/source/common/http/conn_manager_impl.cc:486-542` - ConnectionManagerImpl::onData() entry point
- `/workspace/source/common/http/conn_manager_impl.cc:387-442` - ConnectionManagerImpl::newStream() creates ActiveStream
- `/workspace/source/common/http/http1/codec_impl.h:465-583` - Http1::ServerConnectionImpl HTTP/1.1 codec
- `/workspace/source/common/http/http1/codec_impl.cc:1266-1294` - HTTP/1 parsing callbacks (onMessageBegin, onHeadersComplete, onBody)
- `/workspace/source/common/http/http2/codec_impl.h:815-879` - Http2::ServerConnectionImpl HTTP/2 codec
- `/workspace/source/common/http/http2/codec_impl.h:191-258` - Http2Visitor callback interface

#### Filter Chain Iteration
- `/workspace/source/common/http/filter_manager.h:34-1090` - FilterManager class
- `/workspace/source/common/http/filter_manager.h:73-81` - StreamDecoderFilters (forward iteration A→B→C)
- `/workspace/source/common/http/filter_manager.h:92-100` - StreamEncoderFilters (reverse iteration C→B→A)
- `/workspace/source/common/http/filter_manager.h:105-237` - ActiveStreamFilterBase with IterationState enum
- `/workspace/source/common/http/filter_manager.h:240-330` - ActiveStreamDecoderFilter wrapper
- `/workspace/source/common/http/filter_manager.h:335-387` - ActiveStreamEncoderFilter wrapper
- `/workspace/source/common/http/filter_manager.cc:537-636` - FilterManager::decodeHeaders() forward iteration
- `/workspace/source/common/http/filter_manager.cc:638-762` - FilterManager::decodeData()
- `/workspace/source/common/http/filter_manager.cc:764-844` - FilterManager::decodeTrailers()
- `/workspace/source/common/http/filter_manager.cc:1225-1314` - FilterManager::encodeHeaders() reverse iteration
- `/workspace/source/common/http/filter_manager.cc:1316-1399` - FilterManager::encodeData()
- `/workspace/source/common/http/filter_manager.cc:1401-1480` - FilterManager::encodeTrailers()
- `/workspace/source/common/http/filter_manager.cc:900-932` - commonEncodePrefix() reverse iteration start
- `/workspace/envoy/http/filter.h:38-110` - FilterHeadersStatus enum values
- `/workspace/envoy/http/filter.h:129-165` - FilterDataStatus enum values

#### Router Filter Implementation
- `/workspace/source/common/router/router.h:310-452` - Router filter class definition
- `/workspace/source/common/router/router.cc:445-704` - Filter::decodeHeaders() main implementation
- `/workspace/source/common/router/router.cc:714-849` - Filter::continueDecodeHeaders() and pool creation
- `/workspace/source/common/router/router.cc:905-948` - Filter::createConnPool()

#### Route Matching and Cluster Selection
- `/workspace/source/common/router/config_impl.h:64-77,647-668` - Matchable interface and RouteEntryImplBase
- `/workspace/source/common/router/config_impl.h:1569-1694` - CommonConfigImpl and ConfigImpl
- `/workspace/source/common/router/config_impl.h:834-983` - DynamicRouteEntry for dynamic cluster selection
- `/workspace/source/common/router/config_impl.cc:913` - RouteEntryImplBase::matchRoute()
- `/workspace/source/common/router/config_impl.cc:965` - RouteEntryImplBase::clusterName()
- `/workspace/source/common/router/config_impl.cc:1691,1722,1754,1793,1824,1855` - Route matching implementations for various match types

#### Upstream Connection Pool and Management
- `/workspace/envoy/upstream/thread_local_cluster.h:107` - ThreadLocalCluster::chooseHost() interface
- `/workspace/envoy/router/router.h:1427-1460` - GenericConnPool interface
- `/workspace/envoy/router/router.h:1595-1613` - GenericConnPoolFactory interface
- `/workspace/envoy/tcp/upstream.h:114-160` - GenericUpstream interface for encoding to upstream
- `/workspace/source/common/conn_pool/conn_pool_base.h:19-421` - Base connection pool implementation
- `/workspace/source/common/conn_pool/conn_pool_base.h:30-160` - ActiveClient upstream connection wrapper
- `/workspace/source/common/conn_pool/conn_pool_base.cc:164-201` - ConnPoolImplBase::tryCreateNewConnection()
- `/workspace/source/common/http/conn_pool_base.h:49-103` - HttpConnPoolImplBase
- `/workspace/source/common/http/conn_pool_base.cc:84-94` - HttpConnPoolImplBase::onPoolReady() creates encoder
- `/workspace/source/common/http/http1/conn_pool.h:17-69` - HTTP/1.1 ActiveClient
- `/workspace/source/common/http/http2/conn_pool.h:18-29` - HTTP/2 ActiveClient
- `/workspace/source/common/tcp/conn_pool.h:40-133` - TCP ActiveClient

#### Upstream Request Handling and Response Flow
- `/workspace/source/common/router/upstream_request.h:66-372` - UpstreamRequest class definition
- `/workspace/source/common/router/upstream_request.cc:380-434` - UpstreamRequest::acceptHeadersFromRouter()
- `/workspace/source/common/router/upstream_request.cc:267-307` - UpstreamRequest::decodeHeaders() response received
- `/workspace/source/common/router/upstream_request.cc:321-327` - UpstreamRequest::decodeData() response body
- `/workspace/source/common/router/upstream_request.cc:329-340` - UpstreamRequest::decodeTrailers() response trailers
- `/workspace/source/common/router/upstream_request.h:265-297` - UpstreamRequestFilterManagerCallbacks

### Summary of Complete Flow Path

1. **TCP Accept**: `/workspace/source/common/listener_manager/active_tcp_listener.cc:80-91` → `onAccept()`
2. **Listener Filters**: `/workspace/source/common/listener_manager/active_tcp_socket.cc:111-173` → `continueFilterChain()`
3. **Filter Chain Selection**: `/workspace/source/common/listener_manager/filter_chain_manager_impl.h:148-149` → `findFilterChain()`
4. **Network Filter Creation**: `/workspace/source/common/listener_manager/listener_impl.cc:942-952` → `createNetworkFilterChain()`
5. **HCM Network Filter**: `/workspace/source/extensions/filters/network/http_connection_manager/config.h:127-373` → instantiated
6. **Byte Data Entry**: `/workspace/source/common/http/conn_manager_impl.cc:486-542` → `onData()`
7. **Codec Dispatch**: `/workspace/source/common/http/http1/codec_impl.cc:1266-1294` (HTTP/1) or `/workspace/source/common/http/http2/codec_impl.h:191-258` (HTTP/2) → parsing
8. **ActiveStream Creation**: `/workspace/source/common/http/conn_manager_impl.cc:387-442` → `newStream()`
9. **Decoder Filter Chain**: `/workspace/source/common/http/filter_manager.cc:537-636` → `decodeHeaders()` forward iteration
10. **Route Lookup**: `/workspace/source/common/router/router.cc:445-704` → route matching via `Router::decodeHeaders()`
11. **Cluster Lookup**: `/workspace/source/common/router/router.cc:519` → `cm_.getThreadLocalCluster()`
12. **Host Selection**: `/workspace/source/common/router/router.cc:664` → `cluster->chooseHost()`
13. **Pool Creation**: `/workspace/source/common/router/router.cc:724` → `createConnPool()`
14. **Connection Creation**: `/workspace/source/common/conn_pool/conn_pool_base.cc:164-201` → `tryCreateNewConnection()`
15. **Pool Ready**: `/workspace/source/common/http/conn_pool_base.cc:84-94` → `onPoolReady()` with encoder
16. **Upstream Send**: `/workspace/source/common/router/upstream_request.cc:380-434` → `acceptHeadersFromRouter()`
17. **Response Received**: `/workspace/source/common/router/upstream_request.cc:267-307` → `decodeHeaders()`
18. **Encoder Chain**: `/workspace/source/common/http/filter_manager.cc:1225-1314` → `encodeHeaders()` reverse iteration
19. **Downstream Send**: Response encoded and written to downstream connection

