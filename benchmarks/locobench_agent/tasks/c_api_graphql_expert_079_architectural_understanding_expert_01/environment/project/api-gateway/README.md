```markdown
# SynestheticCanvas API Gateway (`api_graphql`)

> “Every endpoint is a brush stroke.”  
> The **SynestheticCanvas API Gateway** unifies a constellation of micro-services—palette management, dynamic texture synthesis, audio-reactive animation, and narrative branching—behind a single color-coded GraphQL & REST façade.  
> Written in modern, production-grade **C17**, the gateway focuses on _performance_, _observability_, and _extensibility_.

---

## 1. Quick Start

```bash
# Clone & build the full constellation
git clone --recurse-submodules https://github.com/synestheticlabs/synesthetic-canvas.git
cd synesthetic-canvas/SynestheticCanvas/api-gateway
mkdir build && cd build
cmake -DCMAKE_BUILD_TYPE=Release ..
make -j$(nproc)

# Run gateway with default in-container config
./sc-api-gateway --config ../config/gateway.toml
```

The gateway listens by default on:

| Protocol | Port | Purpose                   |
|----------|------|---------------------------|
| HTTP/1.1 | 8080 | REST fallback endpoints   |
| HTTP/2   | 8443 | GraphQL over TLS (gRPC)   |
| UDP      | 8125 | Metrics (StatsD/Datadog)  |

---

## 2. Minimal Client Example (C17)

Below is a self-contained example that queries the `currentPalette` GraphQL endpoint with pagination & version headers.  
Build with: `cc -Wall -Wextra -pedantic -std=c17 client.c -lcurl -o client`

```c
/**
 * @file client.c
 * @brief Example consumer of SynestheticCanvas API Gateway.
 *
 * Demonstrates:
 *  - GraphQL query composition in C
 *  - HTTP/2 request with libcurl
 *  - Basic error handling
 *  - Versioned schema negotiation
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <curl/curl.h>

/* Convenience structure for dynamic buffer */
typedef struct {
    char   *data;
    size_t  size;
} buffer_t;

/* libcurl write-back to dynamic buffer */
static size_t on_write(char *ptr, size_t size, size_t nmemb, void *userdata)
{
    size_t    bytes = size * nmemb;
    buffer_t *buf   = userdata;

    char *new_data = realloc(buf->data, buf->size + bytes + 1);
    if (!new_data) return 0; /* abort transfer */

    buf->data = new_data;
    memcpy(buf->data + buf->size, ptr, bytes);
    buf->size += bytes;
    buf->data[buf->size] = '\0';
    return bytes;
}

/* Utility: fatal error & exit */
static void die(const char *msg, CURLcode code)
{
    fprintf(stderr, "ERROR: %s (%s)\n", msg, curl_easy_strerror(code));
    exit(EXIT_FAILURE);
}

int main(void)
{
    static const char *graphql_query =
        "{"
        "  currentPalette(page: 1, perPage: 10) {"
        "    id"
        "    name"
        "    colors { hex }"
        "    updatedAt"
        "  }"
        "}";

    /* JSON body with query */
    char json_body[1024];
    snprintf(json_body, sizeof(json_body),
             "{\"query\":\"%s\"}", graphql_query);

    /* Initialize curl */
    CURL *curl = curl_easy_init();
    if (!curl) {
        fputs("Unable to init curl\n", stderr);
        return EXIT_FAILURE;
    }

    buffer_t buf = { .data = NULL, .size = 0 };

    /* REST URL fallback; change to https://localhost:8443/graphql for TLS */
    curl_easy_setopt(curl, CURLOPT_URL, "http://localhost:8080/graphql");
    curl_easy_setopt(curl, CURLOPT_HTTP_VERSION, CURL_HTTP_VERSION_2_0);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_body);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, on_write);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &buf);

    /* Set mandatory headers */
    struct curl_slist *headers = NULL;
    headers = curl_slist_append(headers, "Content-Type: application/json");
    headers = curl_slist_append(headers, "X-SC-Schema-Version: 2024-06");
    headers = curl_slist_append(headers, "X-SC-Request-ID: demo-client-001");
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

    /* Perform request */
    CURLcode rc = curl_easy_perform(curl);
    if (rc != CURLE_OK) die("Gateway request failed", rc);

    /* HTTP status */
    long code;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &code);
    printf("HTTP %ld\n%s\n", code, buf.data);

    /* Cleanup */
    curl_slist_free_all(headers);
    free(buf.data);
    curl_easy_cleanup(curl);
    return 0;
}
```

---

## 3. Gateway Highlights

Feature                       | Implementation Details
------------------------------|-------------------------------------------------------------
Versioning                    | `X-SC-Schema-Version` header + Semantic schema directory
Command/Query Segregation     | `commands/` (mutations) vs `queries/` (reads) handlers
Request Validation            | JSON-Schema & libvalijson; early-reject invalid payloads
Observability                 | pluggable sinks (stdout, syslog, Loki); OpenTelemetry
Pagination                    | Cursor & offset styles; helpers in `libsc_pagination.a`
Rate Limiting                 | Token bucket (Redis backend) & adaptive load-shedding
Repository Pattern            | Driver-agnostic adapters (`repo/pg`, `repo/sqlite`, `repo/mock`)
Hot-Reload Schemas            | inotify/FS events → atomic swap registry
Memory Safety                 | μobject memory pool + **ASAN/UBSAN/O2** in CI

---

## 4. Directory Layout

```text
api-gateway/
├── CMakeLists.txt        # Strict flags & sanitizers
├── include/
│   ├── sc_gateway.h      # Public entry
│   ├── sc_log.h          # Colorized logger
│   └── sc_schema.h       # Dynamic GraphQL schema loading
├── src/
│   ├── gateway.c         # Main event loop (libuv)
│   ├── rest_router.c     # Path → handler
│   ├── graphql_server.c  # gRPC & HTTP/2
│   └── middleware/
│       ├── auth.c
│       ├── metrics.c
│       └── validator.c
├── config/
│   ├── gateway.toml
│   └── logging.toml
└── tests/
    ├── test_graphql.c
    └── test_validator.c
```

---

## 5. Building Against the Gateway (pkg-config)

```bash
export PKG_CONFIG_PATH=$PWD/build/pkgconfig:$PKG_CONFIG_PATH
cc -std=c17 -Wall my_service.c -o my_service \
    $(pkg-config --cflags --libs synestheticcanvas-gateway)
```

---

## 6. Contributing

1. Fork & create a feature branch (`feature/your-idea`).
2. Run `make pre-commit` to auto-format (`clang-format`) & lint (`cppcheck`).
3. Ensure tests + sanitizers pass locally: `make test && make memcheck`.
4. Submit a non-draft PR with the template filled.  
   _Quality code is colorful code._

---

## 7. License

The SynestheticCanvas suite is released under the **Apache 2.0** license.  
See [`LICENSE`](../../LICENSE) for details.
```