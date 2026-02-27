# ext_authz Filter Handoff Document

## 1. Purpose

The **ext_authz filter** is an external authorization extension for Envoy that enforces authorization policies by delegating authorization decisions to an external service. It can operate as both an HTTP filter and a network (TCP) filter.

### What it does:
- **Intercepts requests** (HTTP or TCP) before they reach upstream services
- **Sends check requests** to an external authorization service (via gRPC or HTTP) containing request context (headers, body, certificates, connection info)
- **Enforces authorization decisions**:
  - If the service returns `OK` (status 200/0), the request proceeds to upstream
  - If the service returns `Denied`, the request is rejected with 403 (HTTP) or connection closed (network)
  - If the service times out or fails, the filter either denies or allows based on `failure_mode_allow` config
- **Applies mutations** from the authorization service (adds/removes/modifies headers and query parameters)
- **Emits dynamic metadata** that other filters can consume

### When to use it:
- Centralized authorization logic that needs to be shared across multiple services
- Integration with external policy engines (OPA, Authorino, etc.)
- Custom authorization that requires access to request headers, body, or connection details
- A/B testing authorization rules
- Authorization services that need to maintain state or audit trails

### Key principle:
It is **recommended to place ext_authz as the first filter** in the filter chain to authorize requests before other filters process them.

---

## 2. Dependencies

### Upstream Dependencies

The ext_authz filter depends on:

1. **gRPC/HTTP Clients**:
   - `envoy/grpc/async_client.h` - For async gRPC communication
   - `source/common/grpc/typed_async_client.h` - Typed gRPC client wrapper
   - `source/common/http/async_client_impl.h` - For HTTP service calls

2. **Protocol Buffers**:
   - `envoy/service/auth/v3/external_auth.proto` - Defines `CheckRequest`, `CheckResponse`, and `Authorization` service
   - `envoy/extensions/filters/http/ext_authz/v3/ext_authz.proto` - HTTP filter configuration
   - `envoy/extensions/filters/network/ext_authz/v3/ext_authz.proto` - Network filter configuration
   - `envoy/config/core/v3/base.proto` - Core types (metadata, HTTP status, etc.)

3. **HTTP/Network Infrastructure**:
   - `envoy/http/filter.h` - HTTP filter interface (`StreamFilter`, `StreamDecoderFilter`, `StreamEncoderFilter`)
   - `envoy/network/filter.h` - Network filter interface (`ReadFilter`, `ConnectionCallbacks`)
   - `envoy/upstream/cluster_manager.h` - Cluster discovery and connection management

4. **Stream Information & Routing**:
   - `envoy/stream_info/stream_info.h` - Request/connection metadata
   - `envoy/router/router.h` - Route-specific configuration support
   - `source/common/router/config_impl.h` - Per-route config parsing

5. **Statistics & Observability**:
   - `envoy/stats/stats_macros.h` - Statistics instrumentation
   - `envoy/tracing/tracer.h` - Distributed tracing integration

6. **Common Filter Library**:
   - `source/extensions/filters/common/ext_authz/ext_authz.h` - Shared interface (`Client`, `RequestCallbacks`, `Response`)
   - `source/extensions/filters/common/ext_authz/ext_authz_grpc_impl.h` - gRPC client implementation
   - `source/extensions/filters/common/ext_authz/ext_authz_http_impl.h` - HTTP client implementation
   - `source/extensions/filters/common/ext_authz/check_request_utils.h` - CheckRequest construction

7. **Header Mutation Rules**:
   - `source/extensions/filters/common/mutation_rules/mutation_rules.h` - Validates header/query parameter mutations

### Downstream Consumers

The ext_authz filter is consumed by:

1. **Envoy Configuration System**:
   - `source/extensions/filters/http/ext_authz/config.h/cc` - Factory for creating HTTP filter instances
   - `source/extensions/filters/network/ext_authz/config.h/cc` - Factory for creating network filter instances
   - These are registered as named filters with the HTTP/Network filter factories

