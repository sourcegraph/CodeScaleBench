# ext_authz Filter Handoff Document

## 1. Purpose

The **ext_authz** (external authorization) HTTP filter is an Envoy extension that delegates HTTP authorization decisions to an external authorization service. It acts as a gatekeeper in the HTTP filter chain, allowing operators to centralize authorization logic outside of Envoy.

**What it does:**
- Intercepts HTTP requests before they reach the upstream service
- Sends a `CheckRequest` to an external authorization service (via gRPC or HTTP)
- Based on the response, either allows the request to proceed, denies it, or fails gracefully depending on configuration
- Optionally modifies request/response headers based on the authorization server's response
- Supports buffering request bodies to pass to the authorization service
- Can modify query parameters on authorized requests

**Use cases:**
- Centralized API gateway authorization (JWT validation, policy enforcement)
- OAuth/OIDC token validation
- Web Application Firewall (WAF) integration
- Fine-grained access control policies
- Audit logging through response headers/metadata

## 2. Dependencies

### Upstream Dependencies

**Core Envoy Framework:**
- `envoy/http/filter.h` - HTTP filter interface (StreamDecoderFilter, StreamEncoderFilter)
- `envoy/stats/stats_macros.h` - Statistics framework
- `envoy/upstream/cluster_manager.h` - Cluster management for connecting to auth service
- `envoy/runtime/runtime.h` - Runtime feature flags for dynamic configuration

**Authorization Service Communication:**
- `envoy/service/auth/v3/external_auth.pb.h` - Protocol buffer definitions for CheckRequest/CheckResponse
- `envoy/grpc/async_client.h` / `envoy/http/async_client.h` - Async client interfaces for gRPC and HTTP
- `source/extensions/filters/common/ext_authz/ext_authz_grpc_impl.h` - gRPC client implementation
- `source/extensions/filters/common/ext_authz/ext_authz_http_impl.h` - HTTP client implementation

**Configuration & Parsing:**
- `envoy/extensions/filters/http/ext_authz/v3/ext_authz.pb.h` - Filter configuration protobuf
- `source/extensions/filters/http/common/factory_base.h` - Filter factory pattern

**Request/Response Handling:**
- `source/extensions/filters/common/ext_authz/check_request_utils.h` - Utilities to build CheckRequest from HTTP request
- `source/extensions/filters/common/mutation_rules/mutation_rules.h` - Validation for header/query parameter mutations
- `source/common/http/headers.h` - Header manipulation utilities

**Logging & Tracing:**
- `source/common/common/logger.h` - Logging macros
- `envoy/tracing/tracer.h` - Distributed tracing support

### Downstream Consumers

**What uses ext_authz:**
- **HTTP filter chain** - Configured via listeners in Envoy configuration
- **Route-specific configuration** - Per-route ext_authz overrides allow disabling per-route or customizing check settings
- **Other filters** - Can consume dynamic metadata injected by ext_authz
- **Access logs** - Filter state statistics are available to access loggers for observability

**Integration points:**
- Registered as `envoy.filters.http.ext_authz` filter factory (source/extensions/filters/http/ext_authz/config.cc:76)
- Can be chained with other HTTP filters (JWT auth, OAuth2, local_ratelimit, etc.)
- Publishes dynamic metadata under `envoy.filters.http.ext_authz` namespace

## 3. Relevant Components

### Core Implementation Files

#### **source/extensions/filters/http/ext_authz/ext_authz.h** (Header)
- **FilterConfig** - Configuration object holding all filter settings:
  - Failure mode handling (fail-open or fail-closed)
  - Request body buffering settings
  - Header mutation rules and validation flags
  - Statistics names and scopes
  - Dynamic metadata ingestion settings
  - Filter enabled/disabled runtime checks

- **FilterConfigPerRoute** - Per-route override settings:
  - Context extensions to add to CheckRequest
  - Per-route request body buffering settings
  - Ability to disable filter for specific routes

- **Filter** - Main filter implementation:
  - `decodeHeaders()` - Entry point, initiates auth check or buffers request
  - `decodeData()` - Buffers request body chunks until threshold or end-of-stream
  - `decodeTrailers()` - Flushes buffered request body when trailers arrive
  - `encodeHeaders()` / `encodeData()` - Applies response headers from auth service
  - `onComplete()` - Handles async response from auth service (core logic)

- **ExtAuthzLoggingInfo** - Filter state object for per-stream logging/statistics

