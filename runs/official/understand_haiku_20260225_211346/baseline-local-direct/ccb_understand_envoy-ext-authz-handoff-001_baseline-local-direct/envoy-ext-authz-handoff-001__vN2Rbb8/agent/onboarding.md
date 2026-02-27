# ext_authz Filter Handoff Document

## 1. Purpose

The **ext_authz filter** is Envoy's external authorization filter that delegates authorization decisions to an external service. It operates at both the HTTP (L7) and TCP (L4) layers.

### What it does:
- **HTTP Filter**: Intercepts HTTP requests before routing and calls an external gRPC or HTTP authorization service
- **Network Filter**: Intercepts TCP connections and calls an external gRPC authorization service
- **Authorization Decision**: Based on the service response, either:
  - **Allows** the request/connection to proceed
  - **Denies** with HTTP 403 (Forbidden) or closes the TCP connection
  - Returns an **error** (handled via failure modes)

### Key capabilities:
- **Header mutations**: Adds, removes, or modifies request headers based on auth service response
- **Response headers**: Can add headers to the downstream response on success
- **Query parameter mutations**: Can add or remove query parameters
- **Dynamic metadata**: Propagates metadata from the auth service to other filters
- **Request body buffering**: Can buffer and send request body to auth service (HTTP filter only)
- **Per-route configuration**: Can enable/disable the filter or customize behavior per route
- **Flexible auth service**: Supports both gRPC and HTTP backend services

### When to use:
- Authentication/authorization (e.g., OAuth2, JWT validation delegated to external service)
- API gateway authorization policies
- WAF (Web Application Firewall) integration
- Fine-grained access control based on request attributes
- Request enrichment with external service data

---

## 2. Dependencies

### Upstream Dependencies (What ext_authz depends on)

**Core Envoy interfaces:**
- `envoy/http/filter.h`: HTTP filter base classes (`StreamDecoderFilter`, `StreamEncoderFilter`)
- `envoy/network/filter.h`: Network filter base classes (`ReadFilter`, `WriteFilter`)
- `envoy/service/auth/v3/external_auth.pb.h`: Protocol buffer definitions for CheckRequest/CheckResponse
- `envoy/upstream/cluster_manager.h`: Cluster management for routing auth requests
- `envoy/runtime/runtime.h`: Runtime feature flags and fractional percentages

**gRPC client:**
- `envoy/grpc/async_client.h`: Async gRPC client for calling auth service
- `source/common/grpc/typed_async_client.h`: Typed async client wrapper

**HTTP client:**
- `source/common/http/async_client_impl.h`: Async HTTP client for raw HTTP auth service calls

**Utilities:**
- `source/common/http/headers.h`, `source/common/http/utility.h`: HTTP header and utility functions
- `source/common/common/matchers.h`: Pattern matching for headers
- `source/common/router/config_lib`: Route information access
- `source/extensions/filters/common/mutation_rules`: Header/query parameter mutation validation
- `source/common/tracing/http_tracer_impl.h`: Distributed tracing support

**Protobuf and configuration:**
- `envoy/extensions/filters/http/ext_authz/v3/ext_authz.pb.h`: HTTP filter proto config
- `envoy/extensions/filters/network/ext_authz/v3/ext_authz.pb.h`: Network filter proto config

### Downstream Consumers (What depends on ext_authz)

**Direct consumers:**
- **HTTP request handlers** in the filter chain: The ext_authz filter is registered as an HTTP filter and is called from the HTTP filter manager
- **Network connection handlers** in the filter chain: The network filter is called for new TCP connections
- **Router configuration**: Can be enabled/disabled per route, VirtualHost, or weighted cluster

**Related systems that interact with ext_authz:**
- **Upstream cluster**: The auth service endpoint (configured as `grpc_service` or `http_service`)
- **Tracing system**: If tracing is enabled, the filter creates child spans with details about the auth check
- **Stats system**: Emits counters for authorization decisions (ok, denied, error, etc.)
- **Metadata system**: Consumes and produces metadata for context passing and logging