2. **HTTP Filter Chain**:
   - Integrated into the HTTP filter chain via Envoy's filter manager
   - Can be placed at any position but **recommended as the first filter**
   - Receives decoder/encoder callbacks for request/response processing

3. **Network Filter Chain**:
   - Integrated into the network filter chain
   - Attached to connections before application data is processed

4. **Authorization Service**:
   - Consumes the authorization service cluster configuration
   - Makes gRPC or HTTP calls to the configured service endpoint

---

## 3. Relevant Components

### HTTP Filter Implementation

**`source/extensions/filters/http/ext_authz/ext_authz.h`**
- **Role**: Core HTTP filter class and configuration
- **Key classes**:
  - `FilterConfig`: Parses and holds configuration (failure_mode_allow, timeouts, header matchers, etc.)
  - `FilterConfigPerRoute`: Per-route overrides for check settings
  - `Filter`: Implements `Http::StreamFilter` and `RequestCallbacks`
  - `ExtAuthzLoggingInfo`: Holds logging/tracing information (latency, bytes, cluster info)
- **Key methods**:
  - `decodeHeaders()`: Initiates auth check when headers arrive
  - `decodeData()`: Buffers request body if needed
  - `onComplete()`: Processes authorization response, applies mutations

**`source/extensions/filters/http/ext_authz/ext_authz.cc`**
- **Role**: HTTP filter implementation
- **Key operations**:
  - `initiateCall()`: Constructs CheckRequest and sends to auth service
  - `onComplete()`: Handles auth response (accept, deny, error)
    - Applies header mutations (add, set, append, remove)
    - Handles query parameter mutations
    - Manages route cache clearing
    - Injects dynamic metadata
  - `continueDecoding()`: Resumes request processing after async auth check
- **Flow**:
  1. `decodeHeaders()` checks if disabled or per-route skipped
  2. If buffering enabled, buffers request data
  3. `initiateCall()` builds CheckRequest and calls auth service
  4. `onComplete()` receives response (sync or async)
  5. Applies mutations and continues/denies request

**`source/extensions/filters/http/ext_authz/config.h`**
- **Role**: Factory for creating HTTP filter instances
- **Key class**: `ExtAuthzFilterConfig` - Factory that creates `Filter` and `FilterConfig`
- **Default timeout**: 200ms

**`source/extensions/filters/http/ext_authz/config.cc`**
- **Role**: Configuration parsing and factory implementation
- **Operations**:
  - Parses YAML into protobuf configuration
  - Creates gRPC or HTTP client based on config
  - Sets up mutation rule checkers
  - Initializes statistics

### Network Filter Implementation

**`source/extensions/filters/network/ext_authz/ext_authz.h`**
- **Role**: Core network filter class and configuration
- **Key classes**:
  - `Config`: Holds network filter configuration
  - `Filter`: Implements `Network::ReadFilter` and `RequestCallbacks`
- **Key methods**:
  - `onData()`: Triggers auth check on first data
  - `onEvent()`: Handles connection close events
  - `onComplete()`: Processes auth response (closes connection on deny)

**`source/extensions/filters/network/ext_authz/ext_authz.cc`**
- **Role**: Network filter implementation
- **Key operations**:
  - `callCheck()`: Creates TCP CheckRequest and calls auth service
  - `onComplete()`:
    - On OK: continues reading (resume filter chain)
    - On Denied: closes connection immediately
    - On Error: closes unless `failure_mode_allow=true`
  - `onEvent()`: Cancels in-flight check if connection closes

### Common/Shared Implementation

**`source/extensions/filters/common/ext_authz/ext_authz.h`**
- **Role**: Defines the interface between HTTP/network filters and auth clients
- **Key types**:
  - `CheckStatus` enum: OK, Error, Denied
  - `Response` struct: Contains auth result, headers to add/set/remove, query params, status code, dynamic metadata
  - `RequestCallbacks` interface: `onComplete(Response)` callback
  - `Client` interface: `check()` method for making auth requests

