# ADR 002: gRPC for Service-to-Service RPC and NATS Event Bus for Asynchronous Messaging

Date: 2023-11-12  
Status: Accepted  
Supersedes: —  
Superseded by: —  
Authors: Core Architecture Team (CanvasChain Symphony)

---

## 1. Context

CanvasChain Symphony is composed of ten autonomous Rust micro-services—`composer`, `minter`, `remixer`, `market-maker`, `royalty-streamer`, etc. Each service is owned and deployed independently yet must inter-operate to deliver end-to-end user flows. Two communication patterns are required:

1. **Request / Response (RPC)**  
   Example: the `market-maker` service must synchronously query `token-registry` for the current royalty split before quoting a swap.

2. **Publish / Subscribe (Eventing)**  
   Example: the `governance` service votes on a “movement” that triggers the `composer` to mint the next artwork. Every interested service (`gallery-renderer`, `royalty-streamer`, `analytics`) must react to the same chain event without tight coupling.

Key non-functional drivers:

* **Performance:** high throughput, low latency, binary payloads (art layers can be large).
* **Language Inter-op:** we anticipate plug-ins in Python (ML models), WASM (browser previews), and potentially Solidity-compiled bindings.
* **Back-Pressure & Delivery Guarantees:** at-least-once delivery for critical NFT state transitions, but fire-and-forget for analytics streams.
* **Security:** end-to-end encryption (mTLS), pluggable authN/authZ compatible with our wallet integration.

---

## 2. Decision

1. **gRPC** will be adopted for all synchronous, intra-cluster RPC calls.  
2. **NATS JetStream** will be adopted as the event bus for asynchronous, pub/sub communication.

---

## 3. Rationale

### Why gRPC?

* **IDL-First Development.** Protocol Buffers give us a single source of truth for message schemas in Rust, Python, TypeScript, etc.  
* **Streaming Support.** Bidirectional streams map naturally to live trait evolution and real-time auction bidding.  
* **Excellent Rust Ecosystem.** `tonic` provides async/await support, tower middlewares, and first-class mTLS.  
* **Efficient Binary Encoding.** Artwork layers are sent as deltas or binary blobs; Protobuf minimizes overhead compared to JSON.  

### Why NATS JetStream?

* **Lightweight & Cloud-Native.** Simple single-binary, horizontal-scaling suitability for micro-k8s clusters.  
* **Exactly-Once Semantics (Opt-In).** JetStream can persist critical events (e.g., ownership transfers) while still allowing fire-and-forget subjects for telemetry.  
* **Observable.** Built-in tracing, ad-hocs, and integration with Grafana Promtail for distributed tracing.  
* **Secure Subjects.** Supports leaf-nodes and account isolation, enabling multi-tenant “artist pools.”  
* **Rust Client Quality.** `nats.rs` offers async, typed-structured messages and JetStream KV for on-chain state mirroring.

### Alternatives Considered

| Option                    | Pros                                              | Cons                                                      |
|---------------------------|---------------------------------------------------|-----------------------------------------------------------|
| REST/JSON over HTTP/2     | Ubiquitous, easy to debug                         | Verbose payloads, no streaming, manual schema evolution   |
| GraphQL Federation        | Flexible querying                                 | Overkill for service-to-service calls, N + 1 traps        |
| Apache Kafka              | Durable, massive throughput                       | Operationally heavy, zookeeper (or KRaft) complexity      |
| RabbitMQ                  | Mature, routing patterns                          | Lower raw throughput, heavier client libs for WASM        |
| ZeroMQ                    | Embedded-style speed                              | No central broker, discovery challenges                   |

gRPC + NATS best satisfied the combined performance, ergonomics, and operational simplicity we need.

---

## 4. Detailed Design

### 4.1 gRPC Service Definitions

Service contracts live in `proto/` and are versioned via Git tags. An excerpt:

```protobuf
syntax = "proto3";

package canvaschain.market.v1;

service RoyaltyService {
  // Returns the royalty split for a given NFT
  rpc GetRoyaltyInfo(GetRoyaltyInfoRequest) returns (GetRoyaltyInfoResponse) {
    option (google.api.http) = {
      get: "/v1/royalty/{token_id}"
    };
  }
}

message GetRoyaltyInfoRequest {
  uint64 token_id = 1;
}

message GetRoyaltyInfoResponse {
  repeated Split split = 1;
}

message Split {
  string recipient = 1;         // wallet address
  uint32 share_bps   = 2;       // basis points
}
```