**Integration points:**
- **Per-filter configuration**: Can be overridden at route/VirtualHost level via `ExtAuthzPerRoute`
- **Filter state**: Can store logging information in stream's filter state for access logs
- **Dynamic metadata**: Propagates auth service response as dynamic metadata to downstream filters

---

## 3. Relevant Components

### HTTP Filter Implementation

**`source/extensions/filters/http/ext_authz/ext_authz.h`**: Main HTTP filter class
- **Role**: Implements the `Http::StreamFilter` interface, handles request/response filtering
- **Key classes**:
  - `Filter`: Implements decoding (request) and encoding (response) filter hooks
  - `FilterConfig`: Global configuration for the filter instance
  - `FilterConfigPerRoute`: Per-route configuration overrides
  - `ExtAuthzLoggingInfo`: Stores authorization check metadata for logging

**`source/extensions/filters/http/ext_authz/ext_authz.cc`**: HTTP filter implementation
- **Responsibility**: Core filter logic, header/query parameter mutation handling
- **Key methods**:
  - `decodeHeaders()`: Initiates authorization check
  - `decodeData()`: Buffers request body if configured
  - `onComplete()`: Handles authorization service response
  - Header mutation methods: `addResponseHeaders()`, mutation validation
- **Important flow**:
  1. On request headers, builds CheckRequest and calls auth service
  2. Buffers data if needed (for request body)
  3. On auth response, applies mutations and either allows/denies request

**`source/extensions/filters/http/ext_authz/config.h` and `config.cc`**: Configuration factory
- **Responsibility**: Parse proto config, create filter instances
- **Key functions**:
  - `createFilterFactoryFromProtoWithServerContextTyped()`: Creates HTTP filter factory
  - `createRouteSpecificFilterConfigTyped()`: Creates per-route config
  - Chooses between gRPC and HTTP client based on config

### Network Filter Implementation

**`source/extensions/filters/network/ext_authz/ext_authz.h`**: Main network filter class
- **Role**: Implements the `Network::ReadFilter` interface for TCP connections
- **Key classes**:
  - `Filter`: Handles new connections and buffered data
  - `Config`: Global configuration for network filter

**`source/extensions/filters/network/ext_authz/ext_authz.cc`**: Network filter implementation
- **Key methods**:
  - `onNewConnection()`: Called on new TCP connection
  - `onData()`: Called when data arrives (initiates auth check)
  - `onComplete()`: Handles auth service response
  - `onEvent()`: Handles connection close events (cancels pending auth request)
- **Important flow**: Waits for first data on connection, then calls auth service

### Common/Shared Components

**`source/extensions/filters/common/ext_authz/ext_authz.h`**: Core interfaces and data structures
- **Role**: Defines the abstraction between filters and transport implementations
- **Key abstractions**:
  - `Client`: Abstract interface for authorization service communication
  - `RequestCallbacks`: Callback interface for async responses
  - `CheckStatus`: Enum for response status (OK, Error, Denied)
  - `Response`: Structure containing auth service response (headers, body, status)
  - `HeaderValues`: Constants for Envoy-specific auth headers

**`source/extensions/filters/common/ext_authz/ext_authz_grpc_impl.h` and `.cc`**: gRPC client implementation
- **Role**: Communicates with gRPC authorization services
- **Key class**: `GrpcClientImpl`
- **Responsibilities**:
  - Creates CheckRequest protobuf from HTTP/TCP data
  - Makes async gRPC call to auth service
  - Parses CheckResponse and extracts header/body mutations
  - Handles gRPC failures and timeouts

**`source/extensions/filters/common/ext_authz/ext_authz_http_impl.h` and `.cc`**: HTTP client implementation
- **Role**: Communicates with raw HTTP authorization services
- **Key classes**:
  - `RawHttpClientImpl`: Makes HTTP calls to auth service
  - `ClientConfig`: Configuration specific to HTTP service