**`source/extensions/filters/common/ext_authz/ext_authz_grpc_impl.h/cc`**
- **Role**: gRPC client for authorization service
- **Key class**: `GrpcClientImpl` - Implements `Client` and `AsyncRequestCallbacks`
- **Operations**:
  - `check()`: Creates gRPC request and sends async
  - `onSuccess()`: Parses CheckResponse into `Response` object
  - `onFailure()`: Creates error `Response`
  - Timeout management
  - Span creation for distributed tracing

**`source/extensions/filters/common/ext_authz/ext_authz_http_impl.h/cc`**
- **Role**: HTTP client for authorization service
- **Key class**: `HttpClientImpl` - Implements `Client`
- **Operations**:
  - Constructs HTTP request from CheckRequest
  - Parses HTTP response headers into `Response` object
  - Header filtering/selection using matchers
  - Query parameter extraction from response headers

**`source/extensions/filters/common/ext_authz/check_request_utils.h/cc`**
- **Role**: Constructs CheckRequest protobuf from HTTP/network context
- **Key methods**:
  - `createHttpCheck()`: Extracts attributes from HTTP stream (headers, path, body, certificates)
  - `createTcpCheck()`: Extracts attributes from TCP connection (source/dest IPs, certificates)
- **Responsibilities**:
  - Header selection based on matchers (allowed/disallowed headers)
  - Request body buffering and encoding
  - Metadata context population (filter_metadata, typed_filter_metadata)
  - Route metadata injection
  - TLS certificate and session details

### Configuration Protocol Buffers

**`api/envoy/extensions/filters/http/ext_authz/v3/ext_authz.proto`**
- **Key fields**:
  - `grpc_service` / `http_service`: Auth service endpoint
  - `failure_mode_allow`: Fail-open (default: false, fail-closed)
  - `with_request_body`: Buffer and include request body
  - `validate_mutations`: Validate auth response mutations
  - `status_on_error`: HTTP status on auth failure (default: 403)
  - `allowed_headers` / `disallowed_headers`: Header filtering rules
  - `include_peer_certificate`: Include client certificate in check request
  - `metadata_context_namespaces`: Metadata to include in request

**`api/envoy/extensions/filters/network/ext_authz/v3/ext_authz.proto`**
- Similar fields to HTTP variant
- Specific to network/TCP filtering

**`api/envoy/service/auth/v3/external_auth.proto`**
- **CheckRequest**: Sent to auth service
  - `attributes`: Connection/request context
  - `AttributeContext.Peer`: Source and destination peer info (IPs, certificates)
  - `AttributeContext.Request`: HTTP request details (headers, path, body)
- **CheckResponse**: Received from auth service
  - `status`: `OK`, `PERMISSION_DENIED`, other gRPC codes
  - `headers_to_append/set/remove`: Mutations
  - `body`: Response body for denied responses
  - `dynamic_metadata`: Metadata to inject

---

## 4. Failure Modes

### Failure Scenario: Authorization Service Unavailable

**When**: Auth service cluster doesn't exist, is unhealthy, or times out (default: 200ms)

**Behavior**:
- If `failure_mode_allow=true` (fail-open):
  - HTTP: Request continues with 200 status
  - Network: Connection continues
  - Metric: `ext_authz.failure_mode_allowed` counter incremented
  - Header: If `failure_mode_allow_header_add=true`, `x-envoy-auth-failure-mode-allowed: true` added
- If `failure_mode_allow=false` (fail-closed, **default**):
  - HTTP: Returns 403 Forbidden (or `status_on_error`)
  - Network: Connection closed
  - Metric: `ext_authz.error` counter incremented
  - Response code details: `ext_authz_error`

**Related code**:
- HTTP: `ext_authz.cc:onComplete()` case `CheckStatus::Error`
- Network: `ext_authz.cc:onComplete()` lines 105-107

### Failure Scenario: Invalid Authorization Response

