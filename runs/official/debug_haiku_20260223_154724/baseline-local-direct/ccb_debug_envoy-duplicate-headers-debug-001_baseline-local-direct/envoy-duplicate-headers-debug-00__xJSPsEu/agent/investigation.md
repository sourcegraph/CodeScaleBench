# Investigation Report: Duplicate Response Headers in Envoy Filter Pipeline

## Summary

Response headers configured via `response_headers_to_add` in route configuration are being duplicated in HTTP responses generated as local replies by the router filter. The root cause is that `finalizeResponseHeaders()` is invoked twice for local replies: once directly in `DownstreamFilterManager::sendLocalReplyViaFilterChain()` and again inside the router filter's `modify_headers_` callback, resulting in header parsers being applied twice and causing headers with `OVERWRITE_IF_EXISTS_OR_ADD` action to be added multiple times.

## Root Cause

The duplicate header issue stems from a design pattern where response header finalization was moved into the `modify_headers_` callback in the router filter (`source/common/router/router.cc:444-461`), but the filter manager's local reply path (`source/common/http/filter_manager.cc:1120-1145`) still directly calls `finalizeResponseHeaders()` before invoking the callback.

**The critical code paths:**

1. **Router filter initialization (`source/common/router/router.cc:444-461`)**: The `modify_headers_` callback is defined to call `route_entry_->finalizeResponseHeaders(headers, callbacks_->streamInfo())` at line 453.

2. **Upstream response handling (`source/common/router/router.cc:1794`)**: For normal upstream responses, the router calls `modify_headers_(*headers)` only once, avoiding double processing.

3. **Local reply generation (`source/common/http/filter_manager.cc:1120-1145`)**: When `sendLocalReplyViaFilterChain()` is invoked, it passes an `EncodeFunctions` callback that:
   - Directly calls `streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo())` at line 1125
   - Then calls `modify_headers(headers)` at line 1128, which invokes the router's callback again

This creates a double invocation of `finalizeResponseHeaders()` for local replies, causing response headers to be processed and added twice.

## Evidence

### Code References with Line Numbers

**1. Router Filter: modify_headers_ Callback Definition**
- File: `source/common/router/router.cc`
- Lines: 442-461
- Key code:
  ```cpp
  modify_headers_ = [this](Http::ResponseHeaderMap& headers) {
    if (route_entry_ == nullptr) {
      return;
    }
    if (modify_headers_from_upstream_lb_) {
      modify_headers_from_upstream_lb_(headers);
    }
    route_entry_->finalizeResponseHeaders(headers, callbacks_->streamInfo());  // LINE 453
    if (attempt_count_ == 0 || !route_entry_->includeAttemptCountInResponse()) {
      return;
    }
    headers.setEnvoyAttemptCount(attempt_count_);
  };
  ```

**2. Upstream Response Processing (Works Correctly)**
- File: `source/common/router/router.cc`
- Lines: 1790-1801
- Key code:
  ```cpp
  modify_headers_(*headers);  // LINE 1794 - Called once for upstream responses
  if (end_stream) {
    onUpstreamComplete(upstream_request);
  }
  callbacks_->encodeHeaders(std::move(headers), end_stream,
                            StreamInfo::ResponseCodeDetails::get().ViaUpstream);
  ```

**3. Local Reply Path (Double Invocation Issue)**
- File: `source/common/http/filter_manager.cc`
- Lines: 1109-1145
- Key code:
  ```cpp
  void DownstreamFilterManager::sendLocalReplyViaFilterChain(
      bool is_grpc_request, Code code, absl::string_view body,
      const std::function<void(ResponseHeaderMap& headers)>& modify_headers, bool is_head_request,
      const absl::optional<Grpc::Status::GrpcStatus> grpc_status, absl::string_view details) {
    Utility::sendLocalReply(
        state_.destroyed_,
        Utility::EncodeFunctions{
            [this, modify_headers](ResponseHeaderMap& headers) -> void {
              if (streamInfo().route() && streamInfo().route()->routeEntry()) {
                streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());  // LINE 1125
              }
              if (modify_headers) {
                modify_headers(headers);  // LINE 1128 - Router's callback called here
              }
            },
            // ... other lambdas ...
        },
        Utility::LocalReplyData{is_grpc_request, code, body, grpc_status, is_head_request});
  }
  ```

**4. Identical Issue in Direct Local Reply Path**
- File: `source/common/http/filter_manager.cc`
- Lines: 1147-1190
- Same pattern: `finalizeResponseHeaders()` at line 1158, then `modify_headers()` at line 1161