- **Responsibilities**:
  - Constructs HTTP request from CheckRequest data
  - Makes async HTTP call to auth service endpoint
  - Parses HTTP response and extracts header mutations
  - Handles HTTP failures and timeouts

**`source/extensions/filters/common/ext_authz/check_request_utils.h` and `.cc`**: Request building utilities
- **Role**: Extracts request attributes and builds CheckRequest protobuf
- **Key functions**:
  - `createHttpCheck()`: Builds CheckRequest from HTTP request headers/body
  - `createTcpCheck()`: Builds CheckRequest from TCP connection info
  - Header filtering based on allowed/disallowed matchers

### Protocol Buffers

**`api/envoy/extensions/filters/http/ext_authz/v3/ext_authz.proto`**: HTTP filter configuration schema
- `ExtAuthz` message: Main configuration
- `BufferSettings`: Request body buffering options
- `HttpService`: Raw HTTP service configuration
- `AuthorizationRequest` / `AuthorizationResponse`: HTTP service request/response handling
- `ExtAuthzPerRoute`: Per-route configuration
- `CheckSettings`: Per-route check customization

**`api/envoy/extensions/filters/network/ext_authz/v3/ext_authz.proto`**: Network filter configuration schema

---

## 4. Failure Modes

### Configuration-Controlled Behavior

**`failure_mode_allow` (default: false)**:
- When `true`: If the auth service is unavailable or returns a 5xx error, the request/connection is **allowed**
- When `false`: Any error in reaching the auth service causes the request to be **rejected** with status configured in `status_on_error`
- **Use case**: Choose based on security posture (fail-open vs fail-closed)

**`status_on_error` (default: HTTP 403)**:
- HTTP status code returned to client when auth service is unavailable and `failure_mode_allow=false`
- Can be any valid HTTP status (e.g., 401 Unauthorized, 500 Internal Server Error)

**`failure_mode_allow_header_add` (default: false)**:
- When both `failure_mode_allow=true` AND this is `true`: Adds header `x-envoy-auth-failure-mode-allowed: true` to request
- Allows downstream services to know the auth check failed but was allowed

### Common Failure Scenarios

1. **Auth service timeout**:
   - Default timeout: 200ms
   - Configurable via `grpc_service.timeout` or `http_service.server_uri.timeout`
   - Handled as an error (subject to `failure_mode_allow`)

2. **Auth service unavailable** (DNS, connection failure, etc.):
   - gRPC: Connection attempts and retries (controlled by cluster config)
   - HTTP: Async request fails immediately
   - Treated as error (subject to `failure_mode_allow`)

3. **Invalid authorization response**:
   - If `validate_mutations=true`: Response headers/query params validated for invalid characters
   - Invalid mutations cause request rejection with HTTP 500
   - Can be controlled per-filter or set in config

4. **Malformed CheckRequest**:
   - Validation at proto level
   - Filter logs errors and treats as authorization error

5. **Request body buffering limit exceeded**:
   - If `with_request_body.max_request_bytes` exceeded: Returns HTTP 413 (Payload Too Large)
   - This always results in rejection (overrides `failure_mode_allow`)

6. **Filter disabled**:
   - If `deny_at_disable=true` and filter is disabled: Returns configured `status_on_error` status
   - Otherwise: Request is allowed through

### Error Handling in Code

**HTTP Filter (`source/extensions/filters/http/ext_authz/ext_authz.cc`)**:
- Line ~810-830: `onComplete()` handles error status
  - Increments `error` counter
  - If `failure_mode_allow`: allows request and increments `failure_mode_allowed` counter
  - If not: calls local response with `status_on_error` code

**Network Filter (`source/extensions/filters/network/ext_authz/ext_authz.cc`)**:
- Similar pattern: checks `failure_mode_allow` and `failureModeAllow()`
- Closes connection on denial (network filter is stricter by design)

