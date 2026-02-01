```markdown
<!--
  SynestheticCanvas/docs/index.md

  Primary entry point for the SynestheticCanvas API Suite documentation.
  All examples are written in standard C17 and compile cleanly on *nix
  systems with GNU Make and the stock tool-chain (`gcc`, `clang`, `make`).
  Copy & paste any of the code blocks into your project, then run:

      $ make run-example

  to execute the end-to-end demonstration (gateway bootstrap ➜ GraphQL
  round-trip ➜ graceful shutdown).

  ──────────────────────────────────────────────────────────────────────────
  Contents
  ──────────────────────────────────────────────────────────────────────────
  • Introduction
  • High-Level Architecture
  • Quick-Start (5 Minutes)
  • Example: Bootstrapping the Gateway in C
  • Example: Performing a GraphQL Query from C
  • Error-Handling & Observability
  • Versioning & Pagination
  • Deployment Topology
  • Contributing
-->

# SynestheticCanvas 🖌️🎼📈 — Developer Index

SynestheticCanvas is a constellation of narrowly-scoped, high-performance C
microservices that collectively expose a **color-coded GraphQL/REST gateway**.
Every endpoint is treated as a _brush-stroke_, letting users orchestrate
dynamic audio-reactive visuals, narrative branching, and real-time texture
synthesis from a single API surface.

The suite prioritizes rock-solid stability (millisecond-level latency,
zero-downtime deploys) **without compromising on creative freedom**. Services
snap together like LEGO bricks thanks to an opinionated composition pattern:

```
┌───────────────┐    GraphQL + REST   ┌───────────────┐
│ Palette Svc   │  ◄────────────────► │ Texture Svc   │
└───────────────┘                     └───────────────┘
         ▲                                   ▲
         │  gRPC / NATS                      │
┌────────┴────────┐               ┌──────────┴───────────┐
│ Narrative Svc   │               │ Audio-Reactive Svc   │
└─────────────────┘               └──────────────────────┘
          ▲                                    ▲
          └───────────────┬────────────────────┘
                          │
                    ┌─────┴─────┐
                    │ API Gateway│
                    └───────────┘
```

---

## Quick-Start (5 Minutes)

1. Dependencies  
   • C17-compliant compiler (`gcc ≥ 10`, `clang ≥ 12`)  
   • `libcurl` (HTTP transport)  
   • `cJSON`  (minimal JSON parsing)  
   • `OpenSSL` (TLS I/O)  

2. Clone & build:

```bash
$ git clone https://github.com/SynestheticCanvas/api_graphql.git
$ cd api_graphql
$ make
```

3. Start the gateway:

```bash
$ ./bin/sc_gateway --config configs/gateway/dev.toml
[INFO] 2024-05-06T12:00:00Z Gateway listening on :8080 (http) / :8443 (https)
```

4. Run the end-to-end example (creates a palette and asks for the current
   swatch in a single GraphQL round-trip):

```bash
$ make run-example
```

---

## Example #1 — Bootstrapping the Gateway in C

The gateway runtime is fully embeddable. You can spawn it from your own
process, wire up custom middleware, or expose advanced telemetry hooks.

```c
/*
 * examples/gateway_bootstrap.c
 *
 * Compile:
 *   gcc -std=c17 -Wall -Wextra -pedantic -O2 \
 *       examples/gateway_bootstrap.c \
 *       src/gateway/sc_gateway.c \
 *       -Iinclude -lcurl -lcrypto -lpthread -o bin/gateway_bootstrap
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>

#include "sc_gateway.h"          /* Core gateway runtime */
#include "sc_logger.h"           /* Pluggable structured logger */
#include "sc_monitoring.h"       /* Prometheus / OpenTelemetry helpers */

static volatile sig_atomic_t g_stop = 0;

static void sigint_handler(int signo)
{
    (void)signo;
    g_stop = 1;
}

