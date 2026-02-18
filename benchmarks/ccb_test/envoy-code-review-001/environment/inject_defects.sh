#!/bin/bash
# Inject defects into the Envoy proxy codebase for code review benchmarking
# Each defect simulates a realistic bug that an AI code reviewer should catch
# 6 defects across 4 files, 3 require cross-file reasoning

set -e
cd /workspace

# ── Defect 1: Return Continue instead of StopIteration when delay is active ──
# Cross-file: fault_filter returns Continue, but postDelayInjection() later calls
# continueDecoding() via filter_manager.cc — the stream has already moved past
# this filter, causing undefined behavior or assertion failure
python3 -c "
path = 'source/extensions/filters/http/fault/fault_filter.cc'
with open(path) as f:
    content = f.read()

old = '''  if (maybeSetupDelay(headers)) {
    return Http::FilterHeadersStatus::StopIteration;
  }'''

new = '''  if (maybeSetupDelay(headers)) {
    return Http::FilterHeadersStatus::Continue;
  }'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-1: fault filter returns Continue instead of StopIteration when delay active')
"

# ── Defect 2: Invert header matching logic in HeaderUtility::matchHeaders ──
# Cross-file: This utility is called by fault_filter (line 130), RBAC, ratelimit,
# and other filters. Inverting it causes header-based fault injection to match
# on the WRONG requests (those NOT matching the configured headers)
python3 -c "
path = 'source/common/http/header_utility.cc'
with open(path) as f:
    content = f.read()

old = '''  if (!config_headers.empty()) {
    for (const HeaderDataPtr& cfg_header_data : config_headers) {
      if (!cfg_header_data->matchesHeaders(request_headers)) {
        return false;
      }
    }
  }

  return true;'''

new = '''  if (!config_headers.empty()) {
    for (const HeaderDataPtr& cfg_header_data : config_headers) {
      if (cfg_header_data->matchesHeaders(request_headers)) {
        return false;
      }
    }
  }

  return true;'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-2: inverted header matching logic in matchHeaders')
"

# ── Defect 3: Remove route cache clearing from ext_authz onComplete ──
# When ext_authz modifies request headers (adding auth headers, removing
# sensitive headers), the route cache must be cleared so downstream filters
# and the router see the updated route. Without this, stale routes are used.
python3 -c "
path = 'source/extensions/filters/http/ext_authz/ext_authz.cc'
with open(path) as f:
    content = f.read()

old = '''    // Any changes to request headers or query parameters can affect how the request is going to be
    // routed. If we are changing the headers we also need to clear the route
    // cache.
    if (config_->clearRouteCache() &&
        (!response->headers_to_set.empty() || !response->headers_to_append.empty() ||
         !response->headers_to_remove.empty() || !response->query_parameters_to_set.empty() ||
         !response->query_parameters_to_remove.empty())) {
      ENVOY_STREAM_LOG(debug, \"ext_authz is clearing route cache\", *decoder_callbacks_);
      decoder_callbacks_->downstreamCallbacks()->clearRouteCache();
    }'''

new = '''    // Any changes to request headers or query parameters can affect how the request is going to be
    // routed. Route cache clearing handled by downstream filters.'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-3: removed route cache clearing from ext_authz onComplete')
"

# ── Defect 4: Invert required response header check in filter_manager ──
# Cross-file: filter_manager calls HeaderUtility::checkRequiredResponseHeaders()
# (defined in header_utility.cc). Inverting the status check sends 502 for all
# valid responses and lets responses missing :status through
python3 -c "
path = 'source/common/http/filter_manager.cc'
with open(path) as f:
    content = f.read()

old = '''  const auto status = HeaderUtility::checkRequiredResponseHeaders(headers);
  if (!status.ok()) {
    // If the check failed, then we reply with BadGateway, and stop the further processing.
    sendLocalReply('''

new = '''  const auto status = HeaderUtility::checkRequiredResponseHeaders(headers);
  if (status.ok()) {
    // If the check failed, then we reply with BadGateway, and stop the further processing.
    sendLocalReply('''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-4: inverted required response header check in filter_manager')
"

# ── Defect 5: Invert rate limit check causing active_faults gauge leak ──
# In postDelayInjection, the gauge should be decremented when NO rate limit
# is configured (fault is done). Inverting this causes the gauge to be
# decremented when rate limit IS active (double-dec with onDestroy) and
# NOT decremented when it's not (leak), eventually exhausting max_active_faults
python3 -c "
path = 'source/extensions/filters/http/fault/fault_filter.cc'
with open(path) as f:
    content = f.read()

old = '''    ASSERT(fault_active_);
    ASSERT(delay_timer_ == nullptr);
    if (!isResponseRateLimitConfigured()) {
      config_->stats().active_faults_.dec();
      fault_active_ = false;
    }'''

new = '''    ASSERT(fault_active_);
    ASSERT(delay_timer_ == nullptr);
    if (isResponseRateLimitConfigured()) {
      config_->stats().active_faults_.dec();
      fault_active_ = false;
    }'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-5: inverted rate limit check causes active_faults gauge leak')
"

# ── Defect 6: Remove isRemovableHeader guard from ext_authz header removal ──
# ext_authz removes headers based on the external auth response. Without the
# isRemovableHeader check, :-prefixed pseudo-headers and Host can be removed,
# making the request malformed and causing 400 errors or protocol violations
python3 -c "
path = 'source/extensions/filters/http/ext_authz/ext_authz.cc'
with open(path) as f:
    content = f.read()

old = '''      // We don't allow removing any :-prefixed headers, nor Host, as removing them would make the
      // request malformed. checkDecoderHeaderMutation also performs this check, however, so only
      // perform this check explicitly if decoder header mutation rules is empty.
      if (!config_->hasDecoderHeaderMutationRules() &&
          !Http::HeaderUtility::isRemovableHeader(key)) {
        ENVOY_STREAM_LOG(trace, \"Ignoring invalid header removal '{}'.\", *decoder_callbacks_, key);
        continue;
      }'''

new = '''      // Header mutation rules handle validation if configured.'''

content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-6: removed isRemovableHeader guard from ext_authz header removal')
"

echo "All 6 defects injected successfully"