### Logging and Tracing on Errors

- Uses `ENVOY_STREAM_LOG()` macro with `trace` level for detailed error information
- Errors are visible in Envoy's trace logs if enabled
- Metadata is captured in `ExtAuthzLoggingInfo` for access logs

---

## 5. Testing

### Test File Locations and Types

**Common/Shared Components Tests:**

1. **`test/extensions/filters/common/ext_authz/ext_authz_grpc_impl_test.cc`**
   - Tests: gRPC client implementation
   - Scope: Request building, response parsing, timeout handling, failure scenarios
   - Uses mock async gRPC client

2. **`test/extensions/filters/common/ext_authz/ext_authz_http_impl_test.cc`**
   - Tests: HTTP client implementation
   - Scope: HTTP request construction, response parsing, header handling
   - Uses mock HTTP async client

3. **`test/extensions/filters/common/ext_authz/check_request_utils_test.cc`**
   - Tests: CheckRequest building utilities
   - Scope: HTTP/TCP attribute extraction, header filtering

**HTTP Filter Tests:**

1. **`test/extensions/filters/http/ext_authz/ext_authz_test.cc`** (Main unit tests)
   - Tests: HTTP filter behavior, header mutations, state management
   - Test fixtures:
     - `HttpFilterTest`: Basic filter functionality
     - `InvalidMutationTest`: Mutation validation
     - `DecoderHeaderMutationRulesTest`: Header mutation rules
     - `EmitFilterStateTest`: Filter state emission for logging
   - Covers: Response handling, header mutations, error cases, per-route config

2. **`test/extensions/filters/http/ext_authz/config_test.cc`**
   - Tests: Configuration parsing and validation
   - Scope: Proto config parsing, filter factory creation

3. **`test/extensions/filters/http/ext_authz/ext_authz_integration_test.cc`** (Integration tests)
   - Tests: Full end-to-end HTTP flows
   - Infrastructure: Uses `HttpIntegrationTest` base class
   - Test scenarios: Actual gRPC auth server communication, timeout handling, header mutations
   - Parameterized: Tests both gRPC and HTTP backends, IPv4/IPv6, filter state stats

4. **`test/extensions/filters/http/ext_authz/ext_authz_grpc_fuzz_test.cc` and `ext_authz_http_fuzz_test.cc`**
   - Tests: Fuzz testing for robustness
   - Tools: libFuzzer for mutation-based fuzzing

**Network Filter Tests:**

1. **`test/extensions/filters/network/ext_authz/ext_authz_test.cc`**
   - Tests: Network filter behavior for TCP connections
   - Scope: Connection handling, auth decision application

2. **`test/extensions/filters/network/ext_authz/config_test.cc`**
   - Tests: Network filter configuration parsing

3. **`test/extensions/filters/network/ext_authz/ext_authz_fuzz_test.cc`**
   - Tests: Fuzz testing for TCP filter

### How to Run Tests

**Build the project:**
```bash
# Full build (slow, for the entire codebase)
bazel build //...

# Build only ext_authz components
bazel build //source/extensions/filters/http/ext_authz/...
bazel build //source/extensions/filters/network/ext_authz/...
bazel build //source/extensions/filters/common/ext_authz/...
```

**Run specific test suites:**
```bash
# HTTP filter unit tests
bazel test //test/extensions/filters/http/ext_authz:ext_authz_test

# HTTP filter integration tests
bazel test //test/extensions/filters/http/ext_authz:ext_authz_integration_test

# Common component tests
bazel test //test/extensions/filters/common/ext_authz:ext_authz_grpc_impl_test
bazel test //test/extensions/filters/common/ext_authz:ext_authz_http_impl_test

# Network filter tests
bazel test //test/extensions/filters/network/ext_authz:ext_authz_test

# All ext_authz tests
bazel test //test/extensions/filters/http/ext_authz/...
bazel test //test/extensions/filters/network/ext_authz/...
bazel test //test/extensions/filters/common/ext_authz/...
```