**When**: Auth service returns headers with invalid characters, query parameters with invalid names, etc.

**Behavior**:
- If `validate_mutations=true`:
  - HTTP: Returns 500 Internal Server Error
  - Network: Connection closed
  - Validation happens in `validateAndCheckDecoderHeaderMutation()`
- If `validate_mutations=false` (**default**, unsafe):
  - Invalid mutations silently applied (can cause downstream issues)

**Related code**: `ext_authz.cc:validateAndCheckDecoderHeaderMutation()` lines 459-468

### Failure Scenario: Authorization Service Returns 5xx

**When**: Auth service returns HTTP 500-599 or gRPC code >= 2 (not OK)

**Behavior**:
- Treated same as timeout/unavailable (see above)
- Depends on `failure_mode_allow` setting

### Failure Scenario: Request Body Too Large

**When**: Request body exceeds `max_request_bytes`

**Behavior**:
- If `allow_partial_message=true`:
  - Body is truncated, `x-envoy-auth-partial-body: true` header added
  - Auth check proceeds with partial body
- If `allow_partial_message=false` (**default**):
  - Buffer limit enforced, request blocked if exceeded

**Related code**: `ext_authz.cc:isBufferFull()`, `decodeData()` lines 311-329

### Failure Scenario: Filter Disabled (Runtime/Metadata)

**When**: Filter disabled via `filter_enabled` or `filter_enabled_metadata`

**Behavior**:
- If `deny_at_disable=true`:
  - HTTP: Returns 403 (or `status_on_error`)
  - Network: Connection closed
  - Metric: `ext_authz.disabled` counter
- If `deny_at_disable=false` (**default**):
  - Request proceeds without auth check

**Related code**: `ext_authz.cc:decodeHeaders()` lines 266-279 (HTTP), `network/ext_authz.cc:onData()` lines 41-43

### Failure Scenario: Connection Closed During Auth Check

**When**: Client closes connection before auth service responds

**Behavior**:
- `onEvent()` is called with `RemoteClose` / `LocalClose`
- In-flight check is cancelled via `client_->cancel()`
- `config_->stats().active_` gauge decremented
- No further processing

**Related code**: `network/ext_authz.cc:onEvent()` lines 60-70

### Failure Scenario: Auth Response Tries to Mutate Pseudo-Headers

**When**: Auth service tries to add/remove pseudo-headers (`:method`, `:path`, etc.) or protected headers like `Host`

**Behavior**:
- Pseudo-headers are silently skipped (protected)
- Regular protected headers (e.g., Host) are also protected
- Validation checks `Http::HeaderUtility::headerNameIsValid()`

**Related code**: `ext_authz.cc:onComplete()` lines 593-607 (header removal)

### Error Handling Philosophy

**Key principle**: The filter is **defensive**:
- Cancels in-flight requests when streams end
- Validates auth responses before applying
- Logs at trace/debug level for debugging
- Increments counters for observability
- Never crashes on invalid auth response (with `validate_mutations=false`)

---

## 5. Testing

### Unit Tests

**HTTP Filter Tests**: `test/extensions/filters/http/ext_authz/ext_authz_test.cc`
- Test framework: `HttpFilterTestBase` (parameterized for gRPC and HTTP clients)
- Coverage:
  - Normal flow (headers → check → response)
  - Request body buffering
  - Header mutations (add, set, remove)
  - Query parameter mutations
  - Per-route configuration
  - Metadata passing
  - Failure modes (timeout, error, denied)
  - Dynamic metadata injection
  - Stats verification
  - Disabled filter behavior
  - TLS certificate inclusion

**Network Filter Tests**: `test/extensions/filters/network/ext_authz/ext_authz_test.cc`
- Coverage:
  - Connection authorization
  - Connection close handling
  - In-flight check cancellation
  - Failure mode behavior
  - Dynamic metadata for network
  - Stats tracking

