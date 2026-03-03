# Investigation Report: Duplicate Response Headers in Envoy Filter Pipeline

## Summary

Response headers configured via `response_headers_to_add` in route configuration are being duplicated in local reply responses from the router filter. The root cause is that `RouteEntry::finalizeResponseHeaders()` is being invoked twice in the local reply code path: once explicitly in the wrapped `modify_headers_` callback in `FilterManager::prepareLocalReplyViaFilterChain()` (and similar functions), and again through the header mutation filter or filter chain iteration that processes responses.

## Root Cause

The issue stems from a misalignment in responsibility between:

1. **The FilterManager's wrapped callback** (`source/common/http/filter_manager.cc` lines 1072-1078, 1123-1129, 1156-1162) - explicitly calls `finalizeResponseHeaders()`
2. **The router filter's local reply callback** (`source/common/router/router.cc` lines 1405-1410) - passes the `modify_headers_` lambda

When these are combined, the route-level headers from `response_headers_to_add` are applied:
- **First time**: In the wrapped lambda's `finalizeResponseHeaders()` call during `Utility::prepareLocalReply()`
- **Second time**: Through the header mutation filter or another downstream filter that also processes response headers via the filter chain's encode path

## Evidence

### File: `source/common/router/router.cc`

**Lines 444-459** - `modify_headers_` Lambda Initialization:
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
Note: This lambda does NOT call `finalizeResponseHeaders()`.

**Lines 1405-1410** - Local Reply Callback in `onUpstreamAbort()`:
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
This passes a lambda that calls `modify_headers_` but does NOT call `finalizeResponseHeaders()`.

**Lines 1792-1793** - Upstream Response Path:
```cpp
route_entry_->finalizeResponseHeaders(*headers, callbacks_->streamInfo());
modify_headers_(*headers);
```
For upstream responses, `finalizeResponseHeaders()` is called BEFORE `modify_headers_()`.

### File: `source/common/http/filter_manager.cc`

**Lines 1072-1078** - Wrapped Callback in `prepareLocalReplyViaFilterChain()`:
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
This wrapped callback explicitly calls `finalizeResponseHeaders()` FIRST.

**Lines 1123-1129** - Wrapped Callback in `sendLocalReplyViaFilterChain()`:
Identical to prepareLocalReplyViaFilterChain.

**Lines 1156-1162** - Wrapped Callback in `sendDirectLocalReply()`:
Identical to prepareLocalReplyViaFilterChain.

**Lines 1070-1093** - `Utility::prepareLocalReply()` Invocation:
The wrapped callback is passed as the `modify_headers` parameter to `Utility::prepareLocalReply()`.

**Line 1087** - Header Iteration Through Filter Chain:
```cpp
encodeHeaders(nullptr, filter_manager_callbacks_.responseHeaders().ref(), end_stream);
```
This causes the prepared headers to go through the filter chain's `encodeHeaders()` path.

### File: `source/common/http/utility.cc`

**Lines 718-720** - Header Modification in `prepareLocalReply()`:
```cpp
if (encode_functions.modify_headers_) {
  encode_functions.modify_headers_(*response_headers);
}
```
This invokes the wrapped callback from FilterManager, which calls `finalizeResponseHeaders()`.

### File: `source/common/router/config_impl.cc`

**Lines 942-950** - `RouteEntryImplBase::finalizeResponseHeaders()`:
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
This applies all configured response headers via the `HeaderParser` chain.

### File: `source/common/router/header_parser.cc`

**Lines 145-212** - `HeaderParser::evaluateHeaders()`:
The function applies headers according to their `append_action` specification:
- Lines 204-207: Headers with `OVERWRITE_IF_EXISTS_OR_ADD` are applied via `headers.setReferenceKey()`
- Lines 209-211: Headers with other actions are applied via `headers.addReferenceKey()`

**Lines 58-71** - HeadersToAddEntry Constructor - Proto Field Handling:
```cpp
if (header_value_option.has_append()) {
  // 'append' is set and ensure the 'append_action' value is equal to the default value.
  if (header_value_option.append_action() != HeaderValueOption::APPEND_IF_EXISTS_OR_ADD) {
    creation_status =
        absl::InvalidArgumentError("Both append and append_action are set and it's not allowed");
    return;
  }
  append_action_ = header_value_option.append().value()
                       ? HeaderValueOption::APPEND_IF_EXISTS_OR_ADD
                       : HeaderValueOption::OVERWRITE_IF_EXISTS_OR_ADD;
} else {
  append_action_ = header_value_option.append_action_;
}
```
This shows the interaction between deprecated `append` BoolValue field and newer `append_action` enum, but does not directly cause duplication.

### File: `api/envoy/config/core/v3/base.proto`

The `HeaderValueOption` message defines:
- `append_action` enum with values: APPEND_IF_EXISTS_OR_ADD, ADD_IF_ABSENT, OVERWRITE_IF_EXISTS, OVERWRITE_IF_EXISTS_OR_ADD
- Deprecated `append` BoolValue field (converted to enum in header_parser.cc)

