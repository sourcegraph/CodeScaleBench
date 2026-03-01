# Investigation Report: Duplicate Response Headers in Envoy Local Replies

## Summary

Response headers configured via `response_headers_to_add` in route configuration are being duplicated in Envoy local replies (e.g., upstream timeout, cluster not found). The root cause is that `finalizeResponseHeaders()` is being called twice in the local reply processing path: once in the filter manager's wrapper lambda created for local reply preparation, and potentially again through the response encoding pipeline when headers flow through the route entry processing.

## Root Cause

The duplicate invocation stems from a refactoring that moved header finalization into the filter manager's local reply processing pipeline. When `sendLocalReply()` is invoked by the router filter, the filter manager creates an `EncodeFunctions` lambda that unconditionally calls `route_entry_->finalizeResponseHeaders()`, combined with how the response headers are subsequently processed through the filter encoding chain.

### Specific Mechanism

**File: `source/common/http/filter_manager.cc`**

Lines 1072-1078 (prepareLocalReplyViaFilterChain):
```cpp
[this, modify_headers](ResponseHeaderMap& headers) -> void {
  if (streamInfo().route() && streamInfo().route()->routeEntry()) {
    streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());
  }
  if (modify_headers) {
    modify_headers(headers);
  }
}
```

Lines 1123-1129 (sendLocalReplyViaFilterChain) and lines 1156-1162 (sendDirectLocalReply) contain identical lambda patterns.

**File: `source/common/router/router.cc`**

Lines 444-459 - Router initializes `modify_headers_` lambda:
```cpp
modify_headers_ = [this](Http::ResponseHeaderMap& headers) {
  if (route_entry_ == nullptr) {
    return;
  }
  if (modify_headers_from_upstream_lb_) {
    modify_headers_from_upstream_lb_(headers);
  }
  if (attempt_count_ == 0 || !route_entry_->includeAttemptCountInResponse()) {
    return;
  }
  headers.setEnvoyAttemptCount(attempt_count_);
};
```

Lines 1403-1412 - Router calls sendLocalReply on upstream abort (timeout, connection failure):
```cpp
callbacks_->sendLocalReply(
    code, body,
    [dropped, this](Http::ResponseHeaderMap& headers) {
      if (dropped && !config_->suppress_envoy_headers_) {
        headers.addReference(Http::Headers::get().EnvoyOverloaded,
                             Http::Headers::get().EnvoyOverloadedValues.True);
      }
      modify_headers_(headers);
    },
    absl::nullopt, details);
```

## Evidence

### Call Chain for Local Reply Processing

1. **Router Filter Initiates Local Reply** (`router.cc:1403-1412` or `router.cc:520`)
   - Router calls `callbacks_->sendLocalReply()` with either:
     - A lambda wrapping `modify_headers_` (for upstream abort cases)
     - `modify_headers_` directly (for no cluster found case)

2. **Filter Manager Wraps Headers** (`filter_manager.cc:982-1032`)
   - `DownstreamFilterManager::sendLocalReply()` is invoked
   - Based on execution state, routes to:
     - `prepareLocalReplyViaFilterChain()` (if in decoding phase)
     - `sendLocalReplyViaFilterChain()` (if not decoding)
     - `sendDirectLocalReply()` (if response already started)

3. **Header Finalization Applied** (`filter_manager.cc:1070-1093`)
   - `prepareLocalReplyViaFilterChain()` creates `EncodeFunctions` with modify_headers_ lambda
   - This lambda at line 1074 calls: `streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo())`
   - Then calls the passed-in `modify_headers` parameter

4. **Headers Prepared** (`utility.cc:709-780`)
   - `Utility::prepareLocalReply()` invokes `encode_functions.modify_headers_` at line 719
   - This applies `finalizeResponseHeaders` which evaluates all header parsers
   - Header parsers apply `response_headers_to_add` configuration