#### **source/extensions/filters/http/ext_authz/ext_authz.cc** (Implementation)
- **FilterConfig constructor** (lines 64-160+) - Parses protobuf config, sets up matchers and validators
- **decodeHeaders()** (lines 258-309) - Checks if filter is enabled, decides whether to buffer or call auth service
- **decodeData()** (lines 311-329) - Handles request body buffering with watermark management
- **onComplete()** (lines 470-838) - **Critical logic**:
  - **CheckStatus::OK** (lines 501-744) - Authorized request:
    - Applies headers_to_set, headers_to_add, headers_to_append from response
    - Removes headers_to_remove
    - Modifies query parameters
    - Clears route cache if configured
    - Applies response headers to downstream response
    - Records `ext_authz.ok` stat
  - **CheckStatus::Denied** (lines 747-805) - Request denied:
    - Sends local reply with status from auth service response
    - Applies headers specified in denial response
    - Records `ext_authz.denied` stat
  - **CheckStatus::Error** (lines 808-835) - Auth service error:
    - If `failure_mode_allow=true`: Allows request and records `ext_authz.failure_mode_allowed` stat
    - If `failure_mode_allow=false`: Denies with 403 Forbidden (or configured status_on_error)
    - Optionally adds `x-envoy-auth-failure-mode-allowed: true` header
- **rejectResponse()** (lines 840+) - Validates mutations and returns 500 if invalid

#### **source/extensions/filters/http/ext_authz/config.h/cc** (Configuration & Factory)
- **ExtAuthzFilterConfig** factory class - Implements NamedHttpFilterConfigFactory
- `createFilterFactoryFromProtoWithServerContextTyped()` (config.cc:23-64):
  - Selects gRPC or HTTP client based on config
  - Creates filter instances for each connection
  - Default timeout: 200ms
- `createRouteSpecificFilterConfigTyped()` (config.cc:66-71) - Creates per-route configs

### Common ext_authz Infrastructure

#### **source/extensions/filters/common/ext_authz/ext_authz.h** (Interface)
- **Client** - Abstract interface for authorization clients (gRPC or HTTP)
  - `check()` - Async check request, callback may be synchronous (on-stack) or async
  - `cancel()` - Cancels inflight request

- **RequestCallbacks** - Callback interface filter implements:
  - `onComplete(ResponsePtr&& response)` - Called when check completes (implemented in Filter::onComplete)

- **Response** - Parsed authorization response:
  - `status` - OK/Denied/Error
  - `headers_to_set/add/append/remove` - Request header mutations
  - `response_headers_to_add/set/add_if_absent/overwrite_if_exists` - Response header mutations
  - `query_parameters_to_set/remove` - Query parameter mutations
  - `dynamic_metadata` - Protobuf struct for filter state
  - `body` / `status_code` - For denied responses

#### **source/extensions/filters/common/ext_authz/ext_authz_grpc_impl.h/cc** (gRPC Client)
- **GrpcClientImpl** - Unary gRPC client implementation
- `check()` (grpc_impl.cc:~100) - Initiates async gRPC CheckRequest
- `onSuccess()` - Parses CheckResponse, extracts headers/metadata
- `onFailure()` - Handles gRPC errors (timeout, connection failure, etc.)
- Uses typed async client wrapper around raw async client
- Preserves stream info for observability

#### **source/extensions/filters/common/ext_authz/ext_authz_http_impl.h/cc** (HTTP Client)
- **RawHttpClientImpl** - Raw HTTP client for non-gRPC auth services
- `check()` - Builds HTTP POST request to auth service
- `onSuccess()` - Parses HTTP response, extracts headers from configurable matchers
- `onFailure()` - Handles HTTP client errors
- Uses header matchers to select which response headers to apply

#### **source/extensions/filters/common/ext_authz/check_request_utils.h/cc** (Request Building)
- **CheckRequestUtils::createHttpCheck()** - Extracts request attributes and builds CheckRequest:
  - HTTP method, path, headers from request
  - TLS cert/session info if configured
  - Metadata from connections/routes
  - Request body (if buffered)
  - Peer certificate chain

## 4. Failure Modes

### Configuration-Level Failures

| Scenario | Default Behavior | Configurable? |
|----------|------------------|---------------|
| **Auth service unreachable** (no cluster or DNS resolution fails) | Fail-closed (deny request) | Yes - `failure_mode_allow` |
| **Connection timeout** (service too slow, default 200ms) | Fail-closed (deny request) | Yes - `failure_mode_allow` |
| **gRPC error** (service returned error code) | Fail-closed (deny request) | Yes - `failure_mode_allow` |
| **HTTP 5xx response** (server error) | Fail-closed (deny request) | Yes - `failure_mode_allow` |
| **Request body too large** (exceeds max_request_bytes) | Returns HTTP 413 Payload Too Large | N/A - hard limit |
| **Invalid header mutation** (from auth service) | Returns 500 Internal Server Error | Yes - `validate_mutations` |

### Request Processing Failures

**Header mutation validation** (ext_authz.cc:459-468):
- If `validate_mutations=true`, checks header names/values for valid characters
- If `decoder_header_mutation_rules` set, validates mutations against rules
- Invalid mutations → 500 error (rejectResponse), stat `ext_authz.invalid`