**Configuration Tests**:
- `test/extensions/filters/http/ext_authz/config_test.cc` - Config parsing and validation
- `test/extensions/filters/network/ext_authz/config_test.cc` - Network config parsing

**Common Library Tests**: `test/extensions/filters/common/ext_authz/`
- `ext_authz_grpc_impl_test.cc` - gRPC client behavior (callbacks, timeouts, cancellation)
- HTTP client tests for header filtering and metadata extraction

### Integration Tests

**File**: `test/extensions/filters/http/ext_authz/ext_authz_integration_test.cc`

Tests full request flow with mock auth service:
- `FakeHttpConnectionPtr fake_ext_authz_connection_` - Mock auth service connection
- `FakeStreamPtr ext_authz_request_` - Simulates auth service request/response
- Scenarios:
  - End-to-end authorization flow
  - Dynamic metadata injection
  - Header mutations with upstream integration
  - Failure mode testing (service unavailable)
  - Timeout handling
  - Request body forwarding

### Fuzz Tests

**Files**:
- `test/extensions/filters/http/ext_authz/ext_authz_grpc_fuzz_test.cc`
- `test/extensions/filters/http/ext_authz/ext_authz_http_fuzz_test.cc`
- `test/extensions/filters/network/ext_authz/ext_authz_fuzz_test.cc`

Fuzz configuration via `.proto` files:
- `ext_authz_fuzz.proto` - Fuzz test case definitions
- Libfuzzer-based corpus-driven testing
- Corpus directories: `ext_authz_grpc_corpus/`, `ext_authz_http_corpus/`

### Running Tests

```bash
# Run HTTP filter unit tests
bazel test //test/extensions/filters/http/ext_authz:ext_authz_test

# Run network filter unit tests
bazel test //test/extensions/filters/network/ext_authz:ext_authz_test

# Run integration tests
bazel test //test/extensions/filters/http/ext_authz:ext_authz_integration_test

# Run config tests
bazel test //test/extensions/filters/http/ext_authz:config_test
bazel test //test/extensions/filters/network/ext_authz:config_test

# Run common library tests
bazel test //test/extensions/filters/common/ext_authz:ext_authz_grpc_impl_test

# Run fuzz tests
bazel test //test/extensions/filters/http/ext_authz:ext_authz_grpc_fuzz_test
bazel test //test/extensions/filters/http/ext_authz:ext_authz_http_fuzz_test
```

### Test Mocks

**File**: `test/extensions/filters/common/ext_authz/mocks.h`
- `MockClient`: Mock for `ext_authz::Client`
- `MockRequestCallbacks`: Mock for request callbacks
- Used extensively in unit tests to simulate auth service behavior

---

## 6. Debugging

### Logs and Tracing

The filter uses Envoy's logging system with log ID `ext_authz`:

```cpp
class Filter : public Logger::Loggable<Logger::Id::ext_authz>
```

**Log levels**:
- **TRACE**: Detailed flow (header mutations, dynamic metadata, response processing)
- **DEBUG**: High-level operations (buffering, filter state)
- **INFO/WARN**: Significant events or configuration issues

**Key log messages**:
- "ext_authz filter calling authorization server" - Check request sent (TRACE)
- "ext_authz filter is buffering the request" - Request body buffering started (DEBUG)
- "ext_authz filter finished buffering the request" - Buffering complete (DEBUG)
- "ext_authz is clearing route cache" - Route cache cleared (DEBUG)
- "Rejecting invalid header to set" / "Rejecting invalid header to add" - Mutation validation failure (TRACE)

### Statistics

All statistics are under `ext_authz.*` namespace. Key metrics:

**HTTP Filter** (`ext_authz.<stat_prefix>.*`):
- `ok` - Authorization service returned OK
- `denied` - Authorization service returned Denied (403 sent)
- `error` - Authorization service unreachable or error (depends on `failure_mode_allow`)
- `failure_mode_allowed` - Error occurred but allowed due to `failure_mode_allow=true`
- `disabled` - Filter was disabled
- `invalid` - Invalid auth response (with `validate_mutations=true`)
- `ignored_dynamic_metadata` - Dynamic metadata ignored due to disabled ingestion

