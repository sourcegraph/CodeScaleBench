# curl-multi-process-refac-001: Rename multi process function

## Task Type: Cross-File Refactoring (Rename)

Rename process_pending_handles → multi_activate_pending in curl.

## Key Reference Files
- `lib/multi.c` — function definition (static, ~line 3733)
- `lib/multihandle.h` — multi handle declarations
- `lib/url.c` — related transfer handling

## Search Strategy
- Search for `process_pending_handles` in lib/ for all references
- Search for `pending_handles\|pending.*handles` for related code
