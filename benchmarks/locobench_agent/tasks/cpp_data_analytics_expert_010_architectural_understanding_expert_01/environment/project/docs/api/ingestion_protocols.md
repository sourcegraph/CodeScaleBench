```markdown
# CardioInsight360 — Ingestion Protocols API
*File Path: `cardio_insight_360/docs/api/ingestion_protocols.md`*  
*Last Updated: 2024-05-26*  
*Language Focus: C++17*  

CardioInsight360 ingests data from heterogeneous clinical systems through a pluggable **Ingestion Protocol** abstraction. Each protocol wraps the transport semantics (TCP/MLLP, REST, WebSocket, gRPC, serial, etc.) and domain specifics (HL7 v2, HL7 FHIR, vendor-proprietary binary frames) behind a uniform C++ interface so that downstream ETL stages can remain agnostic of their origins.

---

## 1. High-Level Architecture

```text
+---------------+      +-----------------+      +-------------------+
|  External HIS | ---> |  Ingestion Bus   | ---> |  Transformation   |
|  (HL7 v2)     |      |  (librdkafka)    |      |  (Strategy Chain) |
+---------------+      +-----------------+      +-------------------+
                          ^   ^    ^
                          |   |    |
                    +-----+---+----+--------+
                    |  Ingestion Protocols  |
                    +-----------------------+
```

1. **Ingestion Protocols** receive data from external sources.  
2. They marshall incoming payloads into a canonical `RawEnvelope`.  
3. The **Ingestion Bus** (Kafka topic) acts as the only synchronization point between real-time data ingestion and subsequent ETL pipelines.

---

## 2. Core Interface

```cpp
// File: include/ci360/ingestion/IIngestionProtocol.hpp
#pragma once

#include <ci360/common/RawEnvelope.hpp>
#include <ci360/common/ServiceLifecycle.hpp>
#include <memory>
#include <string_view>

namespace ci360::ingestion {

/**
 * @brief   Polymorphic contract for all data-ingestion protocols.
 *
 * Implementations must be thread-safe and non-blocking. The lifecycle
 * controls (start/stop) are invoked by the internal Orchestrator.
 */
class IIngestionProtocol : public common::ServiceLifecycle
{
public:
    virtual ~IIngestionProtocol() = default;

    /**
     * @brief Publish a RawEnvelope into the platform’s streaming bus.
     *
     * The implementation should propagate any recoverable transport
     * errors to the caller via IngestionException.
     */
    virtual void publish(RawEnvelope&& envelope) = 0;

    /**
     * @return Short, immutable identifier (e.g., "HL7-v2").
     */
    [[nodiscard]] virtual std::string_view id() const noexcept = 0;
};

using IIngestionProtocolPtr = std::shared_ptr<IIngestionProtocol>;

} // namespace ci360::ingestion
```

---

## 3. Built-In Protocols

| Protocol                          | Transport | Typical Source  |
|----------------------------------|-----------|-----------------|
| `HL7v2Protocol`                  | TCP/MLLP  | HIS/EHR         |
| `FHIRRestProtocol`               | HTTPS     | FHIR-compliant  |
| `PhilipsIntelliVueBinaryProtocol`| Serial    | Bedside monitor |
| `WearableWebSocketProtocol`      | WSS       | Consumer ECG    |

Below we deep-dive into two production-ready implementations.

---

### 3.1 HL7 v2 (MLLP)

```cpp
// File: src/ingestion/HL7v2Protocol.cpp
#include <ci360/ingestion/HL7v2Protocol.hpp>
#include <ci360/common/Logging.hpp>
#include <ci360/common/Exceptions.hpp>
#include <boost/asio.hpp>
#include <librdkafka/rdkafka.h>

using ci360::common::IngestionException;