Rust code is generated with `prost` + `tonic_build`:

```rust
// build.rs
fn main() -> Result<(), Box<dyn std::error::Error>> {
    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .out_dir("src/proto")
        .compile(&[
            "proto/canvaschain/market/v1/royalty_service.proto",
        ], &["proto"])?;
    Ok(())
}
```

### 4.2 gRPC Infrastructure Patterns

* **Interceptors:** Uniform wallet-signature validation (`x-canvas-sig`), request tracing (OpenTelemetry).  
* **Resilience:** `tower::retry::Retry` with exponential backoff for transient failures.  
* **Codegen Regeneration:** GitHub Action enforces that `cargo build --workspace` fails if `proto/` drift is detected.

### 4.3 NATS JetStream Topology

Subject naming convention: `domain.context.version.resource.event`  
Example: `nft.composer.v1.artwork.minted`

* **Streams:**  
  * `core.events` – all critical state changes, storage TTL = 365 d, ack = explicit  
  * `telemetry.metrics` – non-critical stats, storage TTL = 1 d, ack = none  
* **Consumers:**  
  * Durable pull consumer per microservice (`composer_core`, `gallery_renderer`, …).  
  * Ephemeral consumers for CLI tools and data scientists.

Rust subscription example:

```rust
let event: MintedEvent = jetstream
    .get_stream("core.events")?
    .create_consumer(ConsumerConfig {
        durable_name: Some("gallery_renderer".to_string()),
        filter_subject: "nft.composer.v1.artwork.minted".into(),
        deliver_policy: DeliverPolicy::All,
        ack_policy: AckPolicy::Explicit,
        ..Default::default()
    })?
    .messages()?
    .next()
    .await?
    .unwrap()
    .deserialize()?;
```

### 4.4 Transactional Outbox Pattern

To avoid dual-write hazards between the PostgreSQL command side and the event bus, each service implements the **Transactional Outbox** pattern. A reliable background task (`tokio::spawn`) pulls unsent events, publishes to NATS, and marks them dispatched. This guarantees at-least-once delivery even if the service crashes mid-transaction.

![Transactional Outbox Diagram](../../design/diagrams/transactional_outbox.png)

---

## 5. Security Considerations

* **mTLS Everywhere:** Shared SPIFFE IDs (`spiffe://canvaschain/{service}`) issued by cert-manager.  
* **Subject ACLs:** Only the `composer` may publish on `nft.composer.*`; others read-only.  
* **JWT Claims:** gRPC headers leverage short-lived JWTs signed by the `auth` service, propagated via NATS headers for traceability.  
* **Replay Protection:** Nonces + timestamp fields in all state-changing Protobuf messages.

---

## 6. Consequences

### Positive

* Consistent developer experience across sync and async messaging.
* Performance-optimized binary encoding keeps latency < 15 ms P99 inside the same AZ.
* Pluggable structure: any service can be rewritten in another language with minimal friction.
* Observability is unified via OpenTelemetry exporters for `tonic` and `nats.rs`.

### Negative / Trade-offs

* Learning curve for contributors unfamiliar with Protocol Buffers.
* Operationally, we must maintain a NATS cluster (RAFT group) in addition to the Postgres DB.
* Protobuf evolution requires backward-compatibility discipline to avoid breaking older miners.

---

## 7. Measures of Success

1. End-to-end mint-to-marketplace latency ≤ 200 ms on staging.
2. Zero lost critical events during chaos-testing (`chaos-nats` network partitions).
3. Successful inter-op PoC of Python `remixer` plugin subscribing to `nft.*` events.

---

## 8. References

* NATS JetStream Design: https://docs.nats.io/jetstream  
* tonic gRPC Rust Library: https://github.com/hyperium/tonic  
* “Transactional Outbox” by Pat Helland: https://microservices.io/patterns/data/transactional-outbox.html  
* gRPC Security Best Practices: https://grpc.io/docs/guides/security/

---

*(END OF ADR)*