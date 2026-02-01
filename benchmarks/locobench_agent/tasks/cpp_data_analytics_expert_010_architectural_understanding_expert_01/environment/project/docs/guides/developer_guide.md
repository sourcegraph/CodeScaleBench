```markdown
<!--
 CardioInsight360 – Unified Healthcare Analytics Engine
 Developer Guide
 Copyright (c) 2024 MedTech
 SPDX-License-Identifier: Apache-2.0
-->

# CardioInsight360 • Developer Guide

Welcome to **CardioInsight360**—a single-binary, C++17 analytics engine that ingests, validates, transforms, stores, and visualizes high-volume cardiology data.  
This document targets developers who need to **extend, debug, or embed** the platform.  
If you are looking for operator instructions, consult the *Operations Guide* instead.

---

## 1. Quick Start (10 min)

```bash
# 1️⃣  Clone
git clone https://github.com/medtech/cardio_insight_360.git
cd cardio_insight_360

# 2️⃣  Configure out-of-source build
cmake -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo \
      -DCMAKE_CXX_STANDARD=17 \
      -DENABLE_TESTS=ON \
      -DENABLE_GPU=OFF        # Optional CUDA acceleration

# 3️⃣  Build & test
cmake --build build --parallel
cmake --build build --target test       # Unit + integration

# 4️⃣  Run the engine
./build/bin/cardio_insight_360 --config etc/default.toml
```

---

## 2. Repository Layout

| Path                          | Description                                                             |
| ----------------------------- | ----------------------------------------------------------------------- |
| `apps/`                       | Entry-point executables (CLI, REST façade, diagnostics).               |
| `core/`                       | Domain primitives: ECG lead, ICD-10, HL7, timestamps.                 |
| `modules/`                    | Pluggable engine components (see §4).                                  |
| `modules/strategy/`           | Signal-type specific validation & transformation strategies.           |
| `modules/etl/`                | Scalable ETL pipelines built on Intel TBB.                             |
| `modules/event_bus/`          | In-process Kafka wrapper powered by *librdkafka*.                      |
| `modules/monitoring/`         | Observer hooks (Prometheus, gRPC health checks).                       |
| `third_party/`                | Vendored libraries (minimal forks for reproducible builds).            |
| `tests/`                      | GoogleTest + Catch2 suites.                                            |
| `docs/`                       | All documentation, diagrams, ADRs, and compliance material.           |

---

## 3. Building From Source

### 3.1 Mandatory Dependencies

| Library        | Version | Purpose                          |
| -------------- | ------- | -------------------------------- |
| CMake          | ≥3.22   | Build system                     |
| GCC / Clang    | C++17   | Compiler                         |
| Intel TBB      | ≥2020   | Parallel runtime                 |
| Apache Arrow   | ≥11     | Parquet serialization            |
| librdkafka     | ≥2.0    | Event streaming                  |
| OpenSSL        | 1.1/3   | HIPAA-grade TLS & AES            |
| GoogleTest     | ≥1.12   | Unit testing (downloaded via CPM)|

```bash
# Ubuntu/Debian example
sudo apt install build-essential cmake libtbb-dev \
                 libssl-dev librdkafka-dev libarrow-dev
```

### 3.2 Optional Accelerators

* **CUDA ≥12** – GPU-accelerated arrhythmia detection  
* **Intel® VTune™** – Hot-path profiling  
* **Clang Sanitizers** – `-DENABLE_ASAN=ON`

---

## 4. Module Architecture

Below is the high-level call graph of the default execution path.

```
┌────────────────────┐    HL7/FHIR             ┌─────────────────────┐
│ Ingestion Engine   │ ─────────────┐          │  Event Bus (Kafka)  │
└────────────────────┘             │          └─────────────────────┘
        │                          ▼
        │                ┌─────────────────────┐
        │                │   ETL Pipeline      │  (TBB flow graph)
        │                │  ────────────────   │
        │                │  • Validation       │
        │                │  • Transformation   │
        │                │  • Aggregation      │
        ▼                └─────────────────────┘
┌────────────────────┐            │
│ Data-Lake Facade   │◀───────────┘      (Parquet + Arrow)
└────────────────────┘
        │
        ▼
┌────────────────────┐
│ Visualization      │ (built-in REST/WS)
└────────────────────┘
```

Each gray box corresponds to a C++ namespace under `modules/`.  
They communicate in-process using *Observer Pattern* signals and *Kafka* for
decoupled stream semantics.

---

## 5. Coding Standards

1. **C++17** (`std::optional`, `std::filesystem`, `std::variant` preferred).  
2. **ClangFormat** – Style file at repo root (`.clang-format`).  
3. **Strong Typedefs** – Use `named_type` wrapper (`core/strong_type.hpp`) to
   avoid primitive obsession.  
4. **RAII-Only Resources** – No naked `new`/`delete`; use `std::unique_ptr`,
   `absl::StatusOr`, or ` gsl::owner<>`.  
5. **Error Handling** – Return `tl::expected` or `absl::Status` for recoverable
   errors; throw only for truly exceptional states (e.g., programming errors).  

---

## 6. Implementing a New Transformation Strategy

The engine relies on the **Strategy Pattern** to apply domain-specific
operations. Follow the steps below to add a new `QTIntervalCorrection`
strategy.

### 6.1 Header Declaration

```cpp
// file: modules/strategy/include/qt_interval_correction.hpp
#pragma once
#include "strategy/strategy_interface.hpp"
#include <chrono>