**Query parameter mutation validation** (ext_authz.cc:700-710):
- Checks for proper URL encoding
- If invalid → 500 error

**Filter state state machine** (ext_authz.h:384-389):
- **NotStarted** → **Calling** → **Complete** (or stays Calling if destroyed)
- If destroyed during Calling state, `onDestroy()` cancels the request
- Prevents use-after-free by tracking state

### Error Handling Flow

```
Authorization Service Error
    ↓
if failure_mode_allow:
    ↑ Allow request (record stat: ext_authz.failure_mode_allowed)
    ↑ Optionally add x-envoy-auth-failure-mode-allowed: true header
else:
    ↑ Deny request with status_on_error (default: 403 Forbidden)
    ↑ Record stat: ext_authz.error
    ↑ Set response flag: UnauthorizedExternalService
```

## 5. Testing

### Test Files Location

**Unit Tests:**
- `test/extensions/filters/http/ext_authz/ext_authz_test.cc` - Main filter unit tests (~2000+ lines)
  - Tests request/response flow with mocked client
  - Tests header/query parameter mutations
  - Tests failure mode handling
  - Tests buffering behavior
  - Tests per-route configuration overrides

- `test/extensions/filters/http/ext_authz/config_test.cc` - Configuration parsing tests

**Integration Tests:**
- `test/extensions/filters/http/ext_authz/ext_authz_integration_test.cc`
  - End-to-end tests with fake HTTP/gRPC backends
  - Tests complete request/response cycle
  - Tests with actual HTTP server and gRPC service stubs

**Fuzz Tests:**
- `test/extensions/filters/http/ext_authz/ext_authz_grpc_fuzz_test.cc` - gRPC path fuzzing
- `test/extensions/filters/http/ext_authz/ext_authz_http_fuzz_test.cc` - HTTP path fuzzing
- `test/extensions/filters/http/ext_authz/ext_authz_fuzz_lib.cc` - Shared fuzzing infrastructure

**Common ext_authz Tests:**
- `test/extensions/filters/common/ext_authz/` directory
  - Tests for gRPC client implementation
  - Tests for HTTP client implementation
  - Mocks for testing

### How to Run Tests

```bash
# Run all ext_authz tests
bazel test //test/extensions/filters/http/ext_authz/...

# Run specific test
bazel test //test/extensions/filters/http/ext_authz:ext_authz_test

# Run with verbose output
bazel test //test/extensions/filters/http/ext_authz:ext_authz_test --test_arg=--verbose

# Run integration tests
bazel test //test/extensions/filters/http/ext_authz:ext_authz_integration_test
```

### Test Coverage

- ✅ Authorization grant/deny/error scenarios
- ✅ Header mutations (set, add, append, remove)
- ✅ Query parameter mutations
- ✅ Request body buffering and watermarks
- ✅ Timeout and connection failures
- ✅ Per-route configuration merging
- ✅ Dynamic metadata ingestion
- ✅ Statistics emission
- ✅ Failure mode behaviors
- ✅ Invalid response validation
- ⚠️ Limited edge case coverage (e.g., large headers, many query params)

## 6. Debugging

### Observability

#### **Logs**
The filter uses Envoy's standard logging macros (`ENVOY_STREAM_LOG`):

```cpp
// From ext_authz.cc:
ENVOY_STREAM_LOG(trace, "ext_authz filter calling authorization server", *decoder_callbacks_);
ENVOY_STREAM_LOG(trace, "ext_authz filter rejected the request...", *decoder_callbacks_);
ENVOY_STREAM_LOG(trace, "ext_authz filter added header(s) to the request:", *decoder_callbacks_);
```

**To enable debug logs:**
```yaml
admin:
  address:
    socket_address:
      address: 127.0.0.1
      port_value: 9000

# In Envoy config, add:
logging:
  - name: envoy.filters.http.ext_authz
    level: trace
```

#### **Statistics**
Core statistics (ext_authz.cc:38-46):
- `ext_authz.ok` - Request authorized
- `ext_authz.denied` - Request denied by auth service
- `ext_authz.error` - Auth service unavailable/error
- `ext_authz.disabled` - Filter disabled for request
- `ext_authz.failure_mode_allowed` - Allowed due to failure_mode_allow
- `ext_authz.invalid` - Response validation failed
- `ext_authz.ignored_dynamic_metadata` - Dynamic metadata ingestion disabled

If `stat_prefix` configured (ext_authz.proto:13), stats include prefix: `ext_authz.{stat_prefix}.ok`

**View stats via admin endpoint:**
```bash
curl localhost:9000/stats | grep ext_authz
```

#### **Filter State (Per-Stream Logging)**
If `emit_filter_state_stats=true` (ext_authz.proto:309):

