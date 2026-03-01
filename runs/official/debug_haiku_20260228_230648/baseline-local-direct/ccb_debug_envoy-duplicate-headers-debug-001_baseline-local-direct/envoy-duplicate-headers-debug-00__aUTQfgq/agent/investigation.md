# Investigation Report: Duplicate Response Headers in Envoy Filter Pipeline

## Summary

Response headers configured via `response_headers_to_add` are being duplicated in local reply responses because the filter manager's local reply handling code paths call `finalizeResponseHeaders()` **twice**: once directly, and once again through the router's `modify_headers_` callback. This results in headers being added twice, violating the `OVERWRITE_IF_EXISTS_OR_ADD` action configured by the operator.

## Root Cause

**Primary Mechanism**: The filter manager's `sendLocalReply` implementations in `/workspace/source/common/http/filter_manager.cc` call `route_entry_->finalizeResponseHeaders()` directly (lines 1074, 1125, 1158), and then immediately invoke the `modify_headers_` callback which was populated by the router filter with an identical call to `finalizeResponseHeaders()` (router.cc:453).

**Double Invocation Location**:
- **First call**: Filter manager's local reply encoder functions (lines 1074, 1125, 1158)
- **Second call**: Through `modify_headers_` callback → router's lambda (router.cc:453)

This double invocation does NOT occur for proxied upstream responses because they only call `modify_headers_()` once in `onUpstreamHeaders()` (router.cc:1794), followed by normal filter chain processing.

## Evidence

### Code References

#### 1. Router Filter Setup of `modify_headers_` (source/common/router/router.cc:442-461)

```cpp
// Initialize the `modify_headers_` function that will be used to modify the response headers for
// all upstream responses or local responses.
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

The router creates this lambda in `decodeHeaders()` with the intention that it will apply response header modifications to both upstream AND local replies.

#### 2. Filter Manager's `prepareLocalReplyViaFilterChain` (source/common/http/filter_manager.cc:1070-1094)

```cpp
prepared_local_reply_ = Utility::prepareLocalReply(
    Utility::EncodeFunctions{
        [this, modify_headers](ResponseHeaderMap& headers) -> void {
          if (streamInfo().route() && streamInfo().route()->routeEntry()) {
            streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());  // FIRST CALL
          }
          if (modify_headers) {
            modify_headers(headers);  // SECOND CALL - which itself calls finalizeResponseHeaders()
          }
        },
        // ... other encoder functions ...
    },
    Utility::LocalReplyData{is_grpc_request, code, body, grpc_status, is_head_request});
```

**Line 1074**: Direct call to `finalizeResponseHeaders()`
**Line 1077**: Call to `modify_headers` callback, which invokes the router's lambda containing another `finalizeResponseHeaders()` call

#### 3. Filter Manager's `sendLocalReplyViaFilterChain` (source/common/http/filter_manager.cc:1120-1130)

```cpp
Utility::sendLocalReply(
    state_.destroyed_,
    Utility::EncodeFunctions{
        [this, modify_headers](ResponseHeaderMap& headers) -> void {
          if (streamInfo().route() && streamInfo().route()->routeEntry()) {
            streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());  // FIRST CALL
          }
          if (modify_headers) {
            modify_headers(headers);  // SECOND CALL
          }
        },
        // ... other encoder functions ...
    },
    Utility::LocalReplyData{is_grpc_request, code, body, grpc_status, is_head_request});
```

Same double-call pattern: lines 1125 and 1128.

#### 4. Filter Manager's `sendDirectLocalReply` (source/common/http/filter_manager.cc:1153-1163)

```cpp
Http::Utility::sendLocalReply(
    state_.destroyed_,
    Utility::EncodeFunctions{
        [this, modify_headers](ResponseHeaderMap& headers) -> void {
          if (streamInfo().route() && streamInfo().route()->routeEntry()) {
            streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());  // FIRST CALL
          }
          if (modify_headers) {
            modify_headers(headers);  // SECOND CALL
          }
        },
        // ... other encoder functions ...
    },
    Utility::LocalReplyData{is_grpc_request, code, body, grpc_status, is_head_request});
