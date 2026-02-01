```markdown
# CardioInsight360 – Public C++ API Documentation
Unified Healthcare Analytics Engine (v3.4.x)  
© 2024 PulseDynamics Health-IT, Inc. – All rights reserved.

---

## 1. Overview

CardioInsight360 is a monolithic C++17 analytics platform purpose-built for
large cardiology networks that must ingest, validate, transform, store, and
visualize *high-volume* physiological and operational data.  
This document targets **C++ application developers** who want to embed,
extend, or automate the engine through its **in-process public API**.

*If you are looking for REST/HTTP bindings, see* `docs/api/openapi.yaml`.

---

## 2. Quick Start

### 2.1. Build & Link

```console
# Clone (submodules include third-party libs: librdkafka, Apache Arrow, TBB)
$ git clone --recurse-submodules git@github.com:pulsedynamics/cardio_insight_360.git
$ cd cardio_insight_360 && mkdir build && cd build
$ cmake .. -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON
$ make -j$(nproc)
$ sudo make install   # Installs headers & libcardio_insight360.so
```

Add to your application’s `CMakeLists.txt`:

```cmake
find_package(CardioInsight360 REQUIRED)
target_link_libraries(my_app PRIVATE CardioInsight360::cardio_insight360)
```

---

## 3. Namespaces & Sub-Systems

| Namespace | Purpose | Key Classes |
|-----------|---------|-------------|
| `ci360::ingest`     | HL7/FHIR & streaming device intake | `Hl7Receiver`, `DeviceAdapter` |
| `ci360::transform`  | ETL Strategies / data quality | `Strategy`, `EcgDetrender`, `ArrhythmiaValidator` |
| `ci360::stream`     | Embedded Kafka bus | `EventBus`, `Producer`, `Consumer` |
| `ci360::storage`    | Data-Lake façade | `ParquetSink`, `LakeRouter` |
| `ci360::pipeline`   | Parallel orchestration | `Pipeline`, `Stage`, `JobContext` |
| `ci360::observe`    | Metrics & tracing | `MetricRegistry`, `Span` |
| `ci360::services`   | Pseudo-microservices | `Scheduler`, `RecoveryService` |

Full Doxygen HTML output lives under `build/docs/`.

---

## 4. Minimal End-to-End Example

The sample below shows how to
1. Boot the engine,  
2. Subscribe to an HL7 source,  
3. Apply a custom transformation strategy,  
4. Persist curated data to Parquet, and  
5. Expose a Prometheus metric.

```cpp
#include <ci360/Core.hpp>                 // engine_singleton()
#include <ci360/ingest/Hl7Receiver.hpp>
#include <ci360/transform/Strategy.hpp>
#include <ci360/transform/RegisterStrategy.hpp>
#include <ci360/storage/ParquetSink.hpp>
#include <ci360/observe/MetricRegistry.hpp>

using namespace ci360;

// (1) Custom Strategy: a very naïve QT-interval normalizer
class QtNormalizer final : public transform::Strategy
{
public:
    explicit QtNormalizer(double baselineMs = 390.0)
        : baseline_{baselineMs},
          correctedFrames_{observe::MetricRegistry::counter(
              "qt_normalizer_frames_total", "Total frames normalized")}
    {}

    transform::Result apply(const RawFrame& in,
                            CuratedFrame& out) noexcept override
    {
        try
        {
            out = in; // shallow copy meta fields
            out.qt   = in.qt / (in.rrInterval / baseline_);
            ++correctedFrames_;
            return transform::Result::Success;
        }
        catch (const std::exception& ex)
        {
            CI360_LOG_ERROR("QtNormalizer failure: {}", ex.what());
            return transform::Result::PermanentFailure;
        }
    }

private:
    double baseline_;
    observe::Counter& correctedFrames_;
};

