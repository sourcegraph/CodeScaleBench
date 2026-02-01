```markdown
# SynestheticCanvas – `api_graphql`
_The color-coded gateway that lets every creative micro-service paint on the same canvas._

---

## 1. Overview
SynestheticCanvas is a constellation of _component-based_ micro-services written in C and orchestrated through a single GraphQL/REST gateway.  
Every endpoint is treated as a **brush stroke** that composers, illustrators, video artists and interactive-fiction engines can combine to generate _living canvases_: visuals, sounds and stories that evolve in real time.

`api_graphql` is the public-facing entry point. It exposes:
* A **GraphQL** schema that is color-tagged for human readability.
* A **REST** fallback layer for legacy clients and health checks.
* A runtime plug-in system for versioned schemas, validators and repository adapters.

Production goals:
* End-to-end p99 latency below `4 ms` on commodity hardware.
* Horizontal scaling to 1 M events / sec per region.
* No breaking-change downtime during schema evolution.

---

## 2. Features
| Capability                    | Description                                                               |
| ----------------------------- | ------------------------------------------------------------------------- |
| Versioning                    | Multiple schema versions live side-by-side (`/v1`, `/v2-beta`, …).       |
| Request Validation            | JSON/YAML & GraphQL validation via exhaustive, generated parsers.        |
| Pagination                    | Cursor-based, bidirectional, stable across cluster restarts.             |
| Logging & Monitoring          | Structured logs (OpenTelemetry), Prom metrics, trace correlation IDs.    |
| Repository Pattern            | Pluggable persistence (`lmdb`, `sqlite`, `redis`, `s3`, …).              |
| Command/Query Separation      | Read models use lock-free ring buffers; writes are serialized by CQRS.    |
| Rate Limiting & Caching       | Token-bucket per user + adaptive preview cache (stale-while-revalidate). |

---

## 3. Architecture
```
      ┌───────────────┐
      │  Client App   │
      └──────┬────────┘
             │ GraphQL/REST
             ▼
      ┌───────────────────┐
      │  api_graphql      │  ← You are here
      │  (Reverse Proxy)  │
      └────┬─────┬────────┘
  ┌────────┘     └───────────────┐
  ▼                              ▼
Palette-Svc                 Texture-Svc
(narrative-svc, audio-svc, …)  …
```

High-level patterns:
* **API Gateway**: Single ingress, JWT authentication, per-service timeouts, circuit breakers.
* **Service Layer**: Each micro-service contains its own business logic and persistence.
* **GraphQL Schema Composer**: Merges per-service SDL files, color-codes types by domain.
* **Repository Adapters**: Hot-swappable persistence back-ends using a thin V-table.

---

## 4. Getting Started

### 4.1. Prerequisites
* `gcc >= 13` or `clang >= 17`
* `meson >= 1.2` & `ninja`
* `libgraphqlparser` (submodule included)
* `cmocka` (for tests)
* `openssl >= 3.0`
* Optional: `docker` & `docker-compose`

### 4.2. Build
```bash
git clone --recurse-submodules https://github.com/synesthetic-canvas/api_graphql.git
cd api_graphql
meson setup build
ninja -C build
sudo ninja -C build install          # optional
```

### 4.3. Run
```bash
export SC_PORT=8080
export SC_LOG_LEVEL=info
export SC_PLUGIN_DIR=/usr/local/lib/synesthetic_canvas/plugins
./build/bin/api_graphql
```
Visit `http://localhost:8080/graphiql` for interactive playground.

---

## 5. Usage

### 5.1. Sample GraphQL Mutation
```graphql
mutation {
  createBrushStroke(
    input: {
      layerID: "overlay"
      palette: "cyberpunk"
      textureURL: "ipfs://Qm..."
      opacity: 0.85
    }
  ) {
    strokeID
    layer {
      id
      name
    }
  }
}
```

### 5.2. REST Fallback
```http
POST /v1/brush-strokes HTTP/1.1
Content-Type: application/json

{
  "layerID": "overlay",
  "palette":  "cyberpunk",
  "textureURL": "ipfs://Qm...",
  "opacity": 0.85
}
```

---

