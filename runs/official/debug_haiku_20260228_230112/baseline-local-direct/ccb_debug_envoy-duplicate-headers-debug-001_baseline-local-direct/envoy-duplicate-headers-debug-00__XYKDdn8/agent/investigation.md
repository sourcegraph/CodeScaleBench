# Investigation Report: Duplicate Response Headers in Envoy Filter Pipeline

## Summary

Response headers configured via `response_headers_to_add` in route configuration are being duplicated when the router filter generates local replies (e.g., upstream timeout, no cluster found). The root cause is a double invocation of `finalizeResponseHeaders()` in the filter manager's local reply code path—the function is called both directly in a header modification closure AND as part of the router filter's `modify_headers_` callback that is also passed to the same closure, resulting in headers being added twice to the response.

## Root Cause

**Primary Issue**: Double invocation of `finalizeResponseHeaders()` when local replies are sent.

**File**: `source/common/http/filter_manager.cc`
**Functions**: `sendLocalReplyViaFilterChain()` (line 1109) and `sendDirectLocalReply()` (line 1147)

**Mechanism**:
Both functions create a closure (lines 1123-1129 in `sendLocalReplyViaFilterChain` and 1156-1162 in `sendDirectLocalReply`) that:
1. **Line 1125/1158**: Directly calls `streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo())`
2. **Line 1128/1161**: Calls `modify_headers(headers)` callback, which itself contains another call to `finalizeResponseHeaders()`

When the router filter passes its `modify_headers_` callback to `sendLocalReply()`, both calls occur in sequence on the same response header map, causing response headers from `response_headers_to_add` to be applied twice.

## Evidence

### Code References

**1. Router Filter - modify_headers_ Lambda Definition**
File: `source/common/router/router.cc` (lines 444-461)
```cpp
modify_headers_ = [this](Http::ResponseHeaderMap& headers) {
  if (route_entry_ == nullptr) {
    return;
  }
  if (modify_headers_from_upstream_lb_) {
    modify_headers_from_upstream_lb_(headers);
  }
  route_entry_->finalizeResponseHeaders(headers, callbacks_->streamInfo());  // <-- FIRST CALL
  if (attempt_count_ == 0 || !route_entry_->includeAttemptCountInResponse()) {
    return;
  }
  headers.setEnvoyAttemptCount(attempt_count_);
};
```

**2. Router Filter - sendLocalReply with modify_headers_**
File: `source/common/router/router.cc` (line 522)
```cpp
callbacks_->sendLocalReply(route_entry_->clusterNotFoundResponseCode(), "", modify_headers_,
                           absl::nullopt,
                           StreamInfo::ResponseCodeDetails::get().ClusterNotFound);
```

**3. Filter Manager - Double Invocation in sendLocalReplyViaFilterChain**
File: `source/common/http/filter_manager.cc` (lines 1120-1130)
```cpp
Utility::sendLocalReply(
  state_.destroyed_,
  Utility::EncodeFunctions{
    [this, modify_headers](ResponseHeaderMap& headers) -> void {
      if (streamInfo().route() && streamInfo().route()->routeEntry()) {
        streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());  // <-- FIRST CALL
      }
      if (modify_headers) {
        modify_headers(headers);  // <-- SECOND CALL (nested inside modify_headers_ lambda)
      }
    },
    // ... other lambdas
  },
  // ...
);
```

**4. Filter Manager - Same Double Invocation in sendDirectLocalReply**
File: `source/common/http/filter_manager.cc` (lines 1156-1162)
```cpp
[this, modify_headers](ResponseHeaderMap& headers) -> void {
  if (streamInfo().route() && streamInfo().route()->routeEntry()) {
    streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());  // <-- FIRST CALL
  }
  if (modify_headers) {
    modify_headers(headers);  // <-- SECOND CALL
  }
}
```

### Header Parser Logic

**File**: `source/common/router/header_parser.cc` (lines 53-76, 182-200)

The header parser processes `append_action` configuration:
- Lines 58-71: Handles both deprecated `append` BoolValue and newer `append_action` enum
- Lines 182-200: In `evaluateHeaders()`, applies headers based on `append_action`:
  - `APPEND_IF_EXISTS_OR_ADD`: Calls `headers.addReferenceKey()` (duplicates on second invocation)
  - `OVERWRITE_IF_EXISTS_OR_ADD`: Calls `headers.setReferenceKey()` (still creates two values on two calls)

Even when using `OVERWRITE_IF_EXISTS_OR_ADD`, the second invocation of `finalizeResponseHeaders()` still results in the header being added because the overwrite semantics only apply within a single `evaluateHeaders()` call, not across two separate calls.

### Proto Definitions

**File**: `api/envoy/config/core/v3/base.proto`

HeaderValueOption message defines:
- `append_action` enum (lines ~40-55): Default is `APPEND_IF_EXISTS_OR_ADD` (enum value 0)
- `append` deprecated field (BoolValue): Legacy field for setting append behavior
- Handler in header_parser.cc (line 60) ensures mutual exclusivity: if both are set and not equal to default, raises error

## Affected Components