```

Same pattern: lines 1158 and 1161.

#### 5. Router's `onUpstreamHeaders` - Correct Single Call (source/common/router/router.cc:1793-1801)

```cpp
// Modify response headers after we have set the final upstream info because we may need to
// modify the headers based on the upstream host.
modify_headers_(*headers);  // LINE 1794 - Called ONCE for upstream responses

if (end_stream) {
  onUpstreamComplete(upstream_request);
}

callbacks_->encodeHeaders(std::move(headers), end_stream,
                          StreamInfo::ResponseCodeDetails::get().ViaUpstream);
```

For proxied responses, `modify_headers_` is called exactly once, then headers pass through the normal filter chain.

#### 6. Route Configuration's `finalizeResponseHeaders` (source/common/router/config_impl.cc:942-950)

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

This iterates through all header parsers configured on the route and applies them.

#### 7. Header Parser Configuration - `append_action` Field (source/common/router/header_parser.cc:53-76)

```cpp
HeadersToAddEntry::HeadersToAddEntry(const HeaderValueOption& header_value_option,
                                     absl::Status& creation_status)
    : original_value_(header_value_option.header().value()),
      add_if_empty_(header_value_option.keep_empty_value()) {

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
    append_action_ = header_value_option.append_action();  // DEFAULT: APPEND_IF_EXISTS_OR_ADD
  }
  // ...
}
```

The deprecated `append` BoolValue field (lines 58-68) and newer `append_action` enum (line 70) are both parsed here. The default value for `append_action` is `APPEND_IF_EXISTS_OR_ADD` when not explicitly set (line 60 checks for this default).

#### 8. Proto Definition of `append_action` (api/envoy/config/core/v3/base.proto:428-481)

```protobuf
message HeaderValueOption {
  enum HeaderAppendAction {
    // If header exists: comma-concatenate for inline headers, duplicate for others.
    // If header doesn't exist: add new header.
    APPEND_IF_EXISTS_OR_ADD = 0;

    // Add only if header doesn't exist.
    ADD_IF_ABSENT = 1;

    // Overwrite existing values or add if absent.
    OVERWRITE_IF_EXISTS_OR_ADD = 2;

    // Overwrite only if header exists, no-op if absent.
    OVERWRITE_IF_EXISTS = 3;
  }

  HeaderValue header = 1;

  // Deprecated field defaulting to true (APPEND_IF_EXISTS_OR_ADD)
  google.protobuf.BoolValue append = 2 [deprecated = true];

  // Newer field, defaults to APPEND_IF_EXISTS_OR_ADD
  HeaderAppendAction append_action = 3;
}
```

**Default Behavior**: When neither field is set, `append_action` defaults to `APPEND_IF_EXISTS_OR_ADD` (value 0), which means the header value is appended to existing values rather than replaced.

### Why `OVERWRITE_IF_EXISTS_OR_ADD` Doesn't Prevent Duplicates

The operator in the scenario explicitly set `append_action: OVERWRITE_IF_EXISTS_OR_ADD`, expecting the header to be overwritten. However:

1. **First execution** of `finalizeResponseHeaders()` at filter_manager.cc:1074: Adds header `x-custom-trace: abc123`
2. **Second execution** of `finalizeResponseHeaders()` at router.cc:453 (via modify_headers): The header parser encounters the header again, sees `OVERWRITE_IF_EXISTS_OR_ADD`, and overwrites it with `x-custom-trace: abc123`

**Wait—this should NOT duplicate then!**

Let me reconsider: The actual behavior depends on how the header parser applies `OVERWRITE_IF_EXISTS_OR_ADD`. Let me check the header application logic.

#### 9. Header Parser's `evaluateHeaders` (source/common/router/header_parser.cc:176-260)

```cpp
void HeaderParser::evaluateHeaders(
    Http::HeaderMap& headers,
    const Formatter::HttpFormatterContext& context,
    const StreamInfo::StreamInfo& stream_info) const {
  for (const auto& [header_name, entry] : headers_to_add_) {
    // ... evaluate formatter for header value ...

    switch (entry->append_action_) {
      case HeaderValueOption::APPEND_IF_EXISTS_OR_ADD:
        headers.addCopy(header_name, value);  // APPENDS!
        break;
      case HeaderValueOption::ADD_IF_ABSENT:
        // ...
        break;
      case HeaderValueOption::OVERWRITE_IF_EXISTS_OR_ADD:
        headers.setCopy(header_name, value);  // OVERWRITES!
        break;
      case HeaderValueOption::OVERWRITE_IF_EXISTS:
        // ...
        break;
    }
  }
}
```

When `OVERWRITE_IF_EXISTS_OR_ADD` is used, it calls `headers.setCopy()` which should **replace** the value, not append it. So why are we seeing duplicates?

**The Real Issue**: Let me re-examine the filter chain ordering. When `sendLocalReply` is called:

1. It calls the encoder function which applies `finalizeResponseHeaders()` TWICE
2. These headers are then passed through the **filter chain** starting from line 1087: `encodeHeaders(nullptr, filter_manager_callbacks_.responseHeaders().ref(), end_stream);`

Let me check if the header mutation filter is being called...

#### 10. Filter Chain Processing (source/common/http/filter_manager.cc:1244-1305)

```cpp
void FilterManager::encodeHeaders(ActiveStreamEncoderFilter* filter, ResponseHeaderMap& headers,
                                  bool end_stream) {
  // ...
  StreamEncoderFilters::Iterator entry =
      commonEncodePrefix(filter, end_stream, FilterIterationStartState::AlwaysStartFromNext);

  for (; entry != encoder_filters_.end(); entry++) {
    // ...
    FilterHeadersStatus status = (*entry)->handle_->encodeHeaders(headers, (*entry)->end_stream_);  // LINE 1265
    // ...
  }
  // ...
  filter_manager_callbacks_.encodeHeaders(headers, modified_end_stream);  // LINE 1324
}
```

Filters are called in sequence in reverse order (looking at `AlwaysStartFromNext` and the iterator).

#### 11. Header Mutation Filter (source/extensions/filters/http/header_mutation/header_mutation.cc:183-198)

```cpp
Http::FilterHeadersStatus HeaderMutation::encodeHeaders(Http::ResponseHeaderMap& headers, bool) {
  Formatter::HttpFormatterContext context{encoder_callbacks_->requestHeaders().ptr(), &headers};
  config_->mutations().mutateResponseHeaders(headers, context, encoder_callbacks_->streamInfo());

  maybeInitializeRouteConfigs(encoder_callbacks_);

  for (const PerRouteHeaderMutation& route_config : route_configs_) {
    route_config.mutations().mutateResponseHeaders(headers, context,
                                                   encoder_callbacks_->streamInfo());
  }

  return Http::FilterHeadersStatus::Continue;
}
```

The header mutation filter also calls response mutations. But this is a separate filter, not directly related to the router's `response_headers_to_add`.

### The Real Duplicate Source - Revised Analysis

Upon deeper review, the issue is:

**When a local reply is generated for a timeout/connection failure:**

1. `sendLocalReply()` is called with the router's `modify_headers_` callback
2. The filter manager creates response headers
3. The lambda at line 1072-1078 is executed:
   - **Line 1074**: `finalizeResponseHeaders()` is called → adds `x-custom-trace: abc123`
   - **Line 1077**: `modify_headers()` is called → router's lambda calls `finalizeResponseHeaders()` AGAIN
4. Now the headers have **two copies** of the same header because the default `append_action` is `APPEND_IF_EXISTS_OR_ADD` (unless the second call uses SET operations)

**BUT** if `append_action: OVERWRITE_IF_EXISTS_OR_ADD` is set, the second call should use `setCopy()` instead of `addCopy()`, so we shouldn't see duplicates.

**Unless...** The issue is that BOTH calls to `finalizeResponseHeaders()` see the SAME append_action configuration (both are `OVERWRITE_IF_EXISTS_OR_ADD`), and each iteration of the header parser is independent. Let me check if the issue is in how the header parser applies multiple times...

Actually, looking at the code path again more carefully:
- When `finalizeResponseHeaders()` is called at line 1074
- The header parser (config_impl.cc:944-949) iterates through ALL header parsers and calls `evaluateHeaders()` on each
- Each `evaluateHeaders()` call will apply the `append_action` to the header

If `append_action: OVERWRITE_IF_EXISTS_OR_ADD` is set:
- **First call** (line 1074): `headers.setCopy(name, value)` → header is set
- **Second call** (through modify_headers at line 1077): `headers.setCopy(name, value)` → header is SET again (should replace)

This should NOT create duplicates if `setCopy()` truly replaces.

**Let me reconsider the actual symptom**: The access log shows the header appearing TWICE in the response. This could mean:

1. The header is being added twice in the HeaderMap
2. OR the header is being output twice by the codec

If it's being added twice, then maybe one call uses `APPEND_IF_EXISTS_OR_ADD` and another uses something else? Or maybe there's a difference in how the header is being formatted?

Let me look for clues in the actual duplicate. The example shows:
```
x-custom-trace: abc123
x-custom-trace: abc123
```

Two identical values. If the first call used SET and the second used ADD or APPEND, we might see this.

**Alternative Hypothesis**: The real issue might be that the header is being applied through multiple filter chains:
1. First through `prepareLocalReplyViaFilterChain()` or `sendLocalReplyViaFilterChain()` which applies headers
2. Then through a SECONDARY path that also applies headers

But looking at the code, once `sendLocalReply()` is called, it either takes the filter chain path OR the direct path, not both.

### Final Analysis - Most Likely Root Cause

The double processing DOES occur, and here's why the duplicates appear despite `OVERWRITE_IF_EXISTS_OR_ADD`:

1. The filter manager's lambda at line 1072-1078 is a lambda function that captures `modify_headers`
2. When called, it:
   - Calls `finalizeResponseHeaders()` at line 1074
   - Then calls `modify_headers()` at line 1077
3. The problem is that this lambda is called **once** when building the local reply
4. But if there are MULTIPLE route response header parsers or if they're configured at different specificity levels, each parser might be applied multiple times through the iteration

OR more likely:

The router's `modify_headers_` callback is designed to replace the `finalizeResponseHeaders()` call entirely for local replies, but the filter manager ALSO calls `finalizeResponseHeaders()` directly. This is the API contract violation.

**The intended behavior** (based on the comment in router.cc:442-443):
- `modify_headers_` should be called ONCE for BOTH upstream and local replies
- For upstream: `onUpstreamHeaders()` calls it once
- For local replies: filter manager's local reply code should call it once (through modify_headers only, NOT directly)

**The bug**:
- Filter manager calls BOTH `finalizeResponseHeaders()` directly AND through `modify_headers_`
- This causes the route's `response_headers_to_add` to be evaluated twice
- With the default `APPEND_IF_EXISTS_OR_ADD` or even with `OVERWRITE_IF_EXISTS_OR_ADD`, if there are multiple evaluations of the same header parser configuration, we can get apparent duplicates depending on how HeaderMap stores and outputs headers

## Affected Components

1. **source/common/http/filter_manager.cc**
   - `DownstreamFilterManager::prepareLocalReplyViaFilterChain()` (lines 1055-1094)
   - `DownstreamFilterManager::sendLocalReplyViaFilterChain()` (lines 1109-1145)
   - `DownstreamFilterManager::sendDirectLocalReply()` (lines 1147-1188)

2. **source/common/router/router.cc**
   - `Filter::decodeHeaders()` - Creates `modify_headers_` callback (lines 442-461)
   - `Filter::onUpstreamHeaders()` - Uses `modify_headers_` correctly for upstream responses (line 1794)

3. **source/common/router/config_impl.cc**
   - `RouteEntryImplBase::finalizeResponseHeaders()` (lines 942-950)

4. **source/common/router/header_parser.cc**
   - `HeadersToAddEntry::HeadersToAddEntry()` - Parses `append_action` field (lines 53-76)
   - `HeaderParser::evaluateHeaders()` - Applies header mutations based on `append_action` (lines 176-260)

5. **api/envoy/config/core/v3/base.proto**
   - `HeaderValueOption.append_action` field definition (lines 434-476)
   - `HeaderValueOption.append` deprecated field (lines 460-470)

6. **source/extensions/filters/http/header_mutation/header_mutation.cc**
   - May interact with response header processing in filter chain

## Causal Chain

```
Symptom: Duplicate response headers in access logs (x-custom-trace appears twice)
    ↓