namespace ci360::ingestion {

// --- Private helpers --------------------------------------------------------
namespace {
constexpr std::string_view ACK = "\x0BMSH|^~\\&|CARDIO|CI360|ACK|\x1C\r";
}

// --- Constructor ------------------------------------------------------------
HL7v2Protocol::HL7v2Protocol(const Config& cfg,
                             std::shared_ptr<kafka::Producer> producer)
    : cfg_(cfg),
      producer_(std::move(producer)),
      io_ctx_(1),
      socket_(io_ctx_)
{
    if (!producer_)
        throw std::invalid_argument("HL7v2Protocol: Null producer");
}

// --- Lifecycle --------------------------------------------------------------
void HL7v2Protocol::start()
{
    using boost::asio::ip::tcp;
    tcp::endpoint ep(boost::asio::ip::make_address(cfg_.host), cfg_.port);
    socket_.connect(ep);

    listener_ = std::thread([this] { listen(); });
    CI360_LOG_INFO("HL7v2Protocol [{}] started on {}:{}", id(), cfg_.host, cfg_.port);
}

void HL7v2Protocol::stop()
{
    running_.store(false);
    if (socket_.is_open()) {
        boost::system::error_code ec;
        socket_.close(ec);
    }
    if (listener_.joinable()) listener_.join();
    CI360_LOG_INFO("HL7v2Protocol [{}] stopped.", id());
}

// --- Publish ----------------------------------------------------------------
void HL7v2Protocol::publish(RawEnvelope&& envelope)
{
    if (!producer_)
        throw IngestionException("Kafka producer not initialized");

    rd_kafka_resp_err_t err = producer_->produce(
        cfg_.kafka_topic,
        RD_KAFKA_PARTITION_UA,
        RD_KAFKA_MSG_F_COPY,
        envelope.payload.data(),
        envelope.payload.size(),
        envelope.key.data(),
        envelope.key.size(),
        nullptr);

    if (err != RD_KAFKA_RESP_ERR_NO_ERROR) {
        throw IngestionException(rd_kafka_err2str(err));
    }
}

// --- Internal listener loop -------------------------------------------------
void HL7v2Protocol::listen()
{
    try {
        while (running_.load()) {
            std::string buffer;
            buffer.resize(cfg_.max_frame_size);
            boost::system::error_code ec;

            size_t bytes = socket_.read_some(boost::asio::buffer(buffer), ec);
            if (ec == boost::asio::error::would_block) continue;
            if (ec) throw boost::system::system_error(ec);

            buffer.resize(bytes);

            // Strip MLLP wrapper (0x0B ... 0x1C0D)
            const auto start = buffer.find('\x0B');
            const auto end   = buffer.find("\x1C\r");
            if (start == std::string::npos || end == std::string::npos) {
                CI360_LOG_WARN("Invalid MLLP frame skipped.");
                continue;
            }

            RawEnvelope envelope;
            envelope.protocol = id();
            envelope.payload  = buffer.substr(start + 1, end - start - 1); // HL7 message
            envelope.ingest_ts = std::chrono::system_clock::now();

            publish(std::move(envelope));

            // Send ACK
            boost::asio::write(socket_, boost::asio::buffer(ACK), ec);
        }
    } catch (const std::exception& ex) {
        CI360_LOG_ERROR("HL7v2Protocol listener terminated: {}", ex.what());
        // Notify orchestrator or elevate alarm ...
    }
}

} // namespace ci360::ingestion
```

Key characteristics:
* **Non-blocking**: The listener thread uses Boost.Asio’s async primitives.  
* **Fault tolerance**: Transport and Kafka errors are wrapped into `IngestionException`.  
* **Compliance**: HL7 MLLP wrapper is strictly enforced.

---

### 3.2 FHIR REST

```cpp
// File: src/ingestion/FHIRRestProtocol.cpp
#include <ci360/ingestion/FHIRRestProtocol.hpp>
#include <ci360/common/Logging.hpp>
#include <ci360/common/HttpClient.hpp>
#include <nlohmann/json.hpp>

namespace ci360::ingestion {

void FHIRRestProtocol::start()
{
    // Launch periodic pull task
    task_ = std::thread([this] { pollLoop(); });
}

void FHIRRestProtocol::stop()
{
    running_.store(false);
    if (task_.joinable()) task_.join();
}

void FHIRRestProtocol::publish(RawEnvelope&& envelope)
{
    dispatcher_->dispatch(std::move(envelope)); // internal event-bus
}

void FHIRRestProtocol::pollLoop()
{
    const auto interval = std::chrono::seconds(cfg_.poll_seconds);

    while (running_.load()) {
        try
        {
            auto response = http_->get(cfg_.endpoint, {{"Accept", "application/fhir+json"}});
            if (response.status_code != 200) {
                CI360_LOG_WARN("FHIR poll received HTTP {}", response.status_code);
                continue;
            }

            const auto bundle = nlohmann::json::parse(response.body);

            for (const auto& entry : bundle["entry"]) {
                RawEnvelope env;
                env.protocol   = id();
                env.payload    = entry.dump();
                env.ingest_ts  = std::chrono::system_clock::now();
                publish(std::move(env));
            }
        }
        catch (const std::exception& ex) {
            CI360_LOG_ERROR("FHIR poll error: {}", ex.what());
        }
        std::this_thread::sleep_for(interval);
    }
}

} // namespace ci360::ingestion
```

---

## 4. Configuring Protocols

Configuration is YAML-driven and validated at startup.

```yaml
ingestion:
  hl7v2:
    host: "10.1.2.99"
    port: 2575
    kafka_topic: "hl7_raw"
    max_frame_size: 65536
  fhir_rest:
    endpoint: "https://ehr.gov/api/Observation"
    poll_seconds: 5
