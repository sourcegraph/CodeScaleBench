```markdown
# SynestheticCanvas – Audio Service

The **Audio Service** transforms raw waveforms and live input streams into metadata and event queues that the rest of the SynestheticCanvas constellation can _paint with_.  
Think of it as the **conductor** of an orchestra: it analyses frequency bands, detects beats, classifies instruments, and publishes a color-coded “mood profile” over gRPC / REST / GraphQL in real-time.

---

## :file_folder:  Contents

| Path                               | Purpose                                                      |
| ---------------------------------- | ------------------------------------------------------------ |
| `src/`                             | Production-grade C sources                                   |
| `include/`                         | Public headers                                               |
| `proto/`                           | gRPC/Protobuf definitions (auto-generated REST & GraphQL)    |
| `docker/`                          | Minimal container spec, health checks                        |
| `tests/`                           | Unit + integration tests (Catch2)                            |
| `cmake/`                           | Toolchain abstraction, static analysis hooks                 |
| `scripts/`                         | CI helpers, coverage, linters                                |

---

## :rocket: Quick Start (Local)

```bash
git clone https://github.com/SynestheticCanvas/api_graphql.git
cd api_graphql/services/audio-service

# Build with CMake using the provided toolchain
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --parallel

# Run the service
./synesthetic-audio --config ../config/local.toml
```

---

## :wrench:  Minimal Example (C Client)

Below is a condensed, self-contained example demonstrating **how to consume the Audio Service** via the auto-generated gRPC stubs.  
Compile with:

```bash
gcc demo_client.c -o demo_client \
  `pkg-config --cflags --libs grpc protobuf-c` \
  -lpthread
```

<details>
<summary>Source: <code>demo_client.c</code></summary>

```c
/*
 * demo_client.c
 *
 * A minimal gRPC client that subscribes to the audio-analysis stream
 * and prints the live “mood palette” detected by the service.
 *
 * Build:
 *   gcc demo_client.c -o demo_client `pkg-config --cflags --libs grpc protobuf-c` -lpthread
 */

#include <grpc/grpc.h>
#include <grpc/byte_buffer.h>
#include <grpc/support/log.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "audio.pb-c.h"
#include "audio.grpc-c.h"

static volatile int keep_running = 1;
static void handle_sigint(int _) { (void)_; keep_running = 0; }

/* Convert RGB struct to ANSI escape color string */
static void rgb_to_ansi(const Audio__RGB *rgb, char *out, size_t len)
{
    snprintf(out, len, "\x1b[38;2;%u;%u;%um█\x1b[0m", rgb->r, rgb->g, rgb->b);
}

int main(void)
{
    signal(SIGINT, handle_sigint);

    grpc_init();
    grpc_channel *channel = grpc_insecure_channel_create("127.0.0.1:50051", NULL, NULL);
    grpc_completion_queue *cq = grpc_completion_queue_create_for_next(NULL);

    Audio__AudioServiceClient *client =
        audio__audio_service__client__new(channel);

    /* Prepare request: subscribe to stream in “HLS” (High-level Summary) mode */
    Audio__StreamRequest req = AUDIO__STREAM_REQUEST__INIT;
    req.mode = AUDIO__STREAM_MODE__STREAM_MODE_HLS;
    grpc_call *call =
        audio__audio_service__client__stream_palette(client, &req, cq, NULL);

    /* Send request */
    grpc_call_start_batch(call, NULL, 0, NULL, NULL);

    /* Async loop */
    while (keep_running) {
        grpc_event ev = grpc_completion_queue_next(cq, gpr_inf_future(GPR_CLOCK_REALTIME), NULL);
        if (ev.type == GRPC_OP_COMPLETE) {
            Audio__PaletteUpdate *update = ev.user_data;
            if (!update) continue;

            char ansi[32];
            rgb_to_ansi(update->dominant, ansi, sizeof ansi);
            printf("Time=%.2fs  Dominant=%s  Energy=%.1f\n",
                   update->timestamp_sec, ansi, update->energy);

            audio__palette_update__free_unpacked(update, NULL);
        }
    }

    grpc_completion_queue_shutdown(cq);
    grpc_completion_queue_destroy(cq);
    grpc_channel_destroy(channel);
    grpc_shutdown();

    return 0;
}
```
</details>

---

## :clipboard:  REST Reference (Version `v1`)

| Method | Path                       | Description                          |
| ------ | -------------------------- | ------------------------------------ |
| POST   | `/v1/analyze`              | One-shot analysis of a waveform      |
| GET    | `/v1/stream?mode=raw`      | Live WebSocket / SSE stream          |
| GET    | `/v1/health`               | Health probe (liveness / readiness)  |

All endpoints return the same _color-coded_ structure:

```jsonc
{
  "timestamp": 1703415502.23,
  "bpm": 122.4,
  "energy": 0.77,
  "moodPalette": [
    { "r": 253, "g": 94,  "b": 83 },
    { "r": 241, "g": 201, "b": 60 },
    { "r": 101, "g": 194, "b": 221 }
  ]
}
```

---

## :mag_right:  GraphQL Snippet

```graphql
type PaletteUpdate {
  timestamp: Float!
  bpm: Float!
  energy: Float!
  dominant: RGB!
  highlights: [RGB!]!
}

