```markdown
# ChirpPulse Public API

Welcome to the ChirpPulse API documentation.  
This document describes the **Rust SDK** that ships with the platform and shows how to:

1. Connect to the real-time event fire-hose.  
2. Configure an enrichment pipeline.  
3. Publish analytic results back to Kafka / Iceberg.  
4. Extend the platform with a **custom strategy** (plug-in) that can be hot-swapped in production.

---

## Quick-Start

Add the SDK to your `Cargo.toml`:

```toml
[dependencies]
chirp-pulse = { version = "0.9", features = ["streams", "strategy"] }
tokio        = { version = "1",   features = ["full"] }
```

Consumers are fully `async` and integrate with the Tokio runtime.

---

## Data Model

```rust
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// A flattened representation of any micro-interaction captured by ChirpPulse.
///
/// The schema is forward-compatible and will evolve with optional fields.
/// Unknown fields must be gracefully ignored by downstream services.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SocialEvent {
    /// Unique, idempotent identifier applied by the ingestion layer.
    pub id: Uuid,

    /// Original platform: twitter, reddit, mastodon, etc.
    pub source: &'static str,

    /// RFC-3339 timestamp of when the event was GENERATED on its native platform.
    pub occurred_at: DateTime<Utc>,

    /// The raw, unmodified payload
    pub payload: serde_json::Value,
}
```

---

## Streaming the Fire-Hose

```rust,no_run
use chirp_pulse::sdk::{
    firehose::{FireHoseConsumer, FireHoseConfig},
    prelude::*,
};
use tokio_stream::StreamExt;

#[tokio::main]
async fn main() -> Result<(), chirp_pulse::Error> {
    // 1. Create a config with sensible defaults + overrides.
    let cfg = FireHoseConfig::builder()
        .brokers(["kafka-broker-1:9092", "kafka-broker-2:9092"])
        .group_id("brand-insights-team")
        .topic("chirppulse.firehose.raw")
        .auto_commit_interval_ms(5_000)
        .build()?;

    // 2. Stand-up an asynchronous consumer.
    let mut consumer = FireHoseConsumer::connect(cfg).await?;

    // 3. Consume indefinitely, applying back-pressure automatically.
    while let Some(event) = consumer.next().await {
        match event {
            Ok(record) => {
                println!(
                    "Got event {} from {} at {}",
                    record.value.id, record.value.source, record.value.occurred_at
                );
            }
            Err(e) => {
                // Non-fatal parsing errors (e.g. schema evolution) can be logged & skipped.
                eprintln!("⚠️  Undeserializable record skipped: {e:?}");
            }
        }
    }

    Ok(())
}
```

Key characteristics:
* **At-least-once** delivery with idempotent IDs.
* **Offset management** handled by the SDK (exposed for advanced use-cases).
* Transparent **schema evolution** support via Serde’s non-strict deserialization.

---

## Enrichment Pipelines

ChirpPulse ships with an opinionated but extensible ETL pipeline expressed as an
**observer pattern** backed by **Kafka Streams**.  
Below is a complete, runnable example that adds *language detection* and a custom
*toxicity score* while enforcing data-quality thresholds.

```rust,no_run
use chirp_pulse::{
    sdk::{
        enrich::{Pipeline, Stage},
        firehose::{FireHoseConsumer, FireHoseConfig},
        producers::TopicProducer,
    },
    algorithms::{language::LangDetector, toxicity::ToxicityClassifier},
};

