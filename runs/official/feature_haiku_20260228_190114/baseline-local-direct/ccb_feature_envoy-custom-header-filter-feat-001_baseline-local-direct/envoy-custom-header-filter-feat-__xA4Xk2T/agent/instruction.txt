# Task: Implement Custom Header Injection Filter for Envoy

## Objective
Create a new HTTP filter `envoy.filters.http.custom_header_injection` that injects
configurable headers into requests and/or responses based on route metadata.

## Requirements

1. **Create filter source files**:
   - `source/extensions/filters/http/custom_header_injection/filter.h` — filter class declaration
   - `source/extensions/filters/http/custom_header_injection/filter.cc` — filter implementation
   - `source/extensions/filters/http/custom_header_injection/config.h` — factory declaration
   - `source/extensions/filters/http/custom_header_injection/config.cc` — factory registration

2. **Filter behavior**:
   - Implements `Http::StreamDecoderFilter` (request path) and `Http::StreamEncoderFilter` (response path)
   - Reads header injection rules from filter config
   - Supports both request and response header injection
   - Follows Envoy's filter lifecycle (decodeHeaders, encodeHeaders)

3. **Create test file**:
   - `test/extensions/filters/http/custom_header_injection/filter_test.cc`

## Key Reference Files
- `source/extensions/filters/http/header_to_metadata/filter.h` — simple header filter pattern
- `source/extensions/filters/http/header_to_metadata/filter.cc` — implementation pattern
- `source/extensions/filters/http/header_to_metadata/config.cc` — factory registration
- `source/extensions/filters/http/common/factory_base.h` — factory base class

## Success Criteria
- Filter header file declares class inheriting from StreamDecoderFilter/StreamEncoderFilter
- Filter implementation has decodeHeaders/encodeHeaders methods
- Factory config file registers the filter
- Follows Envoy naming: envoy.filters.http.custom_header_injection
- Test file exists
