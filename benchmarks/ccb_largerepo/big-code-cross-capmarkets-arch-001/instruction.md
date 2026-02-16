# big-code-cross-capmarkets-arch-001: Kafka-Flink Streaming Data Flow (Cross-Repo)

## Task

Trace how streaming data flows from Apache Kafka through Apache Flink's connector framework. Map the complete pipeline from Kafka's producer/consumer API, through the Flink connector base framework, to Flink's streaming runtime. Identify the serialization/deserialization boundary between the two systems and explain how Flink's checkpoint mechanism integrates with Kafka's consumer offset commits.

## Context

- **Repositories**: apache/kafka (Java, ~1M LOC) + apache/flink (Java, ~2M LOC)
- **Category**: Architectural Understanding (cross-repo, capital markets)
- **Difficulty**: hard
- **Domain**: Streaming data infrastructure for capital markets (trade ingestion, pricing, risk)

## Architecture Overview

The Kafka-Flink integration spans two independent projects:

1. **Apache Kafka** — Provides the producer/consumer client API, serialization interfaces, and consumer group coordination
2. **Apache Flink** — Provides the Source/Sink API (flink-core), the connector base framework (flink-connector-base), and the SourceOperator runtime integration (flink-runtime)

The Flink Kafka connector (in a separate repo: apache/flink-connector-kafka) extends Flink's connector-base framework and wraps Kafka's consumer/producer APIs. This task focuses on the API contracts in both main repos that the connector bridges.

## Requirements

1. Map Kafka's producer API: Producer interface, KafkaProducer, ProducerRecord, Serializer
2. Map Kafka's consumer API: Consumer interface, KafkaConsumer, ConsumerRecord, Deserializer, OffsetAndMetadata
3. Map Flink's Source API: Source, SourceReader, SplitEnumerator interfaces
4. Map Flink's connector-base framework: SourceReaderBase, SplitReader, RecordEmitter
5. Map Flink's serde boundary: DeserializationSchema, SerializationSchema
6. Trace the checkpoint-offset integration: SourceOperator.snapshotState() -> SourceReader -> KafkaConsumer.commitSync()

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```markdown
## Files Examined
- kafka/clients/src/.../Producer.java — role in data flow
- flink/flink-core/src/.../Source.java — role in data flow
...

## Dependency Chain
1. Kafka producer: ProducerRecord -> Serializer -> KafkaProducer
2. Kafka consumer: KafkaConsumer -> Deserializer -> ConsumerRecord -> OffsetAndMetadata
3. Flink Source API: Source -> SourceReader -> SplitEnumerator
4. Flink connector-base: SourceReaderBase -> SplitReader -> RecordEmitter
5. Flink serde: DeserializationSchema / SerializationSchema
6. Flink runtime: SourceOperator (checkpoint -> offset commit)
...

## Analysis
[Detailed cross-repo architectural analysis including:
- How Kafka's consumer API is wrapped by Flink's SplitReader
- The dual serialization boundary (Kafka Serializer/Deserializer + Flink Schema)
- How checkpoint completion triggers Kafka offset commits
- The consumer group coordination model
- Thread architecture: Kafka's Fetcher/Sender vs Flink's SplitFetcherManager]

## Summary
[Concise 2-3 sentence summary of the Kafka-Flink data flow]
```

## Evaluation Criteria

- File recall: Did you find files from BOTH repos (Kafka client API + Flink Source/connector-base)?
- Dependency accuracy: Did you trace the correct cross-repo data flow?
- Architectural coherence: Did you identify the serialization boundary and checkpoint-offset integration?