#[tokio::main]
async fn main() -> Result<(), chirp_pulse::Error> {
    // Build ingestion side.
    let source_cfg = FireHoseConfig::builder()
        .topic("chirppulse.firehose.raw")
        .group_id("enrichment-worker-a")
        .build()?;
    let mut firehose = FireHoseConsumer::connect(source_cfg).await?;

    // Build egress side.
    let sink = TopicProducer::builder()
        .topic("chirppulse.firehose.enriched")
        .brokers(["kafka-broker-1:9092"])
        .build()?;

    // Compose the pipeline.
    let pipeline = Pipeline::new()
        .with_stage(Stage::sync("language", LangDetector::default()))
        .with_stage(Stage::async("toxicity", ToxicityClassifier::new(0.85)?))
        .with_stage(Stage::sync("qc", |mut event| {
            // Drop events that don't meet minimum quality scores.
            if let Some(tox) = event
                .metadata
                .get("toxicity")
                .and_then(|v| v.as_f64())
            {
                if tox > 0.95 {
                    // Reject extreme toxicity
                    return None;
                }
            }
            Some(event)
        }));

    // Run forever — pipeline maintains back-pressure internally.
    while let Some(event) = firehose.next().await.transpose()? {
        if let Some(enriched) = pipeline.process(event).await? {
            sink.send(&enriched).await?;
        }
    }

    Ok(())
}
```

### Building Blocks

* `Stage::sync` – executes on the current task; suited for CPU-bound, fast ops.  
* `Stage::async` – spawns a bounded task-pool; suited for I/O or heavy compute.  
* `Pipeline::process` – short-circuit returns `None` to **filter** events.

---

## Implementing a Custom Strategy

Analytical algorithms are loaded via an SPI-like **Strategy pattern** allowing them
to be upgraded *without cluster downtime*.

```rust,no_run
use async_trait::async_trait;
use chirp_pulse::sdk::strategy::{AnalysisCtx, Strategy};

/// Counts emoji usage in real-time.
pub struct EmojiRadar;

#[async_trait]
impl Strategy for EmojiRadar {
    const NAME: &'static str = "emoji-radar";
    type Error = anyhow::Error;

    async fn analyze(&self, ctx: &AnalysisCtx) -> Result<(), Self::Error> {
        let event = &ctx.event;

        let text = event
            .payload
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or_default();

        let emoji_count = text.chars().filter(|c| c.is_emoji_presentation()).count();

        ctx.emit_metric("emoji_count", emoji_count as f64).await?;
        Ok(())
    }
}
```

To register your strategy at runtime:

```rust
use chirp_pulse::sdk::strategy::{StrategyLoader, StrategyServer};

#[tokio::main]
async fn main() -> Result<(), chirp_pulse::Error> {
    StrategyLoader::default()
        .register(Box::new(EmojiRadar))
        .load()?;

    StrategyServer::bind("0.0.0.0:8080").await?.run_forever().await
}
```

---

## REST / gRPC Gateways

Every microservice exposes **OpenAPI v3** & **gRPC** reflection at `/api`.
Example (TypeScript generated client shown for completeness):

```rust,ignore
// Equivalent Rust client is autogenerated via `tonic-build`.
import {FireHoseClient} from 'chirp-pulse/clients/firehose';

const client = new FireHoseClient('grpc+tls://firehose.chirppulse.io');

const stream = client.tail({topic: 'chirppulse.firehose.enriched'});

for await (const event of stream) {
  console.log(event.id, event.source);
}
```

---

## Back-Pressure & Retry Semantics

All producers and consumers expose a `pending()` gauge and `flush()` async call
allowing you to gracefully drain in-flight messages before shutdown signals.

```rust,no_run
signal_hook::flag::register_conditional_default(
    signal_hook::consts::SIGTERM,
    || {
        println!("Shutdown requested. Flushing…");
        producer.flush(); // async barrier
    },
);
```

---

## Error Handling

* **Typed errors** (`chirp_pulse::Error`) cover connection failures, schema problems,
  and pipeline time-outs.
* Every fatal error is reported to **OpenTelemetry** traces *and* bubbled up.

```rust
match consumer.next().await {
    Some(Err(chirp_pulse::Error::Deserializer(e))) => {
        metrics::increment_counter!("events_deser_failed");
        // The SDK automatically commits the offset to avoid poison-pill loops.
    }
    Some(Err(e)) => return Err(e.into()),
    Some(Ok(event)) => { /* happy path */ }
    None => unreachable!("stream never ends"),
}
```

---

## Contributing

Pull-requests must pass:

1. `cargo fmt --all -- --check`  
2. `cargo clippy --all-targets -- -D warnings`  
3. `cargo test` – including integration tests that target a **real** Kafka test-container.

---

© 2023–present **ChirpPulse**.  
Licensed under Apache-2.0.
```