type Query {
  analyze(fileId: ID!): PaletteUpdate!
}

type Subscription {
  stream(mode: StreamMode! = HLS): PaletteUpdate!
}

enum StreamMode {
  RAW
  HLS
  SUMMARY
}
```

---

## :satellite:  Environment

| Variable                | Default        | Purpose                              |
| ----------------------- | -------------- | ------------------------------------ |
| `AUDIO_PORT`            | `50051`        | gRPC port                            |
| `AUDIO_HTTP_PORT`       | `8080`         | REST / GraphQL port                  |
| `AUDIO_MODEL_PATH`      | `./models`     | Folder storing ML models             |
| `AUDIO_LOG_LEVEL`       | `INFO`         | (`DEBUG`,`INFO`,`WARN`,`ERROR`)      |
| `AUDIO_MAX_CHANNELS`    | `2`            | Max audio channels per request       |

---

## :chart_with_upwards_trend: Monitoring Signals

| Metric                             | Type     | Description                         |
| ---------------------------------- | -------- | ------------------------------------ |
| `audio_bpm_gauge`                  | Gauge    | Current beats-per-minute estimation |
| `audio_energy_ratio`               | Gauge    | 0.0 – 1.0 normalized RMS            |
| `audio_requests_total`             | Counter  | Total processed analysis jobs       |
| `audio_request_duration_seconds`   | Histogram| Latency buckets for `/analyze`      |

Prometheus and Grafana dashboards are auto-deployed in Kubernetes via the shared Helm chart.

---

## :warning:  Error Codes

| Code | HTTP | Reason                                             |
| ---- | ---- | --------------------------------------------------- |
| `AU-001` | 400 | Unsupported audio format                         |
| `AU-002` | 413 | File too large / exceeds `maxDuration` threshold |
| `AU-003` | 500 | Internal decoder failure                         |
| `AU-004` | 429 | Rate-limit exceeded                              |

Errors are returned as per [RFC 7807](https://datatracker.ietf.org/doc/html/rfc7807) Problem Details, e.g.:

```json
{
  "type":   "https://synestheticcanvas.com/errors/AU-002",
  "title":  "File too large",
  "status": 413,
  "detail": "Max duration is 600 seconds, got 1143",
  "instance": "/v1/analyze"
}
```

---

## :test_tube:  Running Tests

```bash
cd services/audio-service
mkdir -p build && cd build
cmake .. -DENABLE_TESTS=ON
ctest --output-on-failure
```

---

## :handshake:  Contributing

1. Fork & Branch (`feature/<name>`)
2. Run formatter (`clang-format -i $(git ls-files '*.c' '*.h')`)
3. Ensure _all_ tests & linters pass (`scripts/ci_local.sh`)
4. Open Pull Request with a clear description

---

## :copyright:

© 2023-2024 SynestheticCanvas contributors.  
Released under the MIT License.  
See `LICENSE` at repo root for details.
```