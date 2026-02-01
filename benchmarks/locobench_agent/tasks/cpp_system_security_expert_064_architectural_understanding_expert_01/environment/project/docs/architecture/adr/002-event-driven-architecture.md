```markdown
# Architecture Decision Record: 002 — Event-Driven Architecture

* **Status** : Accepted  
* **Date**   : 2024-06-08  
* **Stakeholders** :  
  * Product: VP Product, Lead Product Manager  
  * Engineering: Chief Architect, Platform Tech-Lead, Backend Guild  
  * Operations: SRE Lead, DevOps Lead  
  * Compliance & Security: CISO, Risk Officer  

---

## 1. Context  

FortiLedger360 is expected to ingest and react to a high volume of fine-grained security events (e.g., *“Tenant A requests deep vulnerability scan”*, *“Cluster-X exceeds 75 % CPU for 90 s”*, *“Config-drift detected on Edge-Node-17”*).  
Traditional synchronous request/response workflows (REST or RPC) impose tight coupling, limited extensibility, and waterfall-style failure domains.  

Key platform requirements:  

* **Scalability** – Burst to > 250 K events/s while maintaining < 200 ms P95 processing latency.  
* **Extensibility** – Add a new service (e.g., `ComplianceAuditor`) with zero downtime.  
* **Fault Isolation** – Failure in `BackupNode` must **not** block `AlertBroker`.  
* **Observability** – Every state transition must emit traceable, structured audit logs.  
* **Multi-tenant Guardrails** – Tenants demand isolated QoS & configurable SLAs.  

These constraints steer us toward **Event-Driven Architecture (EDA)** built around an **asynchronous, durable, high-throughput event bus**.

---

## 2. Decision  

We will implement an Event-Driven Architecture in which:  

1. **Domain events** are first-class citizens.  
2. **Producers** (e.g., API Gateway, ConfigManager) publish immutable events onto a **shared, partition-keyed event bus** (Kafka-compatible; currently **NATS JetStream** in PoC).  
3. **Consumers** (e.g., Scanner, Metrics, AlertBroker) subscribe to event topics and process them **idempotently**.  
4. **Commands** and **Queries** are explicitly separated (CQRS).  
5. **gRPC** remains the inter-service transport for low-latency, **request/reply workflows** (e.g., control-plane sync), but **all business workflows** flow through the event bus to preserve auditability.  
6. **Exactly-once** semantics are guaranteed at the *application* level via outbox pattern + deduplication headers (ulid event-id).  
7. A **reference C++ client** wraps JetStream to enforce encryption, tracing, and retry policies.

---

## 3. Consequences  

### Positive  
* Loose coupling → Horizontal service agility.  
* Native scalability via topic sharding & consumer groups.  
* Natural audit log & replay capability → compliance win.  
* Enables decoupled failure handling and resiliency patterns (DLQ, back-pressure).  

### Negative / Trade-offs  
* Added operational complexity: JetStream clusters, topic ACLs, and schema evolution.  
* Higher learning curve for developers unfamiliar with EDA patterns.  
* Latency overhead vs. sync RPC (≈ 5–15 ms per hop).  

### Follow-ups  
* Implement **Schema Registry** (Apache Avro) + compatibility gates in CI.  
* Define **tenant partition-key strategy** for QoS isolation.  
* Provide **SDKs** (Go, Rust, C++) with consistent observability hooks.  

---

## 4. Reference Implementation (C++)

Below is an excerpt from `messaging/EventBus.hpp` showcasing the thin, opinionated wrapper around NATS JetStream.  
It demonstrates publishing a `SecurityScanInitiated` event and consuming with **exactly-once** semantics.

```cpp
#pragma once
#include <nats/nats.h>
#include <chrono>
#include <future>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>

/**
 * @brief FortiLedger360 :: EventBus
 *
 * Opinionated, thread-safe JetStream wrapper providing:
 *   • Schema-validated payloads (JSON/Avro)
 *   • mTLS enforcement
 *   • Automatic ULID-based idempotency keys
 *   • Structured tracing (OpenTelemetry)
 */
class EventBus {
public:
    explicit EventBus(std::string_view natsUrl,
                      std::chrono::milliseconds timeout = std::chrono::seconds(5))
        : url_{natsUrl}, reqTimeout_{timeout}
    {
        natsOptions_Create(&opts_);
        natsOptions_SetURL(opts_, url_.c_str());
        // TODO: configure mTLS: natsOptions_SetSecureContext(...)
        auto s = natsConnection_ConnectTo(&conn_, opts_);
        if (s != NATS_OK) {
            throw std::runtime_error(
                "EventBus: unable to connect to NATS: " + std::string(natsStatus_GetText(s)));
        }
        // JetStream context
        s = natsConnection_JetStream(&js_, conn_, nullptr);
        if (s != NATS_OK) {
            throw std::runtime_error(
                "EventBus: unable to create JetStream context: " + std::string(natsStatus_GetText(s)));
        }
    }