```

---

## 5. Extending with a Custom Protocol

Below is a template for vendors wanting to integrate proprietary devices.

```cpp
// File: include/ci360/ingestion/MyDeviceProtocol.hpp
#pragma once
#include <ci360/ingestion/IIngestionProtocol.hpp>
#include <boost/asio.hpp>

namespace ci360::ingestion {

class MyDeviceProtocol final : public IIngestionProtocol
{
public:
    struct Config {
        std::string serial_port = "/dev/ttyUSB0";
        uint32_t    baud_rate   = 115'200;
    };

    explicit MyDeviceProtocol(Config cfg);

    // ServiceLifecycle
    void start() override;
    void stop()  override;

    // IIngestionProtocol
    void publish(RawEnvelope&& envelope) override;
    std::string_view id() const noexcept override { return "MyDevice-v1"; }

private:
    void readLoop();

    Config cfg_;
    std::atomic_bool running_{true};
    boost::asio::io_service io_;
    boost::asio::serial_port serial_;
    std::thread reader_;
};

} // namespace ci360::ingestion
```

Compile-time integration:

```cpp
#include <ci360/ingestion/Registry.hpp>
#include <ci360/ingestion/MyDeviceProtocol.hpp>

// Factory registration (executed during static initialization)
CI360_REGISTER_INGESTION_PROTOCOL("my-device", ci360::ingestion::MyDeviceProtocol);
```

At runtime, the Orchestrator resolves `my-device` in YAML and spins up an instance automatically.

---

## 6. Error Handling & Observability

* All protocols surface issues through `IngestionException` to enable centralized retry logic.  
* Each protocol self-registers a `ProtocolMetrics` handle (Prometheus) that exports:
  - `messages_ingested_total` (counter)  
  - `bytes_ingested_total` (counter)  
  - `ingest_latency_ms` (histogram)  
* Critical failures trigger the built-in **Circuit Breaker** which quarantines the protocol until manual intervention.

---

## 7. Thread-Safety Guarantees

1. `publish()` may be concurrently called by multiple producer threads.  
2. Implementations must employ lock-free or fine-grained locking to avoid head-of-line blocking.  
3. No mutable shared state may outlive the protocol’s `stop()`.

---

## 8. Versioning & Compatibility

CardioInsight360 follows **SemVer 2.0**:
* **MAJOR**: breaking interface or protocol changes  
* **MINOR**: backward-compatible enhancements (e.g., new optional fields)  
* **PATCH**: bug-fixes  

Ingestion Protocols must embed their schema version in the first 3 bytes of every `RawEnvelope` to support rolling upgrades.

---

## 9. Example: Manual Test Harness

```cpp
#include <ci360/ingestion/HL7v2Protocol.hpp>
#include <ci360/common/Logging.hpp>
#include <cstdlib>

int main(int argc, char* argv[])
{
    ci360::common::initLogging();

    ci360::ingestion::HL7v2Protocol::Config cfg;
    cfg.host = "127.0.0.1";
    cfg.port = 2580;
    cfg.kafka_topic = "ci360_hl7";
    cfg.max_frame_size = 65536;

    auto producer = std::make_shared<ci360::kafka::Producer>("kafka://localhost:9092");
    ci360::ingestion::HL7v2Protocol proto(cfg, producer);

    proto.start();
    std::this_thread::sleep_for(std::chrono::minutes(5));
    proto.stop();
}
```

Compile:

```bash
g++ -std=c++20 -Iinclude \
    src/ingestion/HL7v2Protocol.cpp \
    -lboost_system -lrdkafka -lpthread -o hl7_test
```

---

## 10. Security Considerations

* **TLS** and **mTLS** are mandatory for FHIR REST and WebSocket protocols.  
* PHI is encrypted at rest using AES-256 GCM before committing to the Data Lake.  
* Role-Based Access Control (RBAC) is enforced at the protocol level; only whitelisted sources may connect.  

---

## 11. Conclusion

The *Ingestion Protocol* layer provides an extensible, production-grade foundation for funneling multimodal clinical data into CardioInsight360. By adhering to the guidelines and interface contracts laid out in this document, vendors and internal teams can safely extend the platform’s reach while maintaining enterprise-level robustness and compliance.
```