**Run with verbose output:**
```bash
bazel test //test/extensions/filters/http/ext_authz:ext_authz_test -s  # Shows output
```

**Testing locally with mocks:**
- Tests use GoogleMock and use mock callbacks/clients
- Integration tests create actual upstream servers for testing communication
- Fuzz tests exercise edge cases and malformed inputs

### Key Test Patterns

1. **Response handling**: Tests verify different auth service responses (OK, Denied, Error)
2. **Header mutations**: Tests verify headers are correctly added, removed, or modified
3. **Timeout scenarios**: Tests verify behavior when auth service times out
4. **Failure modes**: Tests verify `failure_mode_allow` behavior
5. **Per-route config**: Tests verify route-specific overrides
6. **Buffer limit**: Tests verify behavior when request body exceeds limits
7. **Invalid mutations**: Tests verify rejected responses when mutations are invalid

---

## 6. Debugging

### Enabling Trace Logs

The filter uses Envoy's `ENVOY_STREAM_LOG()` macro with `trace` level for detailed logging. To enable:

1. **Configure Envoy with trace logging:**
   ```yaml
   admin:
     address:
       socket_address:
         address: 127.0.0.1
         port_value: 9901

   # Set log level for ext_authz component
   # In bootstrap config or admin interface
   ```

2. **Use Envoy's admin interface to change log levels:**
   ```bash
   # SSH into Envoy or call via admin interface
   curl -X POST http://localhost:9901/logging?ext_authz=trace
   ```

3. **Stream logs from Envoy:**
   ```bash
   tail -f /var/log/envoy/envoy.log | grep ext_authz
   ```

### Key Statistics to Monitor

These counters are emitted to the stats system at `ext_authz.<stat_prefix>.*`:

```
ext_authz.ok                          # Authorization succeeded
ext_authz.denied                      # Authorization denied (403)
ext_authz.error                       # Auth service error or unavailable
ext_authz.failure_mode_allowed        # Error but allowed due to failure_mode_allow
ext_authz.disabled                    # Filter disabled for this request
ext_authz.invalid                     # Invalid auth response (bad mutations)
ext_authz.ignored_dynamic_metadata    # Dynamic metadata from auth ignored
ext_authz.filter_state_name_collision # Logging namespace collision
```

**For gRPC-specific stats** (Envoy gRPC only):
```
cluster.<ext_authz_cluster>.upstream_rq_*              # Standard cluster stats
cluster.<ext_authz_cluster>.upstream_rq_time           # Auth request latency
```

### Using Stats for Debugging

**Query stats via admin interface:**
```bash
curl http://localhost:9901/stats | grep ext_authz

# Or with grep
curl http://localhost:9901/stats | grep -E "ext_authz\.(ok|denied|error)"
```

**Monitor in real-time:**
```bash
watch -n 1 'curl -s http://localhost:9901/stats | grep ext_authz'
```

### Common Debugging Scenarios

**Scenario 1: All requests denied**
1. Check auth service is running: `curl <auth_service_endpoint>`
2. Check network connectivity: `telnet <auth_host> <auth_port>`
3. Check stats: `ext_authz.denied` counter increasing
4. Enable trace logs to see exact denial reason
5. Check if filter is disabled: `ext_authz.disabled` counter

**Scenario 2: Auth service is unreachable**
1. Check `ext_authz.error` counter increasing
2. Check if `failure_mode_allow` is set correctly
3. Verify cluster configuration: `curl http://localhost:9901/clusters | grep ext_authz`
4. Check auth service logs for connection attempts
5. Verify DNS resolution: `nslookup <auth_host>`