    ~EventBus()
    {
        if (js_)  natsJetStream_Destroy(js_);
        if (conn_) natsConnection_Destroy(conn_);
        if (opts_) natsOptions_Destroy(opts_);
    }

    struct PublishAck {
        std::string stream;
        std::string domain;
        uint64_t    sequence{};
    };

    // Publish JSONArray/Avro serialised bytes; async by default
    auto publish(std::string_view subject,
                 std::string_view payload,
                 std::string_view msgId /* ULID */,
                 bool synchronousAck = false) -> std::future<PublishAck>
    {
        // Headers: idempotency + trace
        natsMsg* msg{};
        natsMsg_Create(&msg, subject.data(), nullptr, payload.data(), payload.size());
        natsMsgHeader_Set(msg, "Nats-Msg-Id", msgId.data());
        // TODO: inject OpenTelemetry trace headers

        return std::async(std::launch::async, [=] {
            jsPubAck* ack{};
            auto s =
                natsJetStream_PublishMsg(js_, &ack, msg,
                                         synchronousAck ? NATS_JETSTREAM_PUB_SYNCAWAIT : 0);
            natsMsg_Destroy(msg);

            if (s != NATS_OK) {
                throw std::runtime_error("publish failed: " + std::string(natsStatus_GetText(s)));
            }

            PublishAck r{ack->Stream, ack->Domain, ack->Seq};
            jsPubAck_Destroy(ack);
            return r;
        });
    }

    /**
     * Subscribe with at-least-once semantics.  
     * Application layer is responsible for idempotency using the message ULID.
     */
    void subscribe(std::string_view subject,
                   const std::function<void(const natsMsg*)>& handler,
                   std::string durableName = "")
    {
        natsSubscription* sub{};
        jsSubOpts opts{};
        jsSubOpts_Init(&opts);
        opts.Durable = durableName.empty() ? nullptr : durableName.c_str();
        opts.AckPolicy           = js_AckExplicit;
        opts.MaxDeliver          = 5; // retry/poison message threshold
        opts.IdleHeartbeat       = 30 * 1'000'000'000ULL; // 30s

        auto s = natsJetStream_Subscribe(&sub, js_, subject.data(), nullptr,
                                         internalMsgCb, const_cast<void*>(static_cast<const void*>(&handler)), &opts);
        if (s != NATS_OK) {
            throw std::runtime_error("subscribe failed: " + std::string(natsStatus_GetText(s)));
        }
        activeSubs_.emplace(sub);
    }

private:
    static void internalMsgCb(natsConnection*, natsSubscription*, natsMsg* msg, void* closure)
    {
        auto* userCb = reinterpret_cast<std::function<void(const natsMsg*)>*>(closure);
        try {
            (*userCb)(msg); // userland processing
            natsMsg_Ack(msg); // explicit ack
        } catch (const std::exception& ex) {
            std::cerr << "[EventBus] handler exception: " << ex.what() << '\n';
            natsMsg_Nak(msg, nullptr, 0); // negative ack → redelivery
        }
        natsMsg_Destroy(msg);
    }

    std::string                     url_;
    std::chrono::milliseconds       reqTimeout_{};
    natsOptions*                    opts_{};
    natsConnection*                 conn_{};
    natsJetStreamContext*           js_{};
    std::unordered_set<natsSubscription*> activeSubs_;
};
```

Usage sample for the `Scanner` service:

```cpp
#include "messaging/EventBus.hpp"
#include <ulid/ulid.hpp> // hypothetical ULID lib

int main() {
    EventBus bus{"tls://nats.internal.fortiledger360.io:4222"};

    // Producer side: announce that a scan has started.
    auto ulid = ulid::generate();
    bus.publish(
        "security.scan.initiated",
        R"({"tenant":"acme","cluster":"edge-a1","depth":"deep"})",
        ulid)
        .get(); // wait for ack

    // Consumer side: listen for completion
    bus.subscribe("security.scan.completed", [](const natsMsg* msg) {
        std::string payload{natsMsg_GetData(msg), natsMsg_GetDataLength(msg)};
        // TODO: parse JSON & persist results
        std::cout << "[Scanner] Received scan.completed: " << payload << '\n';
    }, "scanner-completed-durable");

    // Block main thread (demo purposes)
    std::this_thread::sleep_for(std::chrono::hours(24));
}
```

---

## 5. References  

* NATS JetStream – https://docs.nats.io/nats-concepts/jetstream  
* “Building Event-Driven Microservices” – Adam Bellemare  
* CNCF CloudEvents Specification – https://github.com/cloudevents/spec  
* OpenTelemetry for C++ – https://opentelemetry.io/docs/instrumentation/cpp/  

```