**Network Filter** (`ext_authz.<stat_prefix>.*`):
- `ok` - Authorization granted
- `denied` - Authorization denied
- `error` - Authorization service error
- `failure_mode_allowed` - Error allowed
- `cx_closed` - Connection closed
- `total` - Total authorization checks
- `active` - In-flight checks (gauge)
- `disabled` - Filter disabled

**To debug**:
```bash
# View stats during runtime
curl http://localhost:9901/stats | grep ext_authz

# Watch stats in real-time
watch -n 1 'curl -s http://localhost:9901/stats | grep ext_authz'
```

### Distributed Tracing

The filter integrates with Envoy's tracing system:

**Spans created**:
- HTTP: Child span created under request span via `decoder_callbacks_->activeSpan()`
- Network: Uses `Tracing::NullSpan` (no distributed trace on network filter)

**Span tags**:
- Defined in `source/extensions/filters/common/ext_authz/ext_authz.h` (`TracingConstantValues`):
  - `ext_authz_status` - Status (OK, Unauthorized, Error)
  - `ext_authz_unauthorized` - Reason if denied
  - `ext_authz_ok` - Set if authorized
  - `ext_authz_http_status` - HTTP status on error

**To debug**: Enable trace logging for request:
```
x-envoy-force-trace: true
```

### Dynamic Metadata

The filter emits dynamic metadata that can be consumed by subsequent filters:

**Namespace**: `envoy.filters.http.ext_authz` (HTTP), `envoy.filters.network.ext_authz` (Network)

**Fields**:
- `ext_authz_duration` - Duration of auth check in milliseconds (always present if check completes)
- Custom fields from auth service's `CheckResponse.dynamic_metadata`

**To access in filter config**:
```yaml
filter_enabled_metadata:
  match:
    metadata:
      filter: envoy.filters.http.ext_authz
      path:
        - key: ext_authz_duration
        - key: custom_field
```

### Common Debugging Scenarios

#### Scenario 1: Requests Always Denied

**Diagnosis**:
1. Check filter is enabled: `ext_authz.disabled` stat should be low/zero
2. Check auth service is reachable: Look for `ext_authz.error` spikes
3. Check auth service response: Enable trace logging, inspect logs for "ext_authz filter calling authorization server"
4. Verify `failure_mode_allow` is false (default)

**Steps**:
```bash
# 1. Check stats
curl localhost:9901/stats | grep ext_authz

# 2. Enable debug logging
# (Envoy config: --log-level debug)

# 3. Check auth service logs
# Look for incoming CheckRequest messages

# 4. Test auth service directly
grpcurl -d '{}' auth-service:9000 envoy.service.auth.v3.Authorization/Check
```

#### Scenario 2: Headers Not Being Forwarded to Auth Service

**Diagnosis**:
- By default, gRPC forwards all headers, HTTP forwards only specific headers
- Check `allowed_headers` / `disallowed_headers` configuration

**Steps**:
```yaml
# For gRPC, allow specific headers:
ext_authz:
  grpc_service:
    envoy_grpc:
      cluster_name: ext_authz
  allowed_headers:
    patterns:
      - safe_regex:
          regex: "^authorization$|^x-.*"

# For HTTP, defaults are: Host, Method, Path, Content-Length, Authorization
```

#### Scenario 3: Request Body Not Being Sent to Auth Service

**Diagnosis**: `with_request_body` not configured

**Steps**:
```yaml
ext_authz:
  grpc_service:
    envoy_grpc:
      cluster_name: ext_authz
  with_request_body:
    max_request_bytes: 8192
    allow_partial_message: true  # True for streaming bodies
    pack_as_bytes: true           # True to send as bytes instead of UTF-8 string
```

#### Scenario 4: Auth Check Taking Too Long