Filter state object stored as `ExtAuthzLoggingInfo` contains:
- `latency` - Duration of auth check (microseconds)
- `bytes_sent` - Bytes sent to auth service (gRPC only)
- `bytes_received` - Bytes received from auth service (gRPC only)
- `cluster_info` - Upstream cluster handling auth service
- `upstream_host` - Specific host that handled request
- `filter_metadata` - Custom metadata from config

Access in access logs: `%FILTER_STATE(envoy.filters.http.ext_authz)%`

#### **Response Flags**
When ext_authz denies/errors:
- `response_flag` = `UnauthorizedExternalService` (set in onComplete for Denied/Error cases)
- Available in access logs as `%RESPONSE_FLAG%`

#### **Tracing**
The filter integrates with Envoy's distributed tracing:
- Creates child span in auth service cluster
- Span name: Service method name (e.g., `envoy.service.auth.v3.Authorization/Check`)
- Useful for visualizing auth service latency in traces

### Common Issues & Debugging Steps

#### **1. Authorization Requests Timing Out**
**Symptoms:** Requests hang, then return 403
**Debug steps:**
1. Check auth service cluster is healthy:
   ```bash
   curl localhost:9000/clusters | grep ext_authz
   ```
2. Verify service is responding:
   ```bash
   grpcurl -d '{}' ext_authz-service:9001 envoy.service.auth.v3.Authorization/Check
   ```
3. Check timeout configured (default 200ms):
   ```yaml
   grpc_service:
     envoy_grpc:
       cluster_name: ext_authz_server
     timeout: 1s  # Increase if service is slow
   ```
4. Enable trace logs and look for "ext_authz filter calling authorization server"

#### **2. Headers Not Being Modified**
**Symptoms:** Auth service returns headers but they don't appear in request
**Debug steps:**
1. Verify `headers_to_set`/`headers_to_add` in auth response (check proto)
2. If using HTTP service, check response header matchers:
   ```yaml
   http_service:
     authorization_response:
       allowed_upstream_headers:
         patterns:
           - name: "custom-auth-header"
   ```
3. For gRPC, all response headers are allowed by default
4. Enable mutation validation to catch invalid headers:
   ```yaml
   validate_mutations: true
   ```

#### **3. "failure_mode_allowed" Always Triggering**
**Symptoms:** Stats show high failure_mode_allowed rate
**Debug steps:**
1. Check auth service connectivity:
   ```bash
   curl localhost:9000/stats | grep upstream_rq_pending
   ```
2. Look for errors in logs (enable trace level)
3. Check auth service is returning valid responses
4. Verify no network policies are blocking Envoy → auth service

#### **4. Invalid Header/Query Parameter Mutations**
**Symptoms:** Errors with "Rejected invalid header" or "Rejecting invalid header"
**Debug steps:**
1. Enable `validate_mutations: true` to catch issues early
2. Check auth service isn't returning headers with:
   - Non-ASCII characters (unless using encode_raw_headers)
   - Invalid header names (lowercase only, alphanumeric + hyphen)
   - Headers trying to modify pseudo-headers (`:path`, `:method`, etc.)
3. Enable trace logs to see which header is invalid

#### **5. Request Not Being Authorized (Skipped)**
**Symptoms:** Filter doesn't call auth service
**Debug steps:**
1. Check if filter is disabled per-route:
   ```yaml
   route_config:
     routes:
     - match:
         prefix: "/health"
       typed_per_filter_config:
         envoy.filters.http.ext_authz:
           "@type": type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthzPerRoute
           disabled: true
   ```
2. Check `filter_enabled` runtime fraction:
   ```yaml
   filter_enabled:
     runtime_key: ext_authz.enabled
     default_value:
       numerator: 100
       denominator: HUNDRED
   ```
3. Check metadata matcher (`filter_enabled_metadata`)
4. Logs should show "ext_authz filter skipped" or similar

### Performance Considerations

**Latency:**
- Default timeout 200ms - increase if auth service is slow
- Serial processing - auth check completes before upstream connection
- Consider async auth checks (not currently supported)

**Memory:**
- Request buffering - `max_request_bytes` limits buffered request size (prevents OOM)
- Large headers list - careful with many `headers_to_set` operations

**CPU:**
- Header matching/validation - O(n) header count
- Mutation validation - regex matching on header names/values

### Useful Debug Config

```yaml
http_filters:
- name: envoy.filters.http.ext_authz
  typed_config:
    "@type": type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthz
    grpc_service:
      envoy_grpc:
        cluster_name: ext_authz_server
      timeout: 1s
    # Enable all observability
    failure_mode_allow: false
    validate_mutations: true
    emit_filter_state_stats: true
    stat_prefix: debug
    # Include useful context for auth service
    include_peer_certificate: true
    include_tls_session: true
    with_request_body:
      max_request_bytes: 8192
```
