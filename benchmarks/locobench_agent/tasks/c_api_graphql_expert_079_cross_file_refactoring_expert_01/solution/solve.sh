#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The solution requires modifications across multiple directories. Key changes would include:

**1. In `libs/sc_common/include/sc_errors.h`:**
```c
// New enum
typedef enum {
    SC_DOMAIN_UNKNOWN,
    SC_DOMAIN_COMMON,
    SC_DOMAIN_GATEWAY,
    SC_DOMAIN_PALETTE,
    SC_DOMAIN_TEXTURE,
    SC_DOMAIN_AUDIO,
    SC_DOMAIN_NARRATIVE
} sc_service_domain_t;

// New struct
typedef struct {
    sc_service_domain_t domain;
    int code; // Original, internal error code
    int http_status_code;
    char* message;
} sc_error_t;

// New function prototypes
sc_error_t* sc_error_create(sc_service_domain_t domain, int code, int http_status, const char* format, ...);
void sc_error_destroy(sc_error_t* err);
```

**2. Example refactoring in `services/palette-service/src/palette_service.c`:**

*Before:*
```c
int get_palette_by_id(const char* id, palette_t** palette) {
    // ... database logic ...
    if (db_result == NOT_FOUND) {
        return SC_PALETTE_ERROR_NOT_FOUND; // e.g., -1
    }
    // ... more logic ...
    return 0; // Success
}
```

*After:*
```c
#include "sc_errors.h"

sc_error_t* get_palette_by_id(const char* id, palette_t** palette) {
    // ... database logic ...
    if (db_result == NOT_FOUND) {
        return sc_error_create(SC_DOMAIN_PALETTE, SC_PALETTE_ERROR_NOT_FOUND, 404, "Palette with ID '%s' not found.", id);
    }
    // ... more logic ...
    return NULL; // Success
}
```

**3. Example refactoring in `api-gateway/src/rest/fallback_handlers.c`:**

*Logic Change:*
The handler that previously might have had a `switch` statement on an integer error code now receives an `sc_error_t*`. It can directly use the fields:
```c
void handle_service_error(http_request_t* req, http_response_t* res, sc_error_t* err) {
    if (err) {
        set_http_status(res, err->http_status_code);
        set_json_response_body(res, "{\"error\": \"%s\"}", err->message);
        sc_error_destroy(err); // Clean up the error object
    } else {
        // ... handle unexpected case where error is NULL
    }
}
```

**4. List of files expected to be modified:**
- `libs/sc_common/include/sc_errors.h`
- `libs/sc_common/src/sc_errors.c`
- `services/palette-service/include/palette_service.h`
- `services/palette-service/src/palette_service.c`
- `services/palette-service/src/palette_repository.c`
- `services/palette-service/src/palette_handler.c`
- `services/palette-service/tests/test_palette_service.c`
- `services/texture-service/include/texture_service.h`
- `services/texture-service/src/texture_service.c`
- `services/texture-service/src/texture_repository.c`
- `services/texture-service/src/texture_handler.c`
- `services/texture-service/tests/test_texture_service.c`
- `api-gateway/src/services/service_client.c`
- `api-gateway/src/rest/fallback_handlers.c` (or equivalent router/error handling logic)
- `CMakeLists.txt` files for affected modules if new dependencies are introduced (unlikely here, but possible).
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
