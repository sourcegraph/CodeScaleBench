# big-code-cross-capmarkets-arch-001: Kafka-Flink Streaming Data Flow (Cross-Repo)

This task spans two large Java repositories. Use comprehensive cross-repo search to trace the data flow between Kafka's client API and Flink's connector framework.

## Task Type: Architectural Understanding (Cross-Repo)

Your goal is to trace how streaming data flows from Kafka through Flink. Focus on:

1. **Kafka producer/consumer API**: Find the core interfaces and implementations in the clients module
2. **Flink Source API**: Find the Source, SourceReader, SplitEnumerator contracts in flink-core
3. **Flink connector-base**: Find the SourceReaderBase, SplitReader, RecordEmitter framework
4. **Flink serde boundary**: Find DeserializationSchema/SerializationSchema
5. **Checkpoint integration**: Find SourceOperator and its snapshotState/notifyCheckpointComplete

## Repositories and Key Paths

### Apache Kafka (under /workspace/kafka/)

| Component | Path |
|-----------|------|
| Producer API | `clients/src/main/java/org/apache/kafka/clients/producer/` |
| Consumer API | `clients/src/main/java/org/apache/kafka/clients/consumer/` |
| Serialization | `clients/src/main/java/org/apache/kafka/common/serialization/` |

**Sourcegraph repo**: `github.com/apache/kafka`

### Apache Flink (under /workspace/flink/)

| Component | Path |
|-----------|------|
| Source API | `flink-core/src/main/java/org/apache/flink/api/connector/source/` |
| Serde | `flink-core/src/main/java/org/apache/flink/api/common/serialization/` |
| Connector base | `flink-connectors/flink-connector-base/src/main/java/org/apache/flink/connector/base/source/reader/` |
| Runtime | `flink-runtime/src/main/java/org/apache/flink/streaming/api/operators/` |

**Sourcegraph repo**: `github.com/apache/flink`

## Key Files to Find

**Kafka (producer side):**
- `Producer.java` — Producer interface (send, commitTransaction)
- `KafkaProducer.java` — Concrete implementation (serialization, partitioning, batching)
- `ProducerRecord.java` — Outbound record data carrier
- `Serializer.java` — serialize(topic, data) -> byte[]

**Kafka (consumer side):**
- `Consumer.java` — Consumer interface (subscribe, poll, commitSync)
- `KafkaConsumer.java` — Concrete implementation (Fetcher, ConsumerCoordinator)
- `ConsumerRecord.java` — Inbound record data carrier
- `Deserializer.java` — deserialize(topic, byte[]) -> T
- `OffsetAndMetadata.java` — Offset commit payload

**Flink (source API):**
- `Source.java` — Top-level Source interface
- `SourceReader.java` — Reader interface (pollNext, snapshotState, notifyCheckpointComplete)
- `SplitEnumerator.java` — Split discovery and assignment

**Flink (connector framework):**
- `SourceReaderBase.java` — Abstract reader with SplitFetcherManager + RecordEmitter
- `SplitReader.java` — Fetch interface (wraps KafkaConsumer.poll)
- `RecordEmitter.java` — Record transformation bridge

**Flink (runtime + serde):**
- `SourceOperator.java` — Runtime operator (checkpoint triggers offset commit)
- `DeserializationSchema.java` — Flink deserialization interface
- `SerializationSchema.java` — Flink serialization interface

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- kafka/clients/src/.../Producer.java — Kafka producer interface
- flink/flink-core/src/.../Source.java — Flink source API

## Dependency Chain
1. Kafka producer API -> Kafka serde -> broker
2. Kafka consumer API -> Kafka serde -> ConsumerRecord
3. Flink SplitReader wraps KafkaConsumer.poll()
4. RecordEmitter bridges ConsumerRecord -> DeserializationSchema -> typed output
5. SourceOperator.snapshotState -> SourceReader -> checkpoint-offset commit

## Analysis
[Cross-repo data flow analysis]
```

## Search Strategy

- Search `github.com/apache/kafka` for `Producer.java`, `Consumer.java`, `Serializer`, `Deserializer`
- Search `github.com/apache/flink` for `Source.java`, `SourceReader`, `SourceReaderBase`, `SplitReader`
- Search for `SourceOperator` in flink-runtime to find the checkpoint integration
- Use `find_references` on `DeserializationSchema` to trace the serde boundary
- Use `go_to_definition` on `SourceReaderBase` to understand the connector framework