**Scenario 3: Headers not being added/removed**
1. Enable trace logs to see header mutations
2. Check `ext_authz.invalid` counter (invalid responses are rejected)
3. Verify auth service is returning header mutations
4. Check `validate_mutations` and `decoder_header_mutation_rules` configs
5. Check allowed/disallowed header matchers in config

**Scenario 4: Performance issues (slow requests)**
1. Check `ext_authz.error` counter (timeouts count as errors)
2. Increase timeout: `grpc_service.timeout` or `http_service.server_uri.timeout`
3. Check auth service latency: examine cluster upstream request time stats
4. Check if `failure_mode_allow` is enabled (affects behavior on timeout)
5. Consider buffer settings if request body is large

### Filter State for Logging

The filter stores authorization metadata in `ExtAuthzLoggingInfo` at filter state key `<filter_name>`:

```cpp
// Available fields:
class ExtAuthzLoggingInfo {
  const absl::optional<ProtobufWkt::Struct>& filterMetadata();
  absl::optional<std::chrono::microseconds> latency();
  absl::optional<uint64_t> bytesSent();      // gRPC only
  absl::optional<uint64_t> bytesReceived();  // gRPC only
  Upstream::ClusterInfoConstSharedPtr clusterInfo();
  Upstream::HostDescriptionConstSharedPtr upstreamHost();
};
```

Enable via config: `emit_filter_state_stats: true`

### Dynamic Metadata

The auth service can return dynamic metadata that's propagated to downstream filters:

1. Check if `enable_dynamic_metadata_ingestion` is set to `true` (default)
2. Dynamic metadata namespace: `envoy.filters.http.ext_authz` (HTTP) or `envoy.filters.network.ext_authz` (Network)
3. Access in access logs via: `%FILTER_STATE(envoy.filters.http.ext_authz)%`

### Distributed Tracing

If distributed tracing is enabled:
1. Auth service calls create child spans
2. Span name: `ext_authz` (gRPC) or derived from HTTP request
3. Span tags include request/response attributes
4. Trace span contains timing information for auth latency

To enable:
```yaml
tracing:
  provider:
    name: envoy.tracers.zipkin
    typed_config:
      "@type": type.googleapis.com/envoy.config.trace.v3.ZipkinConfig
      # ... zipkin config
```

### Useful Debug Commands

```bash
# Check if ext_authz filter is in the filter chain
curl http://localhost:9901/config_dump | jq '.configs[].config | select(.name == "envoy.filters.http.ext_authz")'

# Monitor error rate
watch -n 1 'curl -s http://localhost:9901/stats | grep ext_authz.error'

# Check cluster health
curl http://localhost:9901/clusters | grep -A 20 ext_authz

# Check runtime overrides affecting ext_authz
curl http://localhost:9901/runtime | grep ext_authz

# Get detailed request/response info (if logs enabled)
tail -f /var/log/envoy/envoy.log | grep -i "ext_authz"
```

### Reading the Code for Issues

Key places to check when debugging:

1. **`ext_authz.cc` line ~244**: Initial auth check call setup
2. **`ext_authz.cc` line ~350-400**: Header/query mutation handling
3. **`ext_authz.cc` line ~810-830**: Error handling path
4. **`ext_authz_grpc_impl.cc`**: gRPC-specific response parsing
5. **`ext_authz_http_impl.cc`**: HTTP-specific response parsing
6. **`check_request_utils.cc`**: Request attribute extraction

---

## Summary

The ext_authz filter is a flexible authorization integration point in Envoy that:
- Delegates auth decisions to external services (gRPC or HTTP)
- Supports both HTTP and TCP/network-level authorization
- Handles failures gracefully with configurable modes
- Integrates with Envoy's broader ecosystem (tracing, stats, metadata, dynamic config)
- Is heavily tested with unit, integration, and fuzz tests
- Provides extensive observability through stats, logs, and filter state

For common issues, check the stats, enable trace logs, and verify auth service connectivity. The code is well-structured with clear separation between protocol implementations (gRPC vs HTTP) and filter logic.