**5. Header Parser: Response Header Addition Logic**
- File: `source/common/router/header_parser.cc`
- Lines: 145-212
- `evaluateHeaders()` method processes `response_headers_to_add` entries and applies header mutations based on `append_action_` field
- For `OVERWRITE_IF_EXISTS_OR_ADD` action (line 197-198), it calls `headers.setReferenceKey()` to set the header
- Then at line 211, it calls `headers.addReferenceKey()` to add it
- When invoked twice, both operations execute twice, resulting in duplicate headers

**6. Route Entry Response Header Finalization**
- File: `source/common/router/config_impl.cc`
- Lines: 942-950
- Code:
  ```cpp
  void RouteEntryImplBase::finalizeResponseHeaders(Http::ResponseHeaderMap& headers,
                                                   const StreamInfo::StreamInfo& stream_info) const {
    for (const HeaderParser* header_parser : getResponseHeaderParsers(...)) {
      header_parser->evaluateHeaders(headers, {stream_info.getRequestHeaders(), &headers},
                                     stream_info);
    }
  }
  ```
  This iterates through all header parsers and calls `evaluateHeaders()` on each one.

**7. Header Value Option Proto Definition**
- File: `api/envoy/config/core/v3/base.proto`
- Contains `HeaderAppendAction` enum with values: `APPEND_IF_EXISTS_OR_ADD` (default), `ADD_IF_ABSENT`, `OVERWRITE_IF_EXISTS_OR_ADD`, `OVERWRITE_IF_EXISTS`
- The `append_action` field defaults to `APPEND_IF_EXISTS_OR_ADD`
- Deprecated `append` field (BoolValue) provides backward compatibility

## Affected Components