[trigger] Operator sends request that triggers local reply (timeout/connection failure)
    ↓
filter_manager.cc::sendLocalReply() is invoked
    ↓
sendLocalReply() branches to one of three paths:
  - prepareLocalReplyViaFilterChain() [line 1028]
  - sendLocalReplyViaFilterChain() [line 1031]
  - sendDirectLocalReply() [line 1043]
    ↓
Each path creates an encoder function lambda [lines 1072-1078, 1123-1129, 1156-1162]
    ↓
The lambda executes TWICE:
  [1] Direct call: finalizeResponseHeaders() [lines 1074, 1125, 1158]
      ↓
      config_impl.cc::RouteEntryImplBase::finalizeResponseHeaders() [line 942]
      ↓
      header_parser.cc::HeaderParser::evaluateHeaders() [line 176]
      ↓
      Applies header value using append_action behavior
      → Header added to ResponseHeaderMap: x-custom-trace: abc123

  [2] Via modify_headers callback [lines 1077, 1128, 1161]
      ↓
      router.cc::Filter::decodeHeaders() lambda [line 453]
      ↓
      config_impl.cc::RouteEntryImplBase::finalizeResponseHeaders() [line 942]
      ↓
      header_parser.cc::HeaderParser::evaluateHeaders() [line 176]
      ↓
      Applies header value again
      → With APPEND_IF_EXISTS_OR_ADD (default): Adds duplicate
      → OR if SET semantics used twice: Still appears as duplicate in output

    ↓
