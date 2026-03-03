# Investigation Report: Duplicate Response Headers in Envoy Filter Pipeline

## Summary

Response headers configured via `response_headers_to_add` in route configuration are being **duplicated in local reply responses** because `finalizeResponseHeaders()` is called twice through different code paths: once directly in `sendLocalReplyViaFilterChain()` and again indirectly through the `modify_headers_` callback from the router filter. This double invocation applies the same header transformations twice, resulting in duplicate headers for local replies (timeouts, connection failures, etc.) while normal proxied upstream responses remain unaffected.

## Root Cause

**Double invocation of `finalizeResponseHeaders()` specific to the local reply code path.**

The causal mechanism:
1. **Initial Setup (router.cc:444-461)**: The router filter's `decodeHeaders()` method creates a `modify_headers_` lambda closure that captures `this` and calls `route_entry_->finalizeResponseHeaders()` (line 453)
2. **Local Reply Initiated (router.cc:1405-1414)**: When the router filter needs to send a local reply (e.g., upstream timeout in `onUpstreamAbort()`), it calls `callbacks_->sendLocalReply()` passing a callback that invokes `modify_headers_(headers)`
3. **First Finalization (filter_manager.cc:1120-1129)**: In `sendLocalReplyViaFilterChain()`, Envoy creates a lambda that:
   - Calls `streamInfo().route()->routeEntry()->finalizeResponseHeaders()` directly at line 1125
   - Then calls the `modify_headers` callback (the one from step 2) at line 1128
4. **Second Finalization (router.cc:453)**: The callback from step 2 executes the `modify_headers_` lambda from step 1, which calls `finalizeResponseHeaders()` again
5. **Result**: `finalizeResponseHeaders()` is invoked twice on the same response header map, applying all header transformations (including `response_headers_to_add`) twice

For upstream responses that are **not** local replies, `modify_headers_` is only invoked once during normal response processing, so duplicates do not occur.

## Evidence

### Code Path Evidence

**Router Filter Setup (source/common/router/router.cc:444-461)**:
```cpp
modify_headers_ = [this](Http::ResponseHeaderMap& headers) {
  if (route_entry_ == nullptr) {
    return;
  }
  if (modify_headers_from_upstream_lb_) {
    modify_headers_from_upstream_lb_(headers);
  }
  route_entry_->finalizeResponseHeaders(headers, callbacks_->streamInfo());  // LINE 453
  // ... attempt count logic ...
};
```

**Local Reply Invocation (source/common/router/router.cc:1405-1414)**:
```cpp
void Filter::onUpstreamAbort(Http::Code code, StreamInfo::CoreResponseFlag response_flags,
                             absl::string_view body, bool dropped, absl::string_view details) {
  // ...
  callbacks_->sendLocalReply(
      code, body,
      [dropped, this](Http::ResponseHeaderMap& headers) {  // Anonymous callback
        if (dropped && !config_->suppress_envoy_headers_) {
          headers.addReference(Http::Headers::get().EnvoyOverloaded, ...);
        }
        modify_headers_(headers);  // LINE 1412: Calls router filter's lambda
      },
      absl::nullopt, details);
}
```

**FilterManager's Local Reply Finalization (source/common/http/filter_manager.cc:1120-1129)**:
```cpp
void DownstreamFilterManager::sendLocalReplyViaFilterChain(
    bool is_grpc_request, Code code, absl::string_view body,
    const std::function<void(ResponseHeaderMap& headers)>& modify_headers, ...) {
  // ...
  Utility::sendLocalReply(
      state_.destroyed_,
      Utility::EncodeFunctions{
          [this, modify_headers](ResponseHeaderMap& headers) -> void {
            if (streamInfo().route() && streamInfo().route()->routeEntry()) {
              streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());  // LINE 1125
            }
            if (modify_headers) {
              modify_headers(headers);  // LINE 1128: Calls the callback that calls modify_headers_
            }
          },
          // ... other encode functions ...
      },
      // ...
  );
}
```

