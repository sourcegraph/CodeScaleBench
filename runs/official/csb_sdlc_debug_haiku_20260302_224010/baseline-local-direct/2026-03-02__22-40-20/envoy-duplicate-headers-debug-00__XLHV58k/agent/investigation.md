# Investigation Report: Duplicate Response Headers in Envoy Filter Pipeline

## Summary

Response headers configured via `response_headers_to_add` are duplicated in local reply responses because the router filter's `finalizeResponseHeaders()` method is invoked twice: once explicitly by the filter manager and again within the router's `modify_headers_` callback, both called during the local reply generation path but not during the normal upstream response path.

## Root Cause

**Double invocation of `finalizeResponseHeaders()` in local reply path**

When the router filter generates a local reply (timeout, no cluster, etc.), the filter manager calls `sendLocalReply()` which eventually creates a lambda callback that explicitly calls `finalizeResponseHeaders()`. However, this same lambda then invokes the router's `modify_headers_` callback, which **also** calls `finalizeResponseHeaders()` internally. This causes header-adding logic to execute twice, resulting in duplicate headers with certain `append_action` configurations.

For normal upstream responses (proxied), `finalizeResponseHeaders()` is called exactly once via the `modify_headers_` callback during the `onUpstreamHeaders()` path, so duplicates do not occur.

## Evidence

### File: `/workspace/source/common/http/filter_manager.cc`

**Lines 1072-1078** (`prepareLocalReplyViaFilterChain`):
```cpp
[this, modify_headers](ResponseHeaderMap& headers) -> void {
  if (streamInfo().route() && streamInfo().route()->routeEntry()) {
    streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());  // FIRST CALL
  }
  if (modify_headers) {
    modify_headers(headers);  // SECOND CALL (indirectly via router's lambda)
  }
},
```

**Lines 1123-1129** (`sendLocalReplyViaFilterChain`):
```cpp
[this, modify_headers](ResponseHeaderMap& headers) -> void {
  if (streamInfo().route() && streamInfo().route()->routeEntry()) {
    streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());  // FIRST CALL
  }
  if (modify_headers) {
    modify_headers(headers);  // SECOND CALL
  }
},
```

**Lines 1156-1162** (`sendDirectLocalReply`):
```cpp
[this, modify_headers](ResponseHeaderMap& headers) -> void {
  if (streamInfo().route() && streamInfo().route()->routeEntry()) {
    streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());  // FIRST CALL
  }
  if (modify_headers) {
    modify_headers(headers);  // SECOND CALL
  }
},
```

### File: `/workspace/source/common/router/router.cc`