/* Custom request validator: reject payloads larger than 64 KiB */
static int validate_request(const sc_request_t *req, char *errbuf, size_t errsz)
{
    if (req->body_len > 65536) {
        snprintf(errbuf, errsz, "Payload exceeds 64 KiB limit (got %zu bytes)",
                 req->body_len);
        return -1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    (void)argc; (void)argv;

    /* 1) Install Ctrl-C handler for graceful shutdown */
    struct sigaction sa = { .sa_handler = sigint_handler };
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = 0;
    sigaction(SIGINT, &sa, NULL);

    /* 2) Configure logger */
    sc_log_config_t log_cfg = {
        .level      = SC_LOG_INFO,
        .colorize   = 1,
        .json       = 0,
        .timestamp  = 1
    };
    sc_logger_init(&log_cfg);

    /* 3) Monitoring (Prometheus metrics on :9100/metrics) */
    sc_monitoring_start(9100);

    /* 4) Gateway options */
    sc_gateway_options_t gw_opts = {
        .http_port         = 8080,
        .https_port        = 8443,
        .tls_cert_path     = "certs/dev.pem",
        .tls_key_path      = "certs/dev.key",
        .schema_path       = "schemas/v1.graphql",
        .plugin_dir        = "plugins",
        .validate_cb       = validate_request,
        .max_concurrency   = 512,
        .request_timeout_s = 15,
        .cache_ttl_s       = 30
    };

    /* 5) Launch the gateway */
    sc_gateway_t *gw = sc_gateway_create(&gw_opts);
    if (!gw) {
        SC_LOG_FATAL("Failed to initialize API gateway");
        return EXIT_FAILURE;
    }
    SC_LOG_INFO("Gateway bootstrapped on http://localhost:%d", gw_opts.http_port);

    /* 6) Event loop */
    while (!g_stop) {
        if (sc_gateway_poll(gw, 100 /* ms */) < 0) {
            SC_LOG_ERROR("Gateway poll error — shutting down");
            break;
        }
    }

    /* 7) Cleanup */
    sc_gateway_destroy(gw);
    sc_monitoring_stop();
    sc_logger_shutdown();

    SC_LOG_INFO("Gateway shutdown complete — goodbye!");
    return EXIT_SUCCESS;
}
```

Compile the snippet (`make example-gateway`) and run:

```
$ ./bin/gateway_bootstrap
[INFO] 2024-05-06T12:05:00Z Gateway bootstrapped on http://localhost:8080
```

Press `Ctrl-C` to invoke the graceful shutdown path.

---

## Example #2 — Performing a GraphQL Query from C

Below is a minimal GraphQL client that:
1. Issues a `createPalette` mutation  
2. Retrieves the newly created palette via a `currentSwatch` query

The code uses `libcurl` for HTTP transport and `cJSON` for parsing the JSON
response.

```c
/*
 * examples/graphql_roundtrip.c
 *
 * Build:
 *   gcc -std=c17 -Wall -Wextra -pedantic -O2 \
 *       examples/graphql_roundtrip.c \
 *       -lcurl -lcjson -o bin/graphql_roundtrip
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <curl/curl.h>
#include <cjson/cJSON.h>

#define ENDPOINT "http://localhost:8080/graphql"
#define USER_AGENT "SynestheticCanvasClient/1.0 (+https://synestheticcanvas.io)"

struct buffer {
    char  *data;
    size_t size;
};

static size_t write_cb(char *ptr, size_t size, size_t nmemb, void *userdata)
{
    size_t realsz = size * nmemb;
    struct buffer *buf = userdata;

    char *new_data = realloc(buf->data, buf->size + realsz + 1);
    if (!new_data) return 0;
    buf->data = new_data;

    memcpy(buf->data + buf->size, ptr, realsz);
    buf->size += realsz;
    buf->data[buf->size] = '\0';
    return realsz;
}

static int perform_graphql(const char *json_payload)
{
    CURL *curl = curl_easy_init();
    if (!curl) {
        fprintf(stderr, "curl_easy_init() failed\n");
        return -1;
    }

    struct buffer resp = { .data = NULL, .size = 0 };

    struct curl_slist *hdrs = NULL;
    hdrs = curl_slist_append(hdrs, "Content-Type: application/json");
    hdrs = curl_slist_append(hdrs, "Accept: application/json");

    curl_easy_setopt(curl, CURLOPT_URL, ENDPOINT);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(curl, CURLOPT_USERAGENT, USER_AGENT);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_payload);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &resp);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);

    CURLcode res = curl_easy_perform(curl);
    if (res != CURLE_OK) {
        fprintf(stderr, "curl_easy_perform() failed: %s\n",
                curl_easy_strerror(res));
        curl_easy_cleanup(curl);
        curl_slist_free_all(hdrs);
        free(resp.data);
        return -1;
    }

    long status_code = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status_code);
    printf("[HTTP %ld] %s\n", status_code, resp.data);

    /* Basic success check */
    if (status_code != 200) {
        fprintf(stderr, "Non-200 status code\n");
    }

    /* Parse JSON (extract paletteId if present) */
    cJSON *root = cJSON_Parse(resp.data);
    if (!root) {
        fprintf(stderr, "Invalid JSON response\n");
    } else {
        cJSON *data = cJSON_GetObjectItem(root, "data");
        if (data) {
            cJSON *create = cJSON_GetObjectItem(data, "createPalette");
            if (create) {
                cJSON *pid = cJSON_GetObjectItem(create, "paletteId");
                if (cJSON_IsString(pid)) {
                    printf("🎨  Created Palette ID: %s\n", pid->valuestring);
                }
            }
        }
        cJSON_Delete(root);
    }

    /* Cleanup */
    curl_easy_cleanup(curl);
    curl_slist_free_all(hdrs);
    free(resp.data);
    return 0;
}