**Diagnosis**: Check `ext_authz_duration` in dynamic metadata or logs

**Steps**:
```bash
# 1. Add debug logging to see duration
# 2. Check auth service latency (check its own metrics)
# 3. Increase timeout if needed (default 200ms)

# Enable per-request timeout override:
ext_authz:
  with_request_body:
    max_request_bytes: 8192
# Increase from default 200ms
```

#### Scenario 5: Header Mutations Not Applied

**Diagnosis**:
- Check if headers are in the auth response
- Check if `validate_mutations=true` is rejecting them
- Check for pseudo-header restrictions

**Steps**:
```bash
# Enable trace logging to see mutations:
# Look for "ext_authz filter added header(s) to the request"

# Check auth service response includes headers:
# CheckResponse.headers_to_set / headers_to_append

# Validate headers don't start with ":" (pseudo-headers)
# Valid: x-custom-header, authorization, content-type
# Invalid: :method, :path, :authority
```

### Response Flags

When ext_authz denies or errors a request, Envoy sets `StreamInfo::CoreResponseFlag`:

- `UnauthorizedExternalService` - Set when ext_authz denies or errors a request

This can be used for logging/metrics:
```
envoy_http_requests{response_flag="UnauthorizedExternalService"}
```

### Cluster Configuration

The auth service cluster is configured separately:

```yaml
clusters:
  - name: ext_authz
    type: STRICT_DNS
    typed_extension_protocol_options:
      envoy.extensions.upstreams.http.v3.HttpProtocolOptions:
        "@type": type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions
        explicit_http_config:
          http2_protocol_options: {}  # For gRPC
    load_assignment:
      cluster_name: ext_authz
      endpoints:
        - lb_endpoints:
            - endpoint:
                address:
                  socket_address:
                    address: auth-server.example.com
                    port_value: 9000
    connect_timeout: 0.25s  # TCP connection timeout
```

### Performance Considerations

1. **Timeout**: Default 200ms - tune based on auth service latency
2. **Buffer size**: `max_request_bytes` - balance accuracy vs. memory
3. **Request body buffering**: Only enable if needed (adds latency and memory)
4. **Cluster health**: Ensure auth service has good health check configuration
5. **Concurrency**: Auth service should handle concurrent requests (per-filter instance, not global)

---

## Summary Table

| Aspect | HTTP Filter | Network Filter |
|--------|-------------|----------------|
| **Location** | `source/extensions/filters/http/ext_authz/` | `source/extensions/filters/network/ext_authz/` |
| **When invoked** | On request headers | On first data (or after TLS) |
| **Deny action** | 403 Forbidden (HTTP) | Connection close |
| **Supported services** | gRPC, HTTP | gRPC only |
| **Request body support** | Yes (buffering) | No |
| **Header mutations** | Supported | Not applicable |
| **Query param mutations** | Supported | Not applicable |
| **Dynamic metadata** | Per-request | Per-connection |
| **Use case** | API authorization, WAF rules | Network-level policy, DDoS filtering |

---

## Key Files for Maintenance

| File | Purpose | Priority |
|------|---------|----------|
| `source/extensions/filters/http/ext_authz/ext_authz.h` | HTTP filter interface | P0 |
| `source/extensions/filters/http/ext_authz/ext_authz.cc` | HTTP filter implementation | P0 |
| `source/extensions/filters/common/ext_authz/ext_authz.h` | Shared interface | P0 |
| `source/extensions/filters/common/ext_authz/ext_authz_grpc_impl.cc` | gRPC client | P1 |
| `source/extensions/filters/common/ext_authz/ext_authz_http_impl.cc` | HTTP client | P1 |
| `source/extensions/filters/common/ext_authz/check_request_utils.cc` | Request construction | P1 |
| `api/envoy/extensions/filters/http/ext_authz/v3/ext_authz.proto` | Config schema | P1 |
| `api/envoy/service/auth/v3/external_auth.proto` | Service interface | P0 |