5. **Headers Encoded Through Filter Chain** (`filter_manager.cc:1085-1088`)
   - The prepared headers are passed through the encoder filter chain
   - `encodeHeaders()` iterates through encoder filters in reverse order
   - Response flows through filters (potentially including header mutation filter)

### Key Locations in Source Code

**File: `source/common/router/config_impl.cc` (Lines 942-950)**
```cpp
void RouteEntryImplBase::finalizeResponseHeaders(Http::ResponseHeaderMap& headers,
                                                 const StreamInfo::StreamInfo& stream_info) const {
  for (const HeaderParser* header_parser : getResponseHeaderParsers(
           /*specificity_ascend=*/vhost_->globalRouteConfig().mostSpecificHeaderMutationsWins())) {
    // Later evaluated header parser wins.
    header_parser->evaluateHeaders(headers, {stream_info.getRequestHeaders(), &headers},
                                   stream_info);
  }
}
```

This function applies header transformations from route configuration, including `response_headers_to_add`.

**File: `source/common/http/utility.cc` (Line 718-720)**
```cpp
if (encode_functions.modify_headers_) {
  encode_functions.modify_headers_(*response_headers);
}
```

The modify_headers_ callback is invoked during local reply preparation, triggering the header parser evaluation.

## Affected Components

1. **source/common/router/**
   - `router.cc` - Router filter that initiates local replies
   - `config_impl.cc` - Route entry that finalizes response headers
   - `router.h` - Router filter interface

2. **source/common/http/**
   - `filter_manager.cc` - Filter manager that wraps local reply with header finalization
   - `utility.cc` - Utility functions that prepare and encode local replies
   - `filter_manager.h` - Filter manager interface

3. **source/extensions/filters/http/header_mutation/**
   - `header_mutation.cc` - Header mutation filter that processes response headers in encoding phase

4. **api/envoy/config/core/v3/**
   - `header_value_option.proto` - Configuration for header value options with append_action
   - Defines `append_action` enum and deprecated `append` BoolValue field

## Causal Chain

```
symptom: Duplicate headers in local reply responses
   ↓
intermediate: Headers modified multiple times through filter pipeline
   ↓
intermediate: finalizeResponseHeaders() called during prepareLocalReply
              AND potentially called again in response processing
   ↓
intermediate: filter_manager.cc lines 1072-1078 create wrapper lambda
              that unconditionally calls finalizeResponseHeaders
   ↓
intermediate: Router.cc lines 1403-1412 (onUpstreamAbort) invoke sendLocalReply
              with lambda containing modify_headers_
   ↓
root cause: When sendLocalReply() is called, filter manager creates a new
            lambda that WRAPS the modification with an additional
            finalizeResponseHeaders() call. The router's lambda and the
            filter manager's lambda both apply header mutations, and if
            response flows through encoding pipeline, headers may be
            re-finalized
```

## Detailed Interaction Analysis

### For Direct Upstream Responses (Non-Local)
**File: `router.cc:1791-1800`**
```cpp
route_entry_->finalizeResponseHeaders(*headers, callbacks_->streamInfo());
modify_headers_(*headers);
...
callbacks_->encodeHeaders(std::move(headers), end_stream, ...);
```
- Headers finalized once BEFORE encoding
- This path works correctly

### For Local Replies
**File: `router.cc:1403-1412` → `filter_manager.cc:1123-1129` → `utility.cc:719`**
- Router calls `sendLocalReply()` with modify_headers_
- Filter manager intercepts and creates wrapper lambda that calls `finalizeResponseHeaders()`
- When response goes through `prepareLocalReply()`, modify_headers_ lambda is invoked
- This triggers `finalizeResponseHeaders()` INSIDE the filter manager's lambda
- Result: Headers get finalized and mutations applied during local reply preparation
- Headers then flow through encoding pipeline

### The Double-Invocation Scenario

The issue manifests when:
1. **Scenario A - No Upstream (cluster not found, no route)**
   - Router calls `sendLocalReply(code, "", modify_headers_, ...)`
   - Filter manager creates wrapper lambda including `finalizeResponseHeaders()` call
   - Wrapper lambda is invoked in `prepareLocalReply()` at line 719
   - `finalizeResponseHeaders()` applies header parsers including `response_headers_to_add`
   - Headers are correctly finalized once

2. **Scenario B - Upstream Failure (timeout, connection reset)**
   - Router calls `sendLocalReply()` with lambda at line 1405 that calls `modify_headers_`
   - Filter manager creates wrapper lambda including `finalizeResponseHeaders()` call
   - Wrapper lambda calls both:
     - `route_entry_->finalizeResponseHeaders()` (filter manager's lambda)
     - `modify_headers()` which then calls `modify_headers_` (router's lambda)
   - If response encoding pipeline processes route entry again, headers duplicated

## The HeaderValueOption Proto Configuration

**Files involved:**
- `api/envoy/config/core/v3/extension.proto`
- `api/envoy/config/core/v3/extension.proto` (HeaderValueOption definition)

The `HeaderValueOption` proto includes:
- `header`: The header name and value
- `append_action`: Enum field specifying behavior (APPEND_IF_EXISTS_OR_ADD, ADD_IF_ABSENT, OVERWRITE_IF_EXISTS, OVERWRITE_IF_EXISTS_OR_ADD)
- `append` (deprecated): Legacy BoolValue field

**Proto Default Behavior:**
- When `append_action` is not set, protobuf uses the default enum value (first defined value)
- This can cause unexpected behavior when headers are evaluated multiple times
- The `OVERWRITE_IF_EXISTS_OR_ADD` action should prevent duplication, but only if applied once

## Filter Manager's Encode Path

**File: `filter_manager.cc:1244-1333` (FilterManager::encodeHeaders)**

The encoder filters are iterated in reverse order (line 1257):
```cpp
for (; entry != encoder_filters_.end(); entry++) {
  FilterHeadersStatus status = (*entry)->handle_->encodeHeaders(headers, (*entry)->end_stream_);
  ...
}
```

Each filter (including header mutation filter) sees the headers AFTER they've been processed by `modify_headers_` in the local reply path.

## Recommendation

### Short-term Diagnostic Approach

1. **Add instrumentation** to track when `finalizeResponseHeaders()` is called:
   - Log every invocation with stack trace
   - Correlation with request ID to track per-stream
   - Record which route entry and header parsers are evaluated

2. **Enable verbose logging** in:
   - `source/common/router/config_impl.cc:finalizeResponseHeaders()`
   - `source/common/http/filter_manager.cc:prepareLocalReplyViaFilterChain()`
   - `source/common/http/filter_manager.cc:sendLocalReplyViaFilterChain()`
   - `source/common/http/filter_manager.cc:sendDirectLocalReply()`

3. **Trace the flow** for a request that exhibits duplicated headers:
   - Confirm if `finalizeResponseHeaders()` is indeed called twice
   - Identify which code path triggers the second invocation
   - Check if response encoding pipeline re-applies header mutations

### Fix Strategy

The fix should ensure that `finalizeResponseHeaders()` is called exactly once for local replies, at a consistent point in the pipeline:

**Option A:** Move header finalization OUT of the wrapper lambda in filter manager, apply it at a single, well-defined point before encoding

**Option B:** Ensure filter manager's wrapper does NOT call `finalizeResponseHeaders()` for local replies that already had it applied

**Option C:** Add a flag to `StreamInfo` tracking whether headers have been finalized, preventing duplicate application

### Testing

Create integration test that:
1. Configures `response_headers_to_add` in route config
2. Triggers upstream timeout (or other local reply scenario)
3. Verifies custom response headers appear exactly once in the response
4. Tests with various `append_action` values to ensure OVERWRITE_IF_EXISTS_OR_ADD works correctly