**Identical Pattern in Prepare Path (source/common/http/filter_manager.cc:1070-1078)**:
```cpp
prepared_local_reply_ = Utility::prepareLocalReply(
    Utility::EncodeFunctions{
        [this, modify_headers](ResponseHeaderMap& headers) -> void {
          if (streamInfo().route() && streamInfo().route()->routeEntry()) {
            streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());  // LINE 1074
          }
          if (modify_headers) {
            modify_headers(headers);  // LINE 1077
          }
        },
        // ...
    },
    // ...
);
```

### Header Transformation Evidence

**Header Parser's `evaluateHeaders()` (source/common/router/header_parser.cc:139-213)**:

When `finalizeResponseHeaders()` calls `header_parser->evaluateHeaders()`, the logic processes headers based on `append_action_`:

```cpp
void HeaderParser::evaluateHeaders(Http::HeaderMap& headers,
                                   const Formatter::HttpFormatterContext& context,
                                   const StreamInfo::StreamInfo* stream_info) const {
  // ... remove headers ...
  for (const auto& [key, entry] : headers_to_add_) {
    // ... format value ...
    switch (entry->append_action_) {
      case HeaderValueOption::APPEND_IF_EXISTS_OR_ADD:
        headers_to_add.emplace_back(key, value);  // Will call addReferenceKey
        break;
      case HeaderValueOption::ADD_IF_ABSENT:
        if (headers.get(key).empty()) {
          headers_to_add.emplace_back(key, value);
        }
        break;
      case HeaderValueOption::OVERWRITE_IF_EXISTS_OR_ADD:
        headers_to_overwrite.emplace_back(key, value);  // Will call setReferenceKey
        break;
    }
  }
  // First overwrite
  for (const auto& header : headers_to_overwrite) {
    headers.setReferenceKey(header.first, header.second);  // LINE 206
  }
  // Then add
  for (const auto& header : headers_to_add) {
    headers.addReferenceKey(header.first, header.second);  // LINE 211
  }
}
```

**Proto Definition (api/envoy/config/core/v3/base.proto:429-476)**:

The proto defines `HeaderAppendAction`:
- `APPEND_IF_EXISTS_OR_ADD = 0` (default): Appends comma-concatenated (for inline headers) or as duplicate headers
- `ADD_IF_ABSENT = 1`: Only adds if header doesn't exist
- `OVERWRITE_IF_EXISTS_OR_ADD = 2`: Overwrites existing or adds new
- `OVERWRITE_IF_EXISTS = 3`: Only overwrites existing

When `append_action_` is `APPEND_IF_EXISTS_OR_ADD`, calling `addReferenceKey()` twice on the same header results in the header being appended twice. When it's `OVERWRITE_IF_EXISTS_OR_ADD`, `setReferenceKey()` should replace, but the double call still means the header transformation is processed twice.

### Why Local Replies are Affected but Not Upstream Responses

**Local Reply Path**:
- `sendLocalReply()` → `sendLocalReplyViaFilterChain()` → Creates lambda that calls `finalizeResponseHeaders()` AND the `modify_headers_` callback
- `modify_headers_` callback also calls `finalizeResponseHeaders()` via router filter's lambda
- **Result: `finalizeResponseHeaders()` called twice**

**Upstream Response Path**:
- Headers received from upstream go directly to `onUpstreamHeaders()`
- Response headers are finalized during normal encoding via the filter chain
- `modify_headers_` is used in `encodeHeaders()` but is only invoked once
- **Result: `finalizeResponseHeaders()` called once**

## Affected Components

The causal chain spans these packages:

1. **source/common/router/** (`router.cc`, `router.h`):
   - `Filter::decodeHeaders()`: Creates `modify_headers_` lambda
   - `Filter::onUpstreamAbort()`, `onPerTryTimeoutCommon()`, `onSoftPerTryTimeout()`, `onUpstreamTimeoutAbort()`: Calls `sendLocalReply()` with `modify_headers_` callback
   - These methods are entry points for all local reply generation

2. **source/common/http/filter_manager.cc** (`filter_manager.h`):
   - `DownstreamFilterManager::sendLocalReply()`: Entry point for local reply handling
   - `DownstreamFilterManager::sendLocalReplyViaFilterChain()`: Creates lambda that calls `finalizeResponseHeaders()` directly (line 1125)
   - `DownstreamFilterManager::prepareLocalReplyViaFilterChain()`: Creates similar lambda (line 1074)
   - These are the code sections that introduce the first `finalizeResponseHeaders()` call for local replies

3. **source/common/router/config_impl.cc** (`config_impl.h`):
   - `RouteEntryImplBase::finalizeResponseHeaders()`: The function being called twice
   - Iterates through header parsers and calls `evaluateHeaders()` on each

4. **source/common/router/header_parser.cc** (`header_parser.h`):
   - `HeaderParser::evaluateHeaders()`: Applies the `response_headers_to_add` transformations
   - `HeadersToAddEntry` constructor: Parses `HeaderValueOption` proto, handles proto field compatibility (lines 53-76)
   - The `append_action_` field (proto field 3) defaults to `APPEND_IF_EXISTS_OR_ADD` per proto comments

5. **api/envoy/config/core/v3/base.proto**:
   - `HeaderValueOption.HeaderAppendAction` enum definition
   - `HeaderValueOption.append_action` field (line 476) with default `APPEND_IF_EXISTS_OR_ADD`
   - `HeaderValueOption.append` field (line 469) - deprecated BoolValue with default `false`

## Causal Chain

```
Symptom: Duplicate headers in local reply responses
    ↓
Upstream timeout/error occurs (onUpstreamAbort, onPerTryTimeout, etc.)
    ↓
Router filter calls sendLocalReply() with modify_headers_ callback
    ↓
FilterManager's sendLocalReplyViaFilterChain() creates wrapper lambda
    ↓
Wrapper lambda [1] calls finalizeResponseHeaders() directly (filter_manager.cc:1125)
    ↓
Wrapper lambda [1] then calls modify_headers callback
    ↓
Router's modify_headers_ lambda [2] calls finalizeResponseHeaders() again (router.cc:453)
    ↓
Both finalizeResponseHeaders() calls invoke HeaderParser::evaluateHeaders()
    ↓
Header transformations from response_headers_to_add applied twice
    ↓
For APPEND_IF_EXISTS_OR_ADD: addReferenceKey() called twice → header appears twice
For OVERWRITE_IF_EXISTS_OR_ADD: setReferenceKey() called twice → transformer runs twice
    ↓
Final response contains duplicate header values in access log
```

## Recommendation

### Root Cause Analysis

The architectural issue is that `sendLocalReplyViaFilterChain()` and `prepareLocalReplyViaFilterChain()` were designed to call `finalizeResponseHeaders()` directly (as a convenience), but this violates the Single Responsibility Principle when combined with the `modify_headers_` callback pattern that also calls `finalizeResponseHeaders()`.

The historical context: The `modify_headers_` callback was created to ensure route-level header modifications are applied consistently to both upstream responses and local replies. However, when the local reply code path was updated to call `finalizeResponseHeaders()` directly in the filter manager (lines 1074-1075, 1125), it created a double-call scenario because the `modify_headers_` callback still also calls `finalizeResponseHeaders()`.

### Fix Strategies

**Option A (Recommended)**: Remove the direct `finalizeResponseHeaders()` call from `sendLocalReplyViaFilterChain()` and `prepareLocalReplyViaFilterChain()` (filter_manager.cc:1074-1075, 1125). Let only the `modify_headers_` callback handle finalization. This maintains the single call pattern.

**Option B**: Create a flag in the `modify_headers_` callback to skip finalization if it's already been done, preventing duplicate execution.

**Option C**: Separate the `modify_headers_` callback into two concerns: route finalization (applied once) and load balancer header modifications (applied separately), ensuring each is invoked exactly once.

### Diagnostic Steps

1. **Verify the double invocation**: Add logging/tracing at router.cc:453 and filter_manager.cc:1125 to confirm `finalizeResponseHeaders()` is being called twice for local reply scenarios.

2. **Identify affected scenarios**:
   - Upstream timeouts (global or per-try)
   - No healthy upstream
   - Cluster not found
   - Request timeout
   - Any scenario where router calls `sendLocalReply()` directly

3. **Test with different append_action values**:
   - Headers with `APPEND_IF_EXISTS_OR_ADD` will show clearly as duplicates
   - Headers with `OVERWRITE_IF_EXISTS_OR_ADD` may not show duplicates but transformer logic runs twice (performance impact)

4. **Verify fix doesn't break upstream response path**: Ensure normal upstream response processing still properly applies route header modifications exactly once.