namespace ci360::strategy {

class QTIntervalCorrection final : public StrategyInterface
{
public:
    explicit QTIntervalCorrection(double heartRateBpm);
    std::string name() const noexcept override { return "QTIntervalCorrection"; }
    Result apply(const SignalBatch& input,
                 PipelineContext&      ctx) const override;

private:
    double m_heartRate;
};

}  // namespace ci360::strategy
```

### 6.2 Implementation

```cpp
// file: modules/strategy/src/qt_interval_correction.cpp
#include "qt_interval_correction.hpp"
#include "core/math/linear_regression.hpp"
#include "core/units/physiology.hpp"
#include <fmt/format.h>

namespace ci360::strategy {

QTIntervalCorrection::QTIntervalCorrection(double heartRateBpm)
    : m_heartRate(heartRateBpm)
{
    if (m_heartRate <= 0.0) {
        throw std::invalid_argument("Heart rate must be positive");
    }
}

StrategyInterface::Result
QTIntervalCorrection::apply(const SignalBatch& batch,
                            PipelineContext&   ctx) const
{
    using namespace ci360::units;
    Result out;
    out.metadata = batch.metadata;

    // Bazett correction: QTc = QT / sqrt(RR)
    for (const ECGLead& lead : batch.ecgLeads) {
        const double rrSec = 60.0 / m_heartRate;  // RR interval
        const double qtc   = lead.qtInterval / std::sqrt(rrSec);
        out.correctedLeads.emplace_back(
            lead.id, static_cast<Milliseconds>(qtc));
    }

    ctx.metrics().increment("qt_interval_corrected");
    return out;
}

} // namespace ci360::strategy
```

### 6.3 Registration

```cpp
// file: modules/strategy/registry.cpp
#include "qt_interval_correction.hpp"
#include "strategy_registry.hpp"

namespace {
bool _registered = [] {
    ci360::strategy::Factory::instance().registerStrategy(
        "QTIntervalCorrection",
        [](const nlohmann::json& cfg) -> std::unique_ptr<StrategyInterface> {
            return std::make_unique<QTIntervalCorrection>(
                cfg.at("heart_rate_bpm").get<double>());
        });
    return true;
}();
} // anonymous namespace
```

The lambda is executed at static initialization, making the
strategy auto-discoverable.

---

## 7. Running the Test Suite

Unit, integration, and compliance tests live under `tests/`.

```bash
cmake --build build --target test
```

CI pipelines (GitHub Actions + self-hosted GitLab) run the same command in
`Debug`, `RelWithDebInfo`, and `AddressSanitizer` configurations.

### 7.1 Focused Run

```bash
# Only run Strategy tests, filter by regex
ctest --output-on-failure -R Strategy
```

### 7.2 Profiling

```bash
# Generate perf data for ingestion path
perf record --call-graph dwarf -- \
    ./build/bin/cardio_insight_360 --profile ingestion
perf report
```

---

## 8. Troubleshooting & Debugging

| Symptom                              | Likely Cause / Fix                                          |
| ------------------------------------ | ----------------------------------------------------------- |
| `KafkaException: Broker transport`   | Mis-configured `bootstrap.servers`; verify DNS & firewall.  |
| `SSL routines:bad_certificate`       | Certificate expired; renew via internal PKI.                |
| High CPU during batch ETL            | Check TBB `max_concurrency`; tune via `etc/perf.toml`.      |
| Engine hangs on shutdown             | A long-running observer; enable `--diagnose lifecycle`.     |

Use `--log-level=trace` for verbose output. Logs are structured JSON and
compatible with Datadog, Splunk, and Elastic.

---

## 9. Secure Coding & Compliance

CardioInsight360 is FDA-class III software and **HIPAA** compliant.

1. All PHI fields are AES-256 encrypted at rest (`DataLake::encryptBlock`).  
2. TLS 1.3 with mutual authentication is mandatory.  
3. Static analysis via *clang-tidy* and *CodeQL* is enforced in CI.  
4. Dependencies are scanned using *Trivy* before each release.  
5. Refer to `docs/compliance/` for SOC 2 and ISO 13485 artifacts.

---

## 10. Release Process

1. Create a release branch: `release/vX.Y.Z`.  
2. Bump version in `core/version.hpp`.  
3. Run `./scripts/regression_suite.sh` (≈ 3 h).  
4. Tag & sign: `git tag -s vX.Y.Z -m "Release vX.Y.Z"`.  
5. CI auto-publishes artifacts to the internal Helm repo and the
   **DoD Iron Bank** container registry.

---

## 11. Additional Resources

* ADRs – `docs/adr/`  
* Doxygen – `build/docs/html/index.html`  
* Slack – `#ci360-dev`  
* On-Call Rotation – `docs/SRE/oncall.md`  

---

## Appendix A • Example HL7 ORU ^R01 Parse

```cpp
using ci360::hl7::ORU_R01;

void handle_message(const std::string& raw)
{
    auto parsed = ORU_R01::parse(raw)
                    .or_else([](auto&& err) {
                        spdlog::error("HL7 parse failed: {}", err.what());
                        return expected<ORU_R01>{tl::unexpected(err)};
                    });
    if (!parsed) return;

    ingest_engine.enqueue(*parsed);
}
```

---

## Appendix B • How to Generate Parquet Schemas

```bash
./build/bin/cardio_insight_360 --schema --format=parquet \
    --signal=ECG --out schemas/ecg.parquet.schema.json
```

---

Happy coding!  
— *CardioInsight360 Core Team*
```