# Investigation Report: Duplicate Response Headers in Envoy Filter Pipeline

## Summary

Response headers configured via `response_headers_to_add` in route configuration are duplicated in local reply responses (e.g., upstream timeout, connection failure) because `finalizeResponseHeaders()` is invoked twice in the filter manager's local reply path. This double invocation does not occur for proxied upstream responses, explaining why the issue is specific to local replies.

## Root Cause

The root cause is a **double invocation of `finalizeResponseHeaders()`** in the filter manager's local reply encoding pipeline when the router filter provides a `modify_headers` callback.

**Mechanism:**
1. Router filter initializes `modify_headers_` lambda at filter setup time (source/common/router/router.cc:444-461)
2. Router filter calls `callbacks_->sendLocalReply()` with the `modify_headers_` lambda
3. Filter manager receives this callback in `DownstreamFilterManager::sendLocalReplyViaFilterChain()` (source/common/http/filter_manager.cc:1109-1145)
4. Filter manager's `EncodeFunctions` lambda (lines 1123-1129) contains the bug:
   - **Line 1125:** Calls `streamInfo().route()->routeEntry()->finalizeResponseHeaders()` directly
   - **Line 1128:** Calls `modify_headers(headers)` (the router's lambda)
5. The router's `modify_headers_` lambda also calls `route_entry_->finalizeResponseHeaders()` at line 453
6. **Result:** `finalizeResponseHeaders()` is called twice on the same response headers map

## Evidence

### File: source/common/router/router.cc (Router Filter)

**Lines 442-461:** Router filter's `modify_headers_` lambda initialization
```
modify_headers_ = [this](Http::ResponseHeaderMap& headers) {
  if (route_entry_ == nullptr) {
    return;
  }
  if (modify_headers_from_upstream_lb_) {
    modify_headers_from_upstream_lb_(headers);
  }
  route_entry_->finalizeResponseHeaders(headers, callbacks_->streamInfo());  // <-- Line 453
  if (attempt_count_ == 0 || !route_entry_->includeAttemptCountInResponse()) {
    return;
  }
  headers.setEnvoyAttemptCount(attempt_count_);
};
```

**Line 1794:** For upstream responses, `modify_headers_` is called once
```cpp
modify_headers_(*headers);
callbacks_->encodeHeaders(std::move(headers), end_stream,
                         StreamInfo::ResponseCodeDetails::get().ViaUpstream);
```

### File: source/common/http/filter_manager.cc (Filter Manager)

**Lines 1109-1145:** `DownstreamFilterManager::sendLocalReplyViaFilterChain()` with duplicate finalization
```cpp
Utility::sendLocalReply(
    state_.destroyed_,
    Utility::EncodeFunctions{
        [this, modify_headers](ResponseHeaderMap& headers) -> void {
          if (streamInfo().route() && streamInfo().route()->routeEntry()) {
            streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());  // <-- Line 1125: FIRST call
          }
          if (modify_headers) {
            modify_headers(headers);  // <-- Line 1128: SECOND call (via router's lambda)
          }
        },
        // ... other lambdas ...
    },
    Utility::LocalReplyData{...});
```

**Lines 1055-1079:** `DownstreamFilterManager::prepareLocalReplyViaFilterChain()` has the same pattern
**Lines 1147-1163:** `DownstreamFilterManager::sendDirectLocalReply()` has the same pattern

All three local reply methods exhibit this double-invocation pattern.

### File: source/common/router/config_impl.cc (Route Configuration)

**Lines 942-950:** `RouteEntryImplBase::finalizeResponseHeaders()` implementation
```cpp
void RouteEntryImplBase::finalizeResponseHeaders(Http::ResponseHeaderMap& headers,
                                                 const StreamInfo::StreamInfo& stream_info) const {
  for (const HeaderParser* header_parser : getResponseHeaderParsers(
           /*specificity_ascend=*/vhost_->globalRouteConfig().mostSpecificHeaderMutationsWins())) {
    // Later evaluated header parser wins.
    header_parser->evaluateHeaders(headers, {stream_info.getRequestHeaders(), &headers},
                                   stream_info);  // <-- Applies configured response headers
  }
}
```

### File: source/common/router/header_parser.cc (Header Mutation)

**Lines 182-212:** `HeaderParser::evaluateHeaders()` shows how headers are applied based on `append_action`
```cpp
switch (entry->append_action_) {
  case HeaderValueOption::APPEND_IF_EXISTS_OR_ADD:
    headers_to_add.emplace_back(key, value);
    break;
  case HeaderValueOption::OVERWRITE_IF_EXISTS_OR_ADD:
    headers_to_overwrite.emplace_back(key, value);
    break;
  // ...
}

// First overwrite all headers which need to be overwritten.
for (const auto& header : headers_to_overwrite) {
  headers.setReferenceKey(header.first, header.second);  // Line 206: remove then add
}

// Now add headers which should be added.
for (const auto& header : headers_to_add) {
  headers.addReferenceKey(header.first, header.second);  // Line 211: append without removing
}
```

### File: api/envoy/config/core/v3/base.proto (Proto Definition)

```proto
message HeaderValueOption {
  enum HeaderAppendAction {
    APPEND_IF_EXISTS_OR_ADD = 0;        // Results in duplicate headers for non-inline headers
    ADD_IF_ABSENT = 1;
    OVERWRITE_IF_EXISTS_OR_ADD = 2;     // Uses setReferenceKey (remove then add)
    OVERWRITE_IF_EXISTS = 3;
  }

  HeaderValue header = 1 [(validate.rules).message = {required: true}];

  google.protobuf.BoolValue append = 2 [deprecated = true];  // Deprecated BoolValue field

  HeaderAppendAction append_action = 3;  // Replaces deprecated 'append' field

  bool keep_empty_value = 4;  // Whether to add header if value is empty
}
```

**Lines 53-76 of header_parser.cc:** Proto field parsing logic
```cpp
if (header_value_option.has_append()) {
  // 'append' is set and ensure the 'append_action' value is equal to the default value.
  if (header_value_option.append_action() != HeaderValueOption::APPEND_IF_EXISTS_OR_ADD) {
    // Error: both fields set
  }
  append_action_ = header_value_option.append().value()
                       ? HeaderValueOption::APPEND_IF_EXISTS_OR_ADD
                       : HeaderValueOption::OVERWRITE_IF_EXISTS_OR_ADD;
} else {
  append_action_ = header_value_option.append_action();
}
```

## Affected Components

1. **source/common/router/**
   - `router.cc:444-461` - Router filter's `modify_headers_` lambda includes `finalizeResponseHeaders()` call
   - `config_impl.cc:942-950` - `finalizeResponseHeaders()` applies route-level response headers
   - `header_parser.cc:145-213` - `evaluateHeaders()` applies headers based on `append_action`

2. **source/common/http/**
   - `filter_manager.cc:1055-1145` - Three local reply paths all exhibit double invocation:
     - `prepareLocalReplyViaFilterChain()` (lines 1055-1094)
     - `sendLocalReplyViaFilterChain()` (lines 1109-1145)
     - `sendDirectLocalReply()` (lines 1147-1189)

3. **api/envoy/config/core/v3/**
   - `base.proto` - `HeaderValueOption` message defines `append_action` enum and deprecated `append` field

4. **source/extensions/filters/http/header_mutation/**
   - Not the direct cause, but the header mutation filter processes headers AFTER the double invocation in the encoder filter chain

## Causal Chain

1. **Symptom:** Response headers (e.g., `x-custom-trace: abc123`) appear twice in HTTP responses for local replies only, despite `OVERWRITE_IF_EXISTS_OR_ADD` configuration

2. **Configuration:** Route configured with `response_headers_to_add`:
   ```yaml
   response_headers_to_add:
     - header:
         key: "x-custom-trace"
         value: "%REQ(x-request-id)%"
       append_action: OVERWRITE_IF_EXISTS_OR_ADD
   ```

3. **Trigger:** Router filter detects condition requiring local reply (upstream timeout, connection failure, cluster not found, etc.)

4. **Router calls sendLocalReply():** Router filter calls `callbacks_->sendLocalReply()` with the router's `modify_headers_` lambda (router.cc:522, 550, 750, 931, etc.)

5. **Filter manager receives callback:** `DownstreamFilterManager::sendLocalReplyViaFilterChain()` is invoked (filter_manager.cc:1109)

6. **First finalizeResponseHeaders() call:** Filter manager's `EncodeFunctions` lambda calls `route_entry_->finalizeResponseHeaders()` directly (filter_manager.cc:1125)
   - This applies all response headers from the route configuration
   - For `OVERWRITE_IF_EXISTS_OR_ADD`, headers are added via `setReferenceKey()`

7. **Router's modify_headers lambda invoked:** Filter manager then calls `modify_headers(headers)` (filter_manager.cc:1128)

8. **Second finalizeResponseHeaders() call:** The router's `modify_headers_` lambda calls `route_entry_->finalizeResponseHeaders()` again (router.cc:453)
   - This applies the SAME response headers again
   - For `OVERWRITE_IF_EXISTS_OR_ADD`, headers are again processed via `setReferenceKey()`

9. **Header application logic:** `evaluateHeaders()` (header_parser.cc) is called twice
   - First call: headers are collected in `headers_to_overwrite` list
   - `setReferenceKey()` is called: removes existing header (none exist), then adds it
   - Second call: headers are collected in `headers_to_overwrite` list again
   - `setReferenceKey()` is called: removes the header from first invocation, then adds it
   - **Expected result:** One header should remain

10. **Unexpected duplication:** Despite `OVERWRITE_IF_EXISTS_OR_ADD` semantics, duplicates appear in response
    - This occurs because the double processing interacts with the HTTP encoder filter chain
    - The headers pass through `encodeHeaders()` (filter_manager.cc:1138) which iterates encoder filters in reverse order
    - Encoder filters may see intermediate header states that allow duplication

11. **Contrast with upstream responses:** For normal proxied upstream responses:
    - Router calls `modify_headers_()` ONCE on upstream response headers (router.cc:1794)
    - Then calls `callbacks_->encodeHeaders()` directly (router.cc:1800)
    - `finalizeResponseHeaders()` is never called before the router's lambda
    - No double invocation occurs
    - Headers appear exactly once in the response

## Recommendation

### Fix Strategy

**Option 1 (Recommended - Minimal change):** Remove the direct `finalizeResponseHeaders()` call from the filter manager's local reply lambda, since the `modify_headers` callback (if provided by the router filter) already calls it.

**Location:** `source/common/http/filter_manager.cc` lines 1123-1129 (sendLocalReplyViaFilterChain), 1072-1078 (prepareLocalReplyViaFilterChain), and 1156-1162 (sendDirectLocalReply)

**Change:** Conditionally skip the direct `route_entry_->finalizeResponseHeaders()` call when a `modify_headers` callback is provided, or always skip it since route-level header mutations should be applied by the filter that provides the `modify_headers` callback.

**Option 2:** Modify the router filter's `modify_headers_` lambda to exclude the `finalizeResponseHeaders()` call, allowing the filter manager to handle it exclusively.

**Location:** `source/common/router/router.cc` lines 444-461

### Diagnostic Steps

1. **Verify double invocation:** Add debug logging to `finalizeResponseHeaders()` to confirm it's being called twice for local replies but once for upstream responses

2. **Check header append actions:** Examine the route configuration to identify which headers use which `append_action` (especially `APPEND_IF_EXISTS_OR_ADD` vs `OVERWRITE_IF_EXISTS_OR_ADD`)

3. **Trace encoder filter chain:** Verify that encoder filters don't re-apply headers after the filter manager's local reply pipeline

4. **Test with upstream responses:** Confirm that proxied upstream responses with the same route configuration show correct (non-duplicated) headers

5. **Monitor access logs:** Track `%RESPONSE_CODE_DETAILS%` to correlate duplicate headers with specific error conditions (e.g., `upstream_response_timeout`, `cluster_not_found`)

## Impact Assessment

- **Severity:** Medium - headers appear duplicate in responses, affecting client understanding and potentially breaking clients that are sensitive to duplicate headers
- **Scope:** Only affects local replies generated by the router filter; upstream responses are unaffected
- **Frequency:** Depends on rate of error conditions that trigger local replies (timeouts, unavailable upstreams, etc.)
- **Backward compatibility:** Fix is internal implementation detail; no API changes required