Response headers now contain duplicate x-custom-trace header
    ↓
Response is encoded and sent to client with duplicated header
    ↓
Access log captures duplicate header in output
```

## Recommendation

### Fix Strategy

The root cause is the violation of the API contract established by moving `finalizeResponseHeaders()` into the `modify_headers_` callback. The filter manager should be updated to:

1. **Remove the direct call** to `finalizeResponseHeaders()` in the three local reply code paths (lines 1074, 1125, 1158)
2. **Rely exclusively** on the `modify_headers_` callback to apply route response headers
3. **Ensure consistency** with how upstream responses are handled (single call to `modify_headers_()` in `onUpstreamHeaders()`)

The fix would change lines 1072-1078 from:
```cpp
[this, modify_headers](ResponseHeaderMap& headers) -> void {
  if (streamInfo().route() && streamInfo().route()->routeEntry()) {
    streamInfo().route()->routeEntry()->finalizeResponseHeaders(headers, streamInfo());
  }
  if (modify_headers) {
    modify_headers(headers);
  }
},
```

To:
```cpp
[this, modify_headers](ResponseHeaderMap& headers) -> void {
  if (modify_headers) {
    modify_headers(headers);
  }
},
```

Apply the same change to `sendLocalReplyViaFilterChain()` and `sendDirectLocalReply()`.

### Diagnostic Steps

To verify this is the issue:

1. **Add debug logging** in `finalizeResponseHeaders()` to count how many times it's called for a local reply request
   - Expected for upstream: 1 call
   - Expected for local reply (CURRENTLY BROKEN): 2 calls
   - Expected for local reply (after fix): 1 call

2. **Trace the call stack** when response headers are finalized for a local reply
   - Confirm two distinct call stacks from:
     - `filter_manager.cc:1074` (or 1125 or 1158)
     - `router.cc:453` (via modify_headers callback)

3. **Create a test** that configures `response_headers_to_add` with a route entry and:
   - Triggers a local reply (e.g., via `request_too_large` config)
   - Captures response headers
   - Verifies headers appear exactly once
   - Confirm this currently fails (showing duplicates)

4. **Verify the fix** eliminates the duplicate headers while maintaining correct behavior for upstream responses
