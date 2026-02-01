```markdown
# CardioInsight360 – Unified Healthcare Analytics Engine
![CI360](docs/assets/ci360_banner.png)

> One binary. End-to-end insights. **HIPAA-grade**.

CardioInsight360 (CI-360) is a C++17 analytics platform purpose-built for cardiology networks that need to **ingest, validate, transform, store, and visualize** high-volume physiological and operational data coming from  
HL7/FHIR feeds, bedside monitors, wearable ECG devices, and imaging archives.

*Monolith on the outside—pluggable on the inside.*

---

## Table of Contents
1. [Quick Start](#quick-start)
2. [High-Level Architecture](#high-level-architecture)
3. [Build & Run](#build--run)
4. [Configuration](#configuration)
5. [Example – 20-Line ETL Pipeline](#example--20-line-etl-pipeline)
6. [Extending CI-360](#extending-ci-360)
7. [Compliance & Security](#compliance--security)
8. [Contributing](#contributing)
9. [License](#license)

---

## Quick Start
```bash
# Clone
git clone https://github.com/acme-hlth/cardio_insight_360.git
cd cardio_insight_360

# Configure & build (Release w/ native arch & OpenSSL, Protobuf, TBB, librdkafka)
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DENABLE_TESTS=ON
cmake --build build -j$(nproc)

# Run first-time setup (creates default config in ~/.ci360)
./build/ci360 --bootstrap

# Start all services (ingestion, ETL, dashboard; runs in-process)
./build/ci360 --start
```

---

## High-Level Architecture
```text
┌─────────────────────────────┐
│   Hospital & Device Feeds   │
└────────────┬────────────────┘
             │  HL7/FHIR, DICOM, CSV, REST, WebSocket
┌────────────▼──────────────┐
│   In-Process Ingestion     │  librdkafka (Kafka) + gRPC
└────────────┬──────────────┘
             │  Event Bus
┌────────────▼──────────────┐
│   Parallel ETL Pipelines   │  Intel TBB + Strategy Pattern
└────────────┬──────────────┘
             │  Curated Frames
┌────────────▼──────────────┐
│     Data-Lake Façade       │  Apache Parquet + Arrow
└────────────┬──────────────┘
             │  Observer Hooks
┌────────────▼──────────────┐
│   Real-Time Monitoring     │  Prometheus + Grafana
└────────────┬──────────────┘
             │
┌────────────▼──────────────┐
│    Visualization API       │  SPA (TypeScript) + gRPC Gateway
└────────────────────────────┘
```

---

## Build & Run

### Prerequisites
* GCC ≥ 11 / Clang ≥ 13 with C++17
* CMake ≥ 3.20
* OpenSSL ≥ 1.1
* Apache Arrow + Parquet
* Intel TBB
* librdkafka (v1.9+)
* Protocol Buffers ≥ 3.18
* Python 3.9 (for tooling scripts only)

> All third-party libraries can be pulled via `conan install . --output-folder=build`  
> (requires Conan ≥ 2.0).

### Build from Source
```bash
conan profile detect --force
conan install . --output-folder=build --build=missing
cmake -S . -B build -DCMAKE_TOOLCHAIN_FILE=build/conan_toolchain.cmake \
      -DCMAKE_BUILD_TYPE=Release -DENABLE_SANITIZERS=OFF
cmake --build build --target ci360_tests ci360 -j
```

### Running Unit & Integration Tests
```bash
ctest --test-dir build -j
```

---

## Configuration

After the first run (`--bootstrap`), CI-360 creates:

* `~/.ci360/ci360.yaml` – main runtime configuration  
* `~/.ci360/keystore/` – AES-256 encryption keys  
* `~/.ci360/log/` – rotating log files (spdlog)  
* `~/.ci360/data/` – hierarchical Parquet lake  

All options are self-documented in `ci360.yaml`; hot-reloading is supported (SIGHUP).

---

## Example – 20-Line ETL Pipeline

Below is a **single-file** example that shows how to register a custom transformation for real-time ECG quality scoring.  
Compile it as a plugin (`ci360_plugin_quality.so`) and drop it into `$CI360_HOME/plugins/`.

```cpp
// ecg_quality_plugin.cpp
#include <ci360/api.hpp>          // Public plugin interface
#include <numeric>

using namespace ci360;

// Custom Strategy: Compute basic signal-to-noise ratio (SNR)
class ECGQualityTransform final : public TransformStrategy
{
public:
    Frame on_execute(const Frame& in) override
    {
        if (!in.is_signal("ECG")) throw std::invalid_argument("Not an ECG frame");

        const auto& v = in.field_as<std::vector<float>>("waveform");
        if (v.empty()) throw std::runtime_error("Empty ECG waveform");

        const float mean = std::accumulate(v.begin(), v.end(), 0.0f) / v.size();
        float noise = 0.0f;
        for (auto s : v) noise += (s - mean) * (s - mean);
        noise = std::sqrt(noise / v.size());

        const float snr = mean / (noise + 1e-6f);

        Frame out = in;
        out.set("snr", snr);
        out.set("is_high_quality", snr > 6.0f);
        return out;
    }

    std::string name() const noexcept override { return "ECGQualityTransform"; }
};

// Plugin entry point
extern "C" CI360_PLUGIN_EXPORT void register_plugin(PluginRegistry& reg)
{
    reg.register_transform(std::make_shared<ECGQualityTransform>());
}
```

_20 lines of real code → instant domain functionality._

---

## Extending CI-360

| Extension Point  | Interface                        | Typical Use-Case                                   |
|------------------|----------------------------------|----------------------------------------------------|
| Ingestion Feed   | `Ingest::SourceStrategy`         | Add MQTT, OPC-UA, or proprietary serial feeds      |
| Transform        | `ETL::TransformStrategy`         | Custom denoising, feature extraction               |
| Validation       | `Quality::CheckStrategy`         | ISO-13485 compliance checks, signal entropy tests  |
| Export           | `Export::SinkStrategy`           | Send curated data to external Lakehouse            |
| Observer         | `Monitor::Observable`            | Push app-metrics to 3rd-party APM                  |

All interfaces are **header-only** and rely on modern C++ idioms (smart ptrs, `std::span`, concepts).

---

## Compliance & Security

* Full audit trail (WORM Parquet w/ SHA-256 checksums)
* Transport security: mTLS (OpenSSL) & HTTP/2
* Data security: AES-256-GCM at rest, row-level masking
* Role-based access control (RBAC) backed by LDAP or OAuth2
* Native support for ICD-10, SNOMED CT, LOINC ontologies

CI-360 is delivered with an FDA-510(k) friendly **Software Bill of Materials (SBOM)** in SPDX format.

---

## Contributing

1. Fork the repo & create a feature branch (`git checkout -b feat/add-awesome`).
2. Follow the [coding guidelines](docs/CONTRIBUTING.md) (clang-format, clang-tidy).
3. Write unit tests (`ci360_tests`) & ensure Green build (`ctest -j`).
4. Open a PR, sign the CLA, and wait for CI approval.

We value inclusive and respectful collaboration. :heart:

---

## License
```
CardioInsight360 – Unified Healthcare Analytics Engine  
Copyright (c) 2024 Acme Healthcare

Distributed under the **Apache License 2.0**.  
See [LICENSE](LICENSE) for full text.
```
```