int main(void)
{
    /* 1) Create a palette */
    const char *mutation =
        "{"
        "  \"query\": \"mutation($name:String!){createPalette(name:$name){paletteId}}\","
        "  \"variables\": {\"name\":\"Sunset Serenade\"}"
        "}";

    if (perform_graphql(mutation) < 0) return EXIT_FAILURE;

    /* 2) Query current swatch */
    const char *query =
        "{"
        "  \"query\": \"{currentSwatch{hex rgb}}\""
        "}";

    if (perform_graphql(query) < 0) return EXIT_FAILURE;

    return EXIT_SUCCESS;
}
```

---

## Error-Handling & Observability

• **Structured logging** (`SC_LOG_INFO`, `SC_LOG_WARN`, `SC_LOG_ERROR`)  
  are emitted in **JSON** or **colorized plain-text** according to runtime
  flags (`--log-fmt=json` vs default).

• Every request carries a **trace-id** header; distributed traces are exported
  to OpenTelemetry via OTLP/gRPC, viewable in Jaeger or Grafana Tempo.

• The gateway enforces:
  – Request timeout (`15 s` default)  
  – Payload size limit (`64 KiB` default)  
  – Rate limiting (`token bucket`, configurable per API key)  
  – Retry budget for upstream microservices (`circuit-breaker`)  

---

## Versioning & Pagination

All schemas are semver-tagged (`v1`, `v2`, …). A `X-SC-Schema: v1` header is
required for **REST** calls. For GraphQL, clients pick the version via:

```graphql
query @schema(version: "1.0") {
  texture(id: "  …  ") { /* … */ }
}
```

Connections implement **cursor-based pagination**:

```graphql
{
  textures(first: 25, after: "opaqueCursor") {
    totalCount
    edges {
      node { id, name, resolution }
      cursor
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
```

---

## Deployment Topology

```
┌────────────────────┐  metrics/logs  ┌───────────────────┐
│    Prometheus      │◄──────────────►│   Grafana         │
└─────────┬──────────┘                └───────────┬───────┘
          │                                       │
      ┌───▼────────┐    gRPC    ┌─────────────────▼───────────┐
      │  API GW    │◄──────────►│ Palette Svc / … (N)         │
      └────────────┘            └─────────────────────────────┘
          ▲  ▲
          │  └── REST/pubsub ingress (webhooks, sensors, etc.)
          │
          └── GraphQL / REST egress to clients (Browsers, Unity, Unreal, …)
```

Each service ships a Dockerfile; the `compose/` directory contains an _opinionated_
development stack (`make dc-up`). K8s manifests live under `k8s/`.

---

## Contributing

1. Fork ➜ feature branch ➜ **signed commits**  
2. Run `make test && make format` locally (clang-format enforced)  
3. Open a PR; GitHub Actions will run the full CI pipeline:  
   Static Analysis → Unit Tests → Integration Tests → Security Scan  
4. Discuss, iterate, merge. Thank you for painting with us! 🖼️✨
```