1. **source/common/router/** (Router Filter Implementation)
   - `router.cc`: Defines `modify_headers_` callback containing `finalizeResponseHeaders()` call
   - `config_impl.cc`: `RouteEntryImplBase::finalizeResponseHeaders()` method
   - `header_parser.cc`: `HeaderParser::evaluateHeaders()` method that applies headers
   - `header_parser.h`: Header parser class and entry structure

2. **source/common/http/** (HTTP Filter Manager)
   - `filter_manager.cc`: `DownstreamFilterManager::sendLocalReply()`, `sendLocalReplyViaFilterChain()`, `sendDirectLocalReply()`
   - `filter_manager.h`: Filter manager interface declarations

3. **source/extensions/filters/http/header_mutation/** (Header Mutation Filter)
   - Interacts with the filter chain during encoding phase
   - Processes response headers after router filter's `modify_headers_` callback

4. **api/envoy/config/core/v3/** (Protocol Buffer Definitions)
   - `base.proto`: `HeaderValueOption` message with `HeaderAppendAction` enum

## Causal Chain

1. **Symptom**: Response headers appear duplicated in access logs (e.g., `x-custom-trace: abc123` appears twice) when local replies are generated by the router filter (e.g., 504 upstream timeout)

2. **Intermediate Hop 1 - Router Filter Header Initialization**:
   - When a request enters the router filter's `decodeHeaders()` method, it creates a `modify_headers_` callback that captures the route entry and encapsulates the header finalization logic (router.cc:444-461)

3. **Intermediate Hop 2a - Upstream Response Path (No Issue)**:
   - For successful upstream responses, `onUpstreamHeaders()` calls `modify_headers_(*headers)` exactly once (router.cc:1794)
   - This single call properly applies all header modifications via `finalizeResponseHeaders()`
   - No duplication occurs

4. **Intermediate Hop 2b - Local Reply Path (Problem)**:
   - When router filter generates a local reply (e.g., cluster not found, overloaded, no healthy upstream), it calls `callbacks_->sendLocalReply()` with the `modify_headers_` callback as an argument (router.cc:522, 550, 750, 931, etc.)

5. **Intermediate Hop 3 - Filter Manager Local Reply Processing**:
   - `DownstreamFilterManager::sendLocalReply()` (filter_manager.cc:982-1053) determines the reply cannot start streaming through the filter chain or must be sent via the chain
   - For responses that need filter chain processing, it calls `sendLocalReplyViaFilterChain()` (filter_manager.cc:1109-1145)

6. **Intermediate Hop 4 - Double Header Finalization**:
   - `sendLocalReplyViaFilterChain()` creates an `EncodeFunctions` callback structure for `Http::Utility::sendLocalReply()`
   - The callback's header encoding function (lines 1123-1130):
     - First directly calls `streamInfo().route()->routeEntry()->finalizeResponseHeaders()` at line 1125
     - Then calls `modify_headers()` (the router's callback) at line 1128
   - Same pattern occurs in `sendDirectLocalReply()` (lines 1156-1162)

7. **Intermediate Hop 5 - Header Parser Double Application**:
   - `finalizeResponseHeaders()` calls `evaluateHeaders()` for each header parser configured for the route
   - Each header parser iterates through `headers_to_add_` entries (configured via `response_headers_to_add`)
   - For headers with `OVERWRITE_IF_EXISTS_OR_ADD` action:
     - `setReferenceKey()` sets/overwrites the header value (line 206)
     - `addReferenceKey()` adds another copy of the header (line 211)
   - When `finalizeResponseHeaders()` is called twice, all these operations happen twice
   - First call: Sets header value, then adds it (one instance)
   - Second call: Overwrites the same header key again, then adds another instance (resulting in two total)

8. **Root Cause - Architectural Mismatch**:
   - The router filter moved header finalization logic into the `modify_headers_` callback to centralize the logic
   - However, the filter manager's local reply path independently calls `finalizeResponseHeaders()` before invoking the callback
   - This creates double processing: once in filter manager's explicit call, once in router's callback
   - Upstream response path avoids this by calling `modify_headers_` directly without a separate `finalizeResponseHeaders()` call
   - Local reply path has both calls, causing duplication

## Recommendation

### Root Cause Fix Strategy

The local reply path in `DownstreamFilterManager` should not call `finalizeResponseHeaders()` directly. Instead:

1. **Option A (Preferred)**: Remove the direct `finalizeResponseHeaders()` call from the `EncodeFunctions` callback in `sendLocalReplyViaFilterChain()` and `sendDirectLocalReply()` (filter_manager.cc:1125 and 1158). Allow the router's `modify_headers_` callback to be the sole handler of response header finalization.

2. **Option B**: Modify the router filter to not include `finalizeResponseHeaders()` inside the `modify_headers_` callback, but instead have the filter manager call it uniformly for all response paths (both upstream and local replies).

### Diagnostic Steps

1. **Verify the issue**: Enable debug logging in `header_parser.cc` and `filter_manager.cc` to count how many times `evaluateHeaders()` is invoked for a given request.

2. **Trace the call stack**: Add ENVOY_STREAM_LOG statements at:
   - `finalizeResponseHeaders()` entry in `config_impl.cc:942`
   - `evaluateHeaders()` entry in `header_parser.cc:145`
   - The header encoding lambda in `filter_manager.cc:1123`
   - The `modify_headers` callback invocation in `filter_manager.cc:1128`

3. **Monitor header values**: Log the header map state:
   - Before the first `finalizeResponseHeaders()` call
   - After the first `finalizeResponseHeaders()` call
   - After the `modify_headers()` callback completes

4. **Compare with upstream path**: Run the same diagnostic on upstream response handling at `router.cc:1794` to confirm it's only called once.

### Testing Recommendations

1. Create a test case with `response_headers_to_add` configured with `OVERWRITE_IF_EXISTS_OR_ADD` action.
2. Trigger local replies via various router error conditions:
   - Cluster not found
   - No healthy upstream
   - Overloaded state
   - Request validation failures (bad request)
3. Verify that response headers appear exactly once, not duplicated.
4. Compare header counts between upstream responses and local replies to ensure parity.

## Additional Context

The issue is specific to local replies because of the architectural difference in how response headers are processed:

- **Upstream responses**: Flow through `onUpstreamHeaders()` → `modify_headers_()` → `encodeHeaders()`
  - Header finalization happens exactly once inside `modify_headers_`

- **Local replies**: Flow through `sendLocalReply()` → `sendLocalReplyViaFilterChain()` → `Utility::sendLocalReply()` → callback EncodeFunctions
  - Header finalization happens in two places: filter manager's explicit call + router's callback

The use of `OVERWRITE_IF_EXISTS_OR_ADD` action is particularly problematic because the header parser's logic of calling both `setReferenceKey()` and `addReferenceKey()` within the same `evaluateHeaders()` invocation already has unusual semantics. When invoked twice, it compounds the issue:

1. First invocation: `setReferenceKey("x-custom-trace", "abc123")` sets it, then `addReferenceKey()` adds it (now: one header)
2. Second invocation: `setReferenceKey("x-custom-trace", "abc123")` sets it again, then `addReferenceKey()` adds another copy (now: two headers with same value)

This behavior would be benign if `finalizeResponseHeaders()` were called only once, but the double call makes it visible as header duplication in the response.