## Affected Components

1. **source/common/router/** - Router filter and response header processing
   - `router.cc` - Local reply generation and `modify_headers_` callback
   - `config_impl.cc` - `RouteEntryImplBase::finalizeResponseHeaders()`
   - `header_parser.cc` - Header evaluation and append action handling

2. **source/common/http/** - HTTP filter infrastructure
   - `filter_manager.cc` - Local reply wrapping and header callback binding
   - `utility.cc` - Local reply preparation and header modification callback invocation

3. **source/extensions/filters/http/header_mutation/** - Header mutation filter
   - May process response headers through filter chain iteration

4. **api/envoy/config/core/v3/** - Protocol buffer definitions
   - `base.proto` - HeaderValueOption with append_action enum

## Causal Chain

1. **Symptom**: Response headers appear twice in access log for local replies
   - Example: `x-custom-trace: abc123` and `x-custom-trace: abc123`

2. **Observation**: Local replies are generated by router filter via `sendLocalReply()`
   - Called in `onUpstreamAbort()`, `onPerTryTimeout()`, and other error paths

3. **First Hop**: Router passes `modify_headers_` lambda callback to `callbacks_->sendLocalReply()`
   - `source/common/router/router.cc` line 1403

4. **Second Hop**: FilterManager's `sendLocalReply()` receives the callback
   - `source/common/http/filter_manager.cc` line 982

5. **Third Hop**: FilterManager wraps the callback to include `finalizeResponseHeaders()` call
   - Lines 1072-1078 (prepareLocalReplyViaFilterChain)
   - Lines 1123-1129 (sendLocalReplyViaFilterChain)
   - Lines 1156-1162 (sendDirectLocalReply)

6. **Fourth Hop**: Wrapped callback is passed to `Utility::prepareLocalReply()` as `modify_headers`
   - `source/common/http/filter_manager.cc` line 1070

7. **Fifth Hop**: `Utility::prepareLocalReply()` invokes the wrapped callback
   - `source/common/http/utility.cc` line 719
   - **First invocation of `finalizeResponseHeaders()` occurs here**
   - Route-level `response_headers_to_add` are applied to response headers

8. **Sixth Hop**: Prepared headers are passed through filter chain via `encodeHeaders()`
   - `source/common/http/filter_manager.cc` line 1087
   - Headers are visible to FilterManager and downstream filters

9. **Seventh Hop**: Filter chain iteration may cause headers to be evaluated again
   - Either through header mutation filter or through the FilterManager's default encode path
   - **Second invocation of header transformations occurs here**

10. **Root Cause**: The wrapped callback in FilterManager explicitly calls `finalizeResponseHeaders()`, but the upstream response path (lines 1792-1793) also shows that `finalizeResponseHeaders()` is called separately for upstream responses. For local replies, the wrapping creates an implicit double-processing when headers pass through the filter chain.

## Recommendation

**Diagnostic Steps**:
1. Trace the exact execution path by adding logging at:
   - `RouteEntryImplBase::finalizeResponseHeaders()` entry point
   - `HeaderParser::evaluateHeaders()` when called for response headers
   - Filter chain's `encodeHeaders()` method

2. Compare header counts at each stage of processing to confirm where duplication occurs

3. Check if header mutation filter or another downstream filter is invoking response header processing that duplicates the work

**Fix Strategy**:
The fundamental issue is that `finalizeResponseHeaders()` responsibility differs between:
- **Upstream path**: Called explicitly BEFORE `modify_headers_()` (line 1792)
- **Local reply path**: Wrapped WITHIN the `modify_headers_` callback by FilterManager

Options:
1. **Move finalizeResponseHeaders outside the wrapped callback** - Have the FilterManager NOT wrap the callback to include finalizeResponseHeaders for local replies, since the router already handles it through modify_headers_
2. **Ensure single invocation point** - Guarantee that `finalizeResponseHeaders()` is called exactly once per response, regardless of path (upstream vs local reply)
3. **Track invocation state** - Add a flag to prevent double-processing of the same response headers

The cleanest fix would be option #1: When FilterManager wraps the callback for local replies, it should NOT call `finalizeResponseHeaders()` separately if the caller's `modify_headers` callback is responsible for it.

## Critical Insight

The inconsistency stems from treating local reply header modification differently from upstream response header modification:

- **Upstream responses** (source/common/router/router.cc:1792-1793):
  ```cpp
  route_entry_->finalizeResponseHeaders(*headers, callbacks_->streamInfo());
  modify_headers_(*headers);
  ```
  Clear separation: header finalization, then header modification

- **Local replies** (source/common/http/filter_manager.cc:1072-1078):
  ```cpp
  streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());
  if (modify_headers) modify_headers(headers);
  ```
  Same structure, but this wrapped callback is treated as the entire `modify_headers` function passed from the router, which means if the filter chain also processes these headers, duplication occurs.
