# Task: Rename process_pending_handles to multi_activate_pending

## Objective
Rename the static `process_pending_handles` function to `multi_activate_pending` in curl's
multi interface to better describe its role of activating pending transfer handles.

## Requirements

1. **Rename function** in `lib/multi.c`:
   - `process_pending_handles` → `multi_activate_pending`
   - Keep it `static` (it's file-local)

2. **Update all call sites** within `lib/multi.c` (5+ references)

3. **Update any forward declarations** if present

## Key Reference Files
- `lib/multi.c` — function definition (static, ~line 3733) and all callers
- `lib/multihandle.h` — multi handle struct declarations
- `lib/url.c` — related transfer handling

## Success Criteria
- `process_pending_handles` no longer exists as function name
- `multi_activate_pending` used instead
- All call sites updated within multi.c
- Function signature unchanged (only name changed)