// (2) Engine bootstrap
int main(int argc, char* argv[])
{
    try
    {
        // Singleton provides thread-safe initialization & shutdown
        auto& engine = Core::engine_singleton();
        engine.configure(CoreConfig{
            .threads = std::thread::hardware_concurrency(),
            .dataDir = "/data/lake"
        });

        // (3) Register our strategy with factory
        transform::register_strategy<QtNormalizer>("QtNormalizer");

        // (4) Ingest HL7 feed
        ingest::Hl7Receiver cfg{
            .host     = "10.1.7.23",
            .port     = 8500,
            .maxFrame = 4096,
        };
        auto receiver = engine.create<ingest::Hl7Receiver>(cfg);

        // (5) Storage sink
        storage::ParquetSink sink("/data/lake/curated/ecg");

        // (6) Wire the pipeline
        pipeline::Pipeline etl("ECG-ingest-pipeline");
        etl.add_stage([&receiver](pipeline::JobContext& ctx) {
                receiver->poll(ctx.cancel_token());
            })
           .add_stage(transform::make_stage({"QtNormalizer"}))
           .add_stage([&sink](pipeline::JobContext& ctx) {
                sink.append(ctx.frame());
            });

        engine.run_pipeline(etl);
        engine.block_until_shutdown();
    }
    catch (const std::exception& ex)
    {
        CI360_LOG_CRITICAL("Fatal: {}", ex.what());
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}
```

Build:

```console
$ g++ -std=c++17 -O2 demo.cpp -lcardio_insight360 -o demo
```

---

## 5. Sub-System Reference

### 5.1. Ingestion (`ci360::ingest`)

```cpp
ingest::DeviceAdapter ecg("BLE:AA:BB:CC:DD:EE");
ecg.set_on_frame([](const RawFrame& f) {
    // Forward to pipeline or do local processing
});
ecg.start();
```

* Zero-copy frame hand-off using `std::span`.
* Built-in loss detection and back-pressure signaling.
* Thread-safe; uses reactor pattern under the hood.

### 5.2. Transformation Strategies

Create, then register with the compile-time factory:

```cpp
class ZeroPhaseFilter final : public Strategy { ... };
transform::register_strategy<ZeroPhaseFilter>("ZeroPhaseFilter");
```

Strategies are hot-swappable at runtime through JSON config reload (`SIGHUP`).

### 5.3. Event Bus

```cpp
stream::EventBus bus({"kafka01:9092", "kafka02:9092"});
bus.producer("arrhythmia.alerts").send(key, value, timestamp);
```

* Exactly-once semantics via idempotent producer & transactions.
* Consumer groups support manual & automatic offset control.

### 5.4. Storage

```cpp
storage::ParquetSink sink("/lake/curated/SpO2",
                          storage::ParquetOptions{
                                .compression = storage::Compression::ZSTD,
                                .rowGroupMB  = 128
                          });
```

* Schema evolution tracked in `/lake/_schemas/`.
* Optional AES-256 encryption at rest.

### 5.5. Observability

```cpp
auto heartbeat = observe::MetricRegistry::gauge(
        "engine_heartbeat_seconds", "Seconds since start");
observe::Tracer::current_span().set_tag("patient_id", "123-456-ABC");
```

Prometheus, OpenTelemetry, and Jaeger exporters are built-in.

---

## 6. Error Handling Strategy

1. **Transient** errors (network hiccups) trigger *automatic retries* with
   exponential back-off (configurable per component).
2. **Permanent** errors bubble up to the `RecoveryService`, which
   a) quarantines corrupt input,  
   b) persists a remediation ticket into the incident queue, and  
   c) notifies on-call via the integrated pager duty bridge.

Developers hook into this flow via:

```cpp
services::RecoveryService::subscribe([](const Incident& i) {
    // Custom remediation, e.g., enqueue reconciliation job
});
```

---

## 7. Extending the Engine

| Goal | Extension Point | Example |
|------|-----------------|---------|
| Add new vital-sign | Implement `transform::Strategy` | `BloodGasCalibrator` |
| Alternate storage   | Derive from `storage::Sink`    | `InfluxDbSink` |
| Custom telemetry    | Implement `observe::Exporter`  | `SplunkExporter` |
| New UI widget       | React component under `web/ui/`| `QTcHistogram.tsx` |

All extension points are compiled into the main binary to preserve the
single-artifact deployment model demanded by regulatory compliance.

---

## 8. Compliance & Security

* HIPAA-grade TLS 1.3 with FIPS-approved ciphers.
* AES-256-GCM encryption at rest (optional KMIP integration).
* Audit logs with WORM support (FINRA 4511 compatible).

See `docs/compliance/` for the full whitepaper.

---

## 9. Contributing

1. Fork → feature branch → PR.
2. `clang-format` and `clang-tidy` must pass (`make lint`).
3. Unit tests (`ctest`) and integration suite (`make itest`) must be green.
4. Sign the contributor license agreement (CLA) to be merged.

---

## 10. Support

Commercial SLAs, training, and consulting are available.  
Email `ci360-support@pulsedynamics.com` or join our **Slack** community:
`https://cardioinsight360.slack.com/`.

---

> **SHA-256** of this documentation at the time of release:  
> `b4b4e4fd7de34a6b0b3324c58c8fd8d62e84624cc0c3d6e70561b2c4862ef575`

Happy hacking, and may your QRS complexes be ever regular 🫀
```