## 6. Environment Variables
| Name                    | Default | Description                                      |
| ----------------------- | ------- | ------------------------------------------------ |
| `SC_PORT`               | `8080`  | Listening port                                   |
| `SC_LOG_LEVEL`          | `info`  | `trace`, `debug`, `info`, `warn`, `error`        |
| `SC_PLUGIN_DIR`         |  –      | Directory for hot-loaded schema / repo plug-ins   |
| `SC_MAX_REQUEST_BYTES`  | `1048576` | Hard cap per HTTP request                       |
| `SC_JWT_PUBLIC_KEY`     |  –      | Path or literal PEM for auth verification        |
| `SC_METRICS_ADDR`       | `0.0.0.0:9100` | Prometheus exporter bind address       |

---

## 7. Development Hints

### 7.1. Hot-Reloading Schemas
1. Drop a compiled `.so` into `$SC_PLUGIN_DIR`.
2. Hit `SIGHUP`.  
   The gateway snapshots active requests, unloads the old module, loads the new one, and resumes traffic in < 5 ms.

### 7.2. Debugging
```bash
gdb --args build/bin/api_graphql --config etc/dev.toml
```

### 7.3. Unit Tests
```bash
meson test -C build --verbose
```

### 7.4. Linting
We enforce [`clang-format`](./.clang-format) and [`cppcheck`](./scripts/lint.sh) in CI.

---

## 8. Example C Snippet

The following handler demonstrates the canonical sandwich of **validation → business logic → repository → response**.

```c
/**
 * strokes_create_handler.c – POST /v1/brush-strokes
 *
 * build: part of libsc_handlers.so
 */
#include "sc_graphql.h"
#include "sc_json.h"
#include "sc_repo.h"
#include "sc_logging.h"

int strokes_create_handler(sc_context_t *ctx)
{
    sc_json_t *req = sc_json_parse(ctx->body);
    if (!req) {
        return sc_ctx_reply_error(ctx, 400, "Invalid JSON");
    }

    // Validate required fields
    const char *layer_id   = sc_json_get_string(req, "layerID");
    const char *palette    = sc_json_get_string(req, "palette");
    const char *texture    = sc_json_get_string(req, "textureURL");
    double      opacity    = sc_json_get_double (req, "opacity", 1.0);

    if (!layer_id || !palette || !texture || opacity < 0.0 || opacity > 1.0) {
        return sc_ctx_reply_error(ctx, 422, "Validation failed");
    }

    // Build domain object
    sc_stroke_t stroke = {
        .layer_id  = layer_id,
        .palette   = palette,
        .texture   = texture,
        .opacity   = opacity
    };

    // Repository write
    sc_repo_t *repo = sc_repo_get(ctx, "strokes");
    if (!repo) {
        return sc_ctx_reply_error(ctx, 500, "Repository unavailable");
    }

    sc_uuid_t stroke_id;
    if (sc_repo_strokes_insert(repo, &stroke, &stroke_id) != 0) {
        return sc_ctx_reply_error(ctx, 503, "Could not persist stroke");
    }

    // Build success response
    char uuid_str[SC_UUID_STRLEN];
    sc_uuid_to_str(&stroke_id, uuid_str);

    sc_json_t *resp = sc_json_object();
    sc_json_set_string(resp, "strokeID", uuid_str);
    sc_json_set_string(resp, "status",   "created");

    return sc_ctx_reply_json(ctx, 201, resp);
}
```

---

## 9. Monitoring & Observability

* **Structured Logs**: `_json` lines; one event per line. Correlation IDs in `sc_trace_id`.
* **Metrics**: `/metrics` endpoint (Prometheus):
  ```
  sc_http_requests_total{method="POST",path="/v1/brush-strokes",status="201"} 42
  sc_request_duration_seconds_bucket{le="0.005"} 40
  ```
* **Tracing**: OpenTelemetry spans exported to Jaeger/Zipkin back-ends.

---

## 10. Contributing

Pull requests are welcome!  
Before submitting, please:
1. Run `meson test`.
2. `clang-format -i **/*.c **/*.h`.
3. Commit with a conventional message (`feat:`, `fix:`, …).

We operate under the **DCO**; sign-off your commits:  
`git commit -s -m "feat: add neon palette"`

---

## 11. License
SynestheticCanvas is released under the **MIT License**.  
See [LICENSE](./LICENSE) for full text.

---

> “The boundary between data and art is made of color.”  
> — _Project mantra_
```