1. **source/common/router/** - Router filter that generates local replies and defines `modify_headers_` callback
2. **source/common/http/filter_manager.cc** - Filter manager's local reply path that invokes both direct `finalizeResponseHeaders()` and `modify_headers_` callback
3. **source/common/router/header_parser.cc** - Parses and applies response headers with `append_action` semantics
4. **api/envoy/config/core/v3/base.proto** - Defines HeaderValueOption proto with `append_action` enum

## Causal Chain

1. **Configuration**: User specifies `response_headers_to_add` in route config with `append_action: OVERWRITE_IF_EXISTS_OR_ADD`

2. **Request Processing - Decode Phase**:
   - Router filter's `decodeHeaders()` is called
   - `modify_headers_` lambda is created (line 444-461 in router.cc) containing call to `finalizeResponseHeaders()` at line 453

3. **Local Reply Trigger**:
   - Router detects error condition (e.g., cluster not found, upstream timeout)
   - Calls `callbacks_->sendLocalReply(..., modify_headers_, ...)` (line 522 in router.cc)

4. **Filter Manager - sendLocalReply Entry**:
   - `DownstreamFilterManager::sendLocalReply()` (line 982 in filter_manager.cc) is called with `modify_headers_` callback from router

5. **Filter Manager - Local Reply Path Decision**:
   - Filter manager checks response state (lines 1012-1043)
   - For local replies sent during request decoding, routes to `sendLocalReplyViaFilterChain()` (line 1031)

6. **CRITICAL: Double Call Point**:
   - `sendLocalReplyViaFilterChain()` (line 1109) creates closure with:
     - **First call** (line 1125): `streamInfo().route()->routeEntry()->finalizeResponseHeaders()`
     - **Second call** (line 1128): `modify_headers(headers)` which contains another `finalizeResponseHeaders()` at router.cc:453

7. **Response Header Application**:
   - HeaderParser's `evaluateHeaders()` (line 145 in header_parser.cc) processes headers twice:
     - First invocation (line 1125): Adds header `x-custom-trace: abc123`
     - Second invocation (line 1128 via modify_headers_): Adds header again `x-custom-trace: abc123`
   - For `APPEND_IF_EXISTS_OR_ADD`: Uses `addReferenceKey()` which appends, resulting in duplicate
   - For `OVERWRITE_IF_EXISTS_OR_ADD`: Uses `setReferenceKey()` within each call, but two separate calls result in two values in HeaderMap

8. **Final Response**: Duplicate headers appear in response sent to client

## Interaction Between sendLocalReply and modify_headers_

The design pattern creates the double invocation:

1. **Router Filter Design**: The router encapsulates all response header modifications in `modify_headers_` lambda to apply them uniformly to all responses (both upstream proxied and local replies)

2. **Filter Manager Assumption**: When calling `sendLocalReply()`, the filter manager assumes it needs to call `finalizeResponseHeaders()` to apply route-level response headers

3. **Redundant Pattern**: The filter manager then ALSO calls the `modify_headers_` callback, not realizing that for router-generated local replies, this callback already contains the `finalizeResponseHeaders()` call

4. **Result**: For router-generated local replies specifically, the headers are applied twice; for local replies from other filters without `modify_headers_`, they are applied only once by the filter manager

## Role of append_action / append Proto Fields

**File**: `source/common/router/header_parser.cc` (lines 53-76)

The proto handling creates potential for defaults:
- `append` field is deprecated BoolValue (default: nil/false)
- `append_action` field has enum default: `APPEND_IF_EXISTS_OR_ADD` (value 0)
- When only `append_action` is set: Used directly as-is
- When `append` is set: Converted to appropriate `append_action` (lines 66-68)
- Proto default behavior means if neither is explicitly set, `APPEND_IF_EXISTS_OR_ADD` is the implicit default

The double invocation bypasses these safeguards because even `OVERWRITE_IF_EXISTS_OR_ADD` only overwrites within a single `evaluateHeaders()` call. Two separate calls result in:
```
First call:  headers = {x-custom-trace: abc123}
Second call: headers = {x-custom-trace: abc123, x-custom-trace: abc123}
```

## Filter Manager's Encode Path

**Files**:
- `source/common/http/filter_manager.h` (lines 73-100)
- `source/common/http/filter_manager.cc` (lines 922-953, 1244-1333)

The encoder filter chain iterates in **reverse order** using `reverse_iterator`:
- StreamEncoderFilters uses `rbegin()` and `rend()` (line 96)
- Comment explains: if filters configured as A, B, C, then encoder chain iterates C, B, A
- When local reply is sent via `sendLocalReplyViaFilterChain()`, it calls `encodeHeaders(nullptr, ...)` which starts iteration from `encoder_filters_.begin()` (line 943 in commonEncodePrefix)
- This begins the encoding path through all encoder filters in reverse order

However, the router filter doesn't implement `encodeHeaders()`, so it doesn't get re-invoked in the encoding path. The double application comes purely from the filter manager's sendLocalReplyViaFilterChain closure calling both `finalizeResponseHeaders()` directly AND via the `modify_headers_` callback.

## Recommendation

**Root Fix**: Avoid calling `finalizeResponseHeaders()` directly in `sendLocalReplyViaFilterChain()` and `sendDirectLocalReply()` when a `modify_headers` callback is provided. The callback should be responsible for all header modifications.

**Diagnostic Steps**:

1. Trace local reply code path by adding logs at:
   - `filter_manager.cc:1125` and `1128` to track both invocations
   - `router.cc:453` to confirm `finalizeResponseHeaders()` is called twice

2. Search git history for commit that moved `finalizeResponseHeaders()` into the filter manager's `sendLocalReplyViaFilterChain()` closure (likely within last 2-3 major releases)

3. Verify the pattern: grep all calls to `sendLocalReply()` in router filter to identify which ones pass `modify_headers_` callback

**Proposed Fix Strategy**:
- Either:
  a) Remove direct `finalizeResponseHeaders()` call from filter manager's closure (line 1125), letting only `modify_headers_` callback handle it
  b) OR have router filter pass `nullptr` for modify_headers when it already plans to apply headers via another mechanism
  c) OR mark the closure to skip `finalizeResponseHeaders()` if it will be called by the modify_headers callback

**Testing**: Create unit test with route `response_headers_to_add` and trigger local reply via cluster not found, verifying headers appear exactly once in response.
