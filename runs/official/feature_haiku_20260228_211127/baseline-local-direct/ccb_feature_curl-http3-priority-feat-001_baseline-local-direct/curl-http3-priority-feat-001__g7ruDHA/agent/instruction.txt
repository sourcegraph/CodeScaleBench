# Task: Implement HTTP/3 Extensible Priorities (RFC 9218) for curl

## Objective
Add HTTP/3 stream priority support to curl, implementing RFC 9218 Extensible Priorities
with urgency (0-7) and incremental (boolean) parameters.

## Requirements

1. **Add new curl option** `CURLOPT_H3_STREAM_PRIORITY`:
   - Define in `include/curl/curl.h` as a new CURLOPT
   - Implement in `lib/setopt.c` to store urgency + incremental values
   - Add to `lib/urldata.h` in the UserDefined struct

2. **Implement in HTTP/3 backend** (`lib/vquic/`):
   - Send PRIORITY_UPDATE frames via ngtcp2/nghttp3 API
   - Set stream priority during request setup
   - Handle priority for both initial request and subsequent updates

3. **Add CLI option** `--h3-priority`:
   - Parse in `src/tool_getparam.c`
   - Wire to CURLOPT in `src/tool_operate.c`
   - Format: `--h3-priority u=N[,i]` (urgency=N, incremental flag)

4. **Create test** `tests/unit/unit_h3_priority.c` or integration test

## Key Reference Files
- `include/curl/curl.h` — CURLOPT definitions
- `lib/setopt.c` — option handling
- `lib/urldata.h` — UserDefined struct (line ~1242 has RFC 9218 TODO)
- `lib/vquic/curl_ngtcp2.c` — ngtcp2 HTTP/3 backend
- `src/tool_getparam.c` — CLI argument parsing
- `src/tool_operate.c` — option wiring

## Success Criteria
- CURLOPT_H3_STREAM_PRIORITY defined in curl.h
- Priority fields added to urldata.h UserDefined struct
- Backend code references priority/urgency/incremental
- CLI option parsing exists
- Test file exists