**Lines 444-461** (Router's `modify_headers_` lambda definition):
```cpp
modify_headers_ = [this](Http::ResponseHeaderMap& headers) {
  if (route_entry_ == nullptr) {
    return;
  }
  if (modify_headers_from_upstream_lb_) {
    modify_headers_from_upstream_lb_(headers);
  }
  route_entry_->finalizeResponseHeaders(headers, callbacks_->streamInfo());  // DUPLICATE CALL
  if (attempt_count_ == 0 || !route_entry_->includeAttemptCountInResponse()) {
    return;
  }
  headers.setEnvoyAttemptCount(attempt_count_);
};
```

**Line 1794** (Normal upstream response path):
```cpp
modify_headers_(*headers);  // CALLED ONCE for upstream responses
```

**Lines 522, 550, 750, 931, 1004, 1060, 1340** (Local reply calls):
```cpp
callbacks_->sendLocalReply(..., modify_headers_, ...);  // Router passes its lambda
```

### File: `/workspace/source/common/router/config_impl.cc`

**Lines 942-950** (`RouteEntryImplBase::finalizeResponseHeaders`):
```cpp
void RouteEntryImplBase::finalizeResponseHeaders(Http::ResponseHeaderMap& headers,
                                                 const StreamInfo::StreamInfo& stream_info) const {
  for (const HeaderParser* header_parser : getResponseHeaderParsers(...)) {
    header_parser->evaluateHeaders(headers, {stream_info.getRequestHeaders(), &headers},
                                   stream_info);
  }
}
```

This iterates through all `HeaderParser` instances and evaluates them, applying `response_headers_to_add` configuration.

### File: `/workspace/source/common/router/header_parser.cc`

**Lines 182-199** (`evaluateHeaders` - header application logic):
```cpp
switch (entry->append_action_) {
  case HeaderValueOption::APPEND_IF_EXISTS_OR_ADD:
    headers_to_add.emplace_back(key, value);  // Queues header for addition
    break;
  case HeaderValueOption::OVERWRITE_IF_EXISTS_OR_ADD:
    headers_to_overwrite.emplace_back(key, value);  // Queues header for overwrite
    break;
  // ...
}
```

**Lines 205-212** (Application phase):
```cpp
for (const auto& header : headers_to_overwrite) {
  headers.setReferenceKey(header.first, header.second);  // Overwrites: remove then add
}
for (const auto& header : headers_to_add) {
  headers.addReferenceKey(header.first, header.second);  // Appends or adds
}
```

When `finalizeResponseHeaders` is called twice:
1. **First invocation** (filter_manager): Header is added via `addReferenceKey()`
2. **Second invocation** (router's `modify_headers_`): For `APPEND_IF_EXISTS_OR_ADD`, the header is appended again, resulting in duplicate values

## Affected Components

1. **`source/common/http/filter_manager.cc`**
   - `DownstreamFilterManager::prepareLocalReplyViaFilterChain()`
   - `DownstreamFilterManager::sendLocalReplyViaFilterChain()`
   - `DownstreamFilterManager::sendDirectLocalReply()`

2. **`source/common/router/router.cc`**
   - `Filter::decodeHeaders()` - initializes `modify_headers_` lambda
   - `Filter::onUpstreamHeaders()` - calls `modify_headers_` for upstream responses
   - `Filter::onLocalReply()` and related methods - pass `modify_headers_` to `sendLocalReply()`

3. **`source/common/router/config_impl.cc`**
   - `RouteEntryImplBase::finalizeResponseHeaders()` - applies route-level header configurations

4. **`source/common/router/header_parser.cc`**
   - `HeaderParser::evaluateHeaders()` - implements the header mutation logic
   - `HeadersToAddEntry` - proto parsing for `response_headers_to_add`

5. **`api/envoy/config/core/v3/base.proto`**
   - `HeaderValueOption` message definition
   - `HeaderAppendAction` enum defining append/overwrite semantics

## Causal Chain

1. **Symptom**: Response headers appear duplicated in local reply responses (e.g., `x-custom-trace: abc123` appears twice)

2. **Observation**: Duplication occurs only for local replies, not for proxied upstream responses

3. **Filter Manager Entry Point**: Router calls `sendLocalReply()` with its `modify_headers_` callback (router.cc:522, etc.)

4. **Filter Manager Path Selection**: Based on request state, filter manager routes to one of:
   - `sendLocalReplyViaFilterChain()` (line 1031 of filter_manager.cc)
   - `prepareLocalReplyViaFilterChain()` (line 1028 of filter_manager.cc)
   - `sendDirectLocalReply()` (line 1043 of filter_manager.cc)

5. **First `finalizeResponseHeaders` Call**: Each of these functions creates a lambda that explicitly invokes `route_entry_->finalizeResponseHeaders()` (lines 1074, 1125, 1158)

6. **Second `finalizeResponseHeaders` Call**: The same lambda then invokes the `modify_headers` callback (lines 1077, 1128, 1161), which is the router's `modify_headers_` lambda defined at router.cc:444-461

7. **Router's `modify_headers_` Lambda**: Contains another call to `route_entry_->finalizeResponseHeaders()` at router.cc:453

8. **Header Application Logic**: For each invocation, `evaluateHeaders()` processes the `response_headers_to_add` configuration:
   - With `APPEND_IF_EXISTS_OR_ADD` (default): Headers are appended, not deduplicated
   - With `OVERWRITE_IF_EXISTS_OR_ADD`: First call adds header, second call overwrites it (but the semantics still result in the header being re-added)

9. **Access Log Evidence**: Duplicate headers appear in response headers sent to the client, visible in access logs using `%RESPONSE_HEADERS%` formatter

## Architectural Context

### Normal Upstream Response Path (Correct - Single Call)
```
Filter::onUpstreamHeaders()
  → modify_headers_(*headers)           [Line 1794]
    → finalizeResponseHeaders()         [Line 453 - Single call]
      → HeaderParser::evaluateHeaders() [Applies headers once]
  → callbacks_->encodeHeaders()         [Sends to downstream]
```

### Local Reply Path (Incorrect - Double Call)
```
Filter::onLocalReply() / similar
  → callbacks_->sendLocalReply(..., modify_headers_, ...)
    → FilterManager::sendLocalReply()
      → FilterManager::sendLocalReplyViaFilterChain()
        → Utility::sendLocalReply()
          → Utility::prepareLocalReply()
            → Lambda [filter_manager.cc:1123-1129]
              → finalizeResponseHeaders()              [Line 1125 - FIRST CALL]
              → modify_headers(headers)                [Line 1128]
                → Router's modify_headers_ lambda
                  → finalizeResponseHeaders()          [Line 453 - SECOND CALL]
            → HeaderParser::evaluateHeaders()          [Applied twice]
              → Headers duplicated due to APPEND_IF_EXISTS_OR_ADD
```

## Root Cause Analysis

The fundamental issue is a **separation of concerns violation**:

1. **The filter manager assumes it should call `finalizeResponseHeaders()`** to apply route-level header mutations when preparing local replies. This is done to ensure consistency with route configuration.

2. **The router also assumes it should call `finalizeResponseHeaders()`** via its `modify_headers_` callback, which is passed to `sendLocalReply()` to handle route-level headers.

3. **No guard exists** to prevent `finalizeResponseHeaders()` from being called multiple times in the local reply code path.

In contrast, the normal upstream response path explicitly calls `modify_headers_` (which contains the single `finalizeResponseHeaders()` call) exactly once, avoiding duplication.

## Proto Configuration Details

The `HeaderValueOption` proto (in `api/envoy/config/core/v3/base.proto`) contains:

- **`append_action`**: Modern enum field (default: `APPEND_IF_EXISTS_OR_ADD`) that controls mutation semantics
  - `APPEND_IF_EXISTS_OR_ADD` (0): Appends to existing headers; adds if absent (causes duplication when called twice)
  - `OVERWRITE_IF_EXISTS_OR_ADD` (2): Overwrites if exists; adds if absent
  - `ADD_IF_ABSENT` (1): Only adds if header doesn't exist
  - `OVERWRITE_IF_EXISTS` (3): Only overwrites if exists

- **`append`**: Deprecated `BoolValue` field that maps to `append_action` (true = APPEND_IF_EXISTS_OR_ADD, false = OVERWRITE_IF_EXISTS_OR_ADD)

**Header parsing** (header_parser.cc:58-71) handles both fields with appropriate deprecation checks:
```cpp
if (header_value_option.has_append()) {
  append_action_ = header_value_option.append().value()
                       ? HeaderValueOption::APPEND_IF_EXISTS_OR_ADD
                       : HeaderValueOption::OVERWRITE_IF_EXISTS_OR_ADD;
} else {
  append_action_ = header_value_option.append_action();
}
```

The problem manifests with default configurations because `append_action` defaults to `APPEND_IF_EXISTS_OR_ADD`, which causes headers to be duplicated when `finalizeResponseHeaders()` is called twice.

## Filter Execution Order

The filter manager's `encodeHeaders()` (filter_manager.cc:1244) iterates through encoder filters in reverse order:

```cpp
for (auto entry = encoder_filters_.rbegin(); entry != encoder_filters_.rend(); ++entry) {
  FilterHeadersStatus status = (*entry)->handle_->encodeHeaders(headers, (*entry)->end_stream_);
  // ...
}
```

Filters like `header_mutation` (which also processes response headers) run AFTER the router filter's header modifications are complete. However, for local replies, this execution order is bypassed, and headers are modified during the local reply generation phase itself, within the filter manager's lambda, causing the duplication.

## Recommendation

### Fix Strategy

The duplication can be resolved by **removing the explicit `finalizeResponseHeaders()` call from the filter manager's local reply lambdas** (filter_manager.cc:1074, 1125, 1158). The router's `modify_headers_` callback already invokes `finalizeResponseHeaders()`, so the filter manager call is redundant.

Instead, the filter manager should trust that:
1. The router's `modify_headers_` lambda will apply route-level headers via `finalizeResponseHeaders()`
2. The router's lambda is always passed to `sendLocalReply()` for this purpose
3. No additional header finalization is needed at the filter manager level

### Diagnostic Steps

To verify this issue in a running system:

1. **Enable response header logging**: Use the `%RESPONSE_HEADERS%` formatter in access logs
2. **Monitor local reply responses**: Filter access logs for response code details like `upstream_response_timeout`, `no_cluster_found`, `request_too_large`
3. **Count header occurrences**: Search for custom response headers (e.g., `x-custom-trace`) in the response headers field
4. **Compare with upstream responses**: Verify that the same headers appear only once in normal proxied responses
5. **Test with `OVERWRITE_IF_EXISTS_OR_ADD`**: Configure a test header with this action to confirm it's being reapplied

### Testing Approach

1. Create a route with `response_headers_to_add` containing a custom header with both default and explicit `append_action` values
2. Generate a local reply scenario (e.g., upstream timeout by setting low timeout)
3. Capture response headers and verify no duplication occurs
4. Compare behavior with upstream responses to ensure consistency

## References

- Router filter initialization: `source/common/router/router.cc:440-461`
- Local reply generation: `source/common/http/filter_manager.cc:982-1053`
- Header parser logic: `source/common/router/header_parser.cc:139-213`
- Route finalization: `source/common/router/config_impl.cc:942-950`
- Proto definition: `api/envoy/config/core/v3/base.proto` (HeaderValueOption, HeaderAppendAction)
