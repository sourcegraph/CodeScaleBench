# Kafka-Flink Streaming Data Flow: Cross-Repository Architecture Analysis

## Executive Summary

The Kafka-Flink integration bridges two independent frameworks through carefully abstracted interfaces:
1. **Apache Kafka** provides the `Producer`/`Consumer` APIs with `Serializer`/`Deserializer` for client-level serialization
2. **Apache Flink** provides the `Source` API with `SourceReader`/`SplitEnumerator` for distributed stream processing
3. **Flink Connector Base** (separate repo) provides the `SourceReaderBase` framework that wraps Kafka consumers into Flink's split-based reading model
4. **Flink Serde boundary** introduces a secondary serialization layer via `DeserializationSchema`/`SerializationSchema` for Flink-specific type handling
5. **Checkpoint-Offset integration** connects Flink's snapshot mechanism to Kafka's offset commit protocol through `SourceOperator.snapshotState()` → `SourceReader.snapshotState()` → `KafkaConsumer.commitSync()`

---

## Files Examined

### Apache Kafka (Producer/Consumer APIs)
- **kafka/clients/src/main/java/org/apache/kafka/clients/producer/Producer.java** — Interface defining send(), flush(), close() operations for Kafka producers
- **kafka/clients/src/main/java/org/apache/kafka/clients/producer/ProducerRecord.java** — Data structure (topic, partition, key, value, timestamp, headers) sent through producers
- **kafka/clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java** — Implementation of Producer interface; handles serialization via Serializer, routing, buffering, and network I/O (~2100 lines)
- **kafka/clients/src/main/java/org/apache/kafka/clients/consumer/Consumer.java** — Interface defining poll(), subscribe(), commitSync()/commitAsync(), seek() for consumers
- **kafka/clients/src/main/java/org/apache/kafka/clients/consumer/ConsumerRecord.java** — Data structure (topic, partition, offset, key, value, timestamp, headers, leaderEpoch) returned from consumer polls
- **kafka/clients/src/main/java/org/apache/kafka/clients/consumer/OffsetAndMetadata.java** — Offset state (offset value, metadata string, leader epoch) used for managing consumer position and commit state
- **kafka/clients/src/main/java/org/apache/kafka/clients/consumer/KafkaConsumer.java** — Implementation of Consumer interface; manages group coordination, rebalancing, fetching, and offset commits (~3300 lines)
- **kafka/clients/src/main/java/org/apache/kafka/common/serialization/Serializer.java** — Interface for converting objects → bytes; topic-aware with Headers support
- **kafka/clients/src/main/java/org/apache/kafka/common/serialization/Deserializer.java** — Interface for converting bytes → objects; topic-aware with Headers support and ByteBuffer variant

### Apache Flink Source API (Core Framework)
- **flink/flink-core/src/main/java/org/apache/flink/api/connector/source/Source.java** — Factory interface producing SplitEnumerator and SourceReader; defines boundedness and serializers for splits/enumerator state
- **flink/flink-core/src/main/java/org/apache/flink/api/connector/source/SourceReader.java** — Interface for reading from splits (assigned by enumerator); methods: start(), pollNext(), snapshotState(), isAvailable(), addSplits(), notifyNoMoreSplits()
- **flink/flink-core/src/main/java/org/apache/flink/api/connector/source/SplitEnumerator.java** — Interface for discovering and assigning splits to readers; methods: start(), snapshotState(), handleSplitRequest(), addSplitsBack(), notifyCheckpointComplete()
- **flink/flink-core/src/main/java/org/apache/flink/api/common/serialization/DeserializationSchema.java** — Flink-specific serde interface for converting bytes → typed objects; includes InitializationContext for metrics/classloaders

### Flink Connector Base Framework (Reader/Fetcher Infrastructure)
- **flink/flink-connectors/flink-connector-base/src/main/java/org/apache/flink/connector/base/source/reader/SourceReaderBase.java** — Abstract implementation of SourceReader using SplitFetcherManager and RecordEmitter; handles split state, element buffering, and polling (~400+ lines)
- **flink/flink-connectors/flink-connector-base/src/main/java/org/apache/flink/connector/base/source/reader/splitreader/SplitReader.java** — Interface for reading from one or more splits in a single thread; methods: fetch(), handleSplitsChanges(), wakeUp()
- **flink/flink-connectors/flink-connector-base/src/main/java/org/apache/flink/connector/base/source/reader/RecordEmitter.java** — Interface for transforming fetched elements into output records; method: emitRecord(element, output, splitState)
- **flink/flink-connectors/flink-connector-base/src/main/java/org/apache/flink/connector/base/source/reader/fetcher/SplitFetcherManager.java** — Manages background fetcher threads; coordinates SplitFetcher tasks for non-blocking I/O (referenced in SourceReaderBase)

### Flink Runtime (Checkpoint-Offset Integration)
- **flink/flink-runtime/src/main/java/org/apache/flink/streaming/api/operators/SourceOperator.java** — Stream operator wrapping SourceReader; manages state initialization, checkpointing, and event routing; crucially implements snapshotState(StateSnapshotContext) method that calls sourceReader.snapshotState(checkpointId) and updates readerState (lines 608-612), and notifyCheckpointComplete(checkpointId) that propagates to sourceReader.notifyCheckpointComplete() (lines 640-643)

---

## Dependency Chain & Data Flow

### 1. Kafka Producer Path: ProducerRecord → Serializer → KafkaProducer

```
Application Code
    ↓
ProducerRecord<K, V>
    ├─ topic: String
    ├─ partition: Integer (optional)
    ├─ key: K
    ├─ value: V
    ├─ timestamp: Long (optional, system-assigned if null)
    └─ headers: Headers
    ↓
Serializer<K>.serialize(topic, key) → byte[]  [Key serialization]
Serializer<V>.serialize(topic, value) → byte[]  [Value serialization]
    ↓
KafkaProducer
    ├─ Batches records in memory
    ├─ Routes to partition (via Partitioner + key hash or round-robin)
    ├─ Intercepts via ProducerInterceptor
    └─ Sends to broker network
    ↓
Broker
    └─ Stores in partition log at offset N
    ↓
RecordMetadata
    ├─ topic, partition, offset (assigned by broker)
    ├─ timestamp (system or broker-assigned)
    └─ serialized sizes
```

**Role in data flow:** Kafka producers serialize structured data into bytes for transmission. For capital markets use cases (trade ingestion), ProducerRecord encapsulates tick data, order events, or risk signals with timestamps and optional headers for metadata (e.g., source system ID).

---

### 2. Kafka Consumer Path: KafkaConsumer → Deserializer → ConsumerRecord → OffsetAndMetadata

```
Application Code (e.g., Flink SplitReader)
    ↓
Consumer<K, V> consumer = new KafkaConsumer<K, V>(configs)
    ├─ subscribe(Collection<String> topics) OR assign(Collection<TopicPartition> partitions)
    ├─ Optional: ConsumerRebalanceListener for rebalance callbacks
    └─ Optional: seek(TopicPartition, long) to position at offset
    ↓
consumer.poll(Duration timeout) → ConsumerRecords<K, V>
    ↓
KafkaConsumer Internal Flow:
    ├─ Fetcher thread: Requests fetch from brokers (respects max.bytes, max.poll.records)
    ├─ Broker returns: FetchResponse with record batches
    ├─ Deserializer<K>.deserialize(topic, key_bytes) → K
    ├─ Deserializer<V>.deserialize(topic, value_bytes) → V
    └─ Creates ConsumerRecord<K, V> for each record:
        ├─ topic, partition, offset
        ├─ key: K, value: V
        ├─ timestamp (broker-assigned or producer-assigned)
        ├─ leaderEpoch (for log truncation detection)
        └─ headers
    ↓
Application processes ConsumerRecord objects
    ↓
consumer.commitSync(Map<TopicPartition, OffsetAndMetadata> offsets)
    ├─ Sends OffsetCommit request to broker (coordinator)
    ├─ OffsetAndMetadata contains:
    │   ├─ offset: next offset to consume (exclusive)
    │   ├─ metadata: optional string (e.g., checkpoint ID, user data)
    │   └─ leaderEpoch: for log recovery validation
    └─ Broker persists in __consumer_offsets topic
    ↓
Consumer group coordinate rebalance if members join/leave
    └─ Rebalance listener callbacks (onPartitionsRevokedBefore, onPartitionsAssigned)
```

**Role in data flow:** Kafka consumers provide a group-coordinated polling API that deserializes bytes into typed ConsumerRecords and manages offset state. Multiple consumer instances in a group load-balance partition consumption. Offset commits record the last processed position, enabling recovery and exactly-once semantics (combined with transactions).

---

### 3. Flink Source API: Source → SourceReader → SplitEnumerator

```
StreamingProgram
    ↓
StreamExecutionEnvironment.fromSource(Source<T, SplitT, EnumChkT>)
    ↓
Source<T, SplitT, EnumChkT> Interface:
    ├─ getBoundedness() → BOUNDED / UNBOUNDED
    ├─ createEnumerator(SplitEnumeratorContext) → SplitEnumerator<SplitT, EnumChkT>
    ├─ restoreEnumerator(context, checkpoint) → SplitEnumerator (for recovery)
    ├─ getSplitSerializer() → SimpleVersionedSerializer<SplitT>
    └─ getEnumeratorCheckpointSerializer() → SimpleVersionedSerializer<EnumChkT>
    ↓
SplitEnumerator (JobManager-side, single instance)
    ├─ start()
    ├─ handleSplitRequest(subtaskId) — reader asks for split
    ├─ addSplitsBack(splits, subtaskId) — handle reader failure
    ├─ snapshotState(checkpointId) → EnumChkT (persisted to checkpoint)
    └─ assignSplit() via SplitEnumeratorContext → sends split to reader
    ↓
TaskManager × N (parallel subtasks)
    ↓
SourceReader (TaskManager-side, per parallel subtask)
    ├─ start()
    ├─ pollNext(ReaderOutput) → InputStatus (ONE record emitted per call)
    ├─ addSplits(List<SplitT>) — receive assigned splits
    ├─ snapshotState(checkpointId) → List<SplitT> (in-flight splits returned)
    ├─ isAvailable() → CompletableFuture (signals when data ready)
    ├─ notifyNoMoreSplits() — enumerator done assigning
    └─ notifyCheckpointComplete(checkpointId) — checkpoint committed
    ↓
SourceReader emits records via ReaderOutput<T>
    └─ Records flow downstream to operators
```

**Role in data flow:** The Source API abstracts source connectors as split-enumeration + parallel reading. SplitEnumerator discovers partitions/files/shards; SourceReaders consume splits independently. For Kafka, splits = TopicPartition; enumerator = Kafka consumer group coordinator simulation; readers = per-partition consumers.

---

### 4. Flink Connector Base Framework: SourceReaderBase → SplitReader → RecordEmitter

```
SourceReaderFactory.createReader() (from Source interface)
    ↓
SourceReaderBase<E, T, SplitT, SplitStateT> (Abstract implementation)
    ├─ SplitFetcherManager<E, SplitT> — manages background fetch threads
    ├─ RecordEmitter<E, T, SplitStateT> — transforms E → T
    ├─ FutureCompletingBlockingQueue<RecordsWithSplitIds<E>> — buffers fetched records
    ├─ Map<String, SplitContext<T, SplitStateT>> — maintains per-split state
    └─ Implements SourceReader<T, SplitT>
    ↓
SourceReaderBase.pollNext(ReaderOutput<T>) Implementation:
    1. Check if split fetch buffer has records
    2. If empty, request from SplitFetcherManager via FutureCompletingBlockingQueue
    3. For each buffered element E:
       └─ RecordEmitter.emitRecord(element, output, splitState)
          ├─ Transforms E → T (deserialization, extraction)
          ├─ Emits T via SourceOutput<T>.collect(T)
          └─ Updates SplitStateT (e.g., offset tracking)
    4. Return InputStatus.MORE_AVAILABLE or NO_MORE_AVAILABLE
    ↓
SplitFetcherManager (Background threads)
    ├─ Maintains pool of SplitFetcher threads
    ├─ Each SplitFetcher wraps a SplitReader<E, SplitT>
    ├─ Orchestrates fetch tasks: FetchTask (calls SplitReader.fetch())
    ├─ RecordsWithSplitIds<E> collected from all fetchers
    └─ Puts results into SourceReaderBase's queue
    ↓
SplitReader<E, SplitT> Interface (Connector-specific)
    ├─ fetch() → RecordsWithSplitIds<E>  [BLOCKING, per-thread]
    ├─ handleSplitsChanges(SplitsChange<SplitT>)  [Add/remove splits]
    └─ wakeUp()  [Unblock fetch if sleeping]
    ↓
For Kafka Connector (KafkaSourceReader):
    SplitReader implementation wraps KafkaConsumer:
    ├─ poll() on KafkaConsumer → ConsumerRecord<byte[], byte[]>
    ├─ Deserialize key/value via Serializer/Deserializer
    ├─ Return wrapped as RecordsWithSplitIds<ConsumerRecord<K, V>>
    └─ Track offset in split state (for snapshotState)
    ↓
RecordEmitter<E, T, SplitStateT> Interface
    └─ emitRecord(ConsumerRecord, output, KafkaPartitionState):
        ├─ Extract timestamp from ConsumerRecord
        ├─ Emit via output.collect(T)
        └─ Update KafkaPartitionState.offset to ConsumerRecord.offset + 1
```

**Role in data flow:** SourceReaderBase provides a tested, production-ready framework for connectors. It abstracts threading (SplitFetcherManager), buffering, and polling mechanics. RecordEmitter acts as a transformation hook where connectors apply Flink's DeserializationSchema and state updates.

---

### 5. Dual Serialization Boundary: Kafka Serde + Flink Serde

```
Raw bytes on broker
    ↓
┌─────────────────────────────────────────────────────────────┐
│ KAFKA SERIALIZATION LAYER (Client-side)                     │
│ ─────────────────────────────────────────────────────────── │
│ KafkaConsumer.poll()                                        │
│   └─ Deserializer<K>.deserialize(topic, key_bytes) → K     │
│   └─ Deserializer<V>.deserialize(topic, value_bytes) → V   │
│ Returns: ConsumerRecord<K, V> (typed, but K/V may be       │
│          generic: often String, Long, or byte[] for raw)   │
└─────────────────────────────────────────────────────────────┘
    ↓
ConsumerRecord<K, V> → RecordsWithSplitIds<ConsumerRecord<K, V>>
    ↓
┌─────────────────────────────────────────────────────────────┐
│ FLINK SERIALIZATION LAYER (Flink-specific)                 │
│ ─────────────────────────────────────────────────────────── │
│ RecordEmitter.emitRecord(ConsumerRecord, output, state):   │
│   └─ If ConsumerRecord<String, Trade>:                     │
│       ├─ Extract key/value already typed by Kafka          │
│       └─ Pass through or transform via                      │
│           DeserializationSchema<T>.deserialize(value_bytes) │
│   └─ More commonly: ConsumerRecord<byte[], byte[]>:        │
│       └─ DeserializationSchema<T> applied here:            │
│           ├─ Deserialize complete record bytes → T         │
│           ├─ Extract timestamp, watermarks                 │
│           └─ Supports multi-record emission via Collector  │
│ Returns: T (fully deserialized, Flink-typed)              │
│ Emits: output.collect(T)                                   │
└─────────────────────────────────────────────────────────────┘
    ↓
Downstream Flink Operators receive T (fully typed)
```

**Design rationale:**
- **Kafka's Serializer/Deserializer:** Client-side, topic-aware, header-aware. Decouples producers/consumers from serialization format. For capital markets, often StringSerde (JSON tick data) or custom binary protocols.
- **Flink's DeserializationSchema:** Framework-level, enables Flink to:
  - Support complex types (Avro, Protobuf, custom POJOs via reflection)
  - Integrate with Flink's type system (TypeInformation, TypeSerializer)
  - Emit metrics and state updates
  - Multi-record deserialization (via Collector pattern)
  - Handle watermarks and timestamps separately from payload

For Kafka-to-Flink pipelines, typical flow:
```
KafkaConsumer polls byte[]
  ├─ Kafka Deserializer converts to intermediate type (e.g., String/GenericRecord)
  └─ Flink DeserializationSchema further deserializes to domain type (e.g., Trade, OrderEvent)
```

---

### 6. Checkpoint-Offset Integration: SourceOperator.snapshotState() ↔ KafkaConsumer.commitSync()

#### A. Checkpoint Trigger Flow

```
StreamTask.triggerCheckpoint()
    ↓
SourceOperator.snapshotState(StateSnapshotContext context)  [Line 608-612]
    │
    ├─ long checkpointId = context.getCheckpointId()
    │
    ├─ List<SplitT> splits = sourceReader.snapshotState(checkpointId)
    │   [SourceReader interface, line 80]
    │   └─ SourceReaderBase implementation:
    │      ├─ Collects all splits from splitStates map
    │      ├─ Each split state may include current offset (if KafkaPartitionState)
    │      └─ Returns List<KafkaPartitionSplit> with lastConsumedOffset
    │
    └─ readerState.update(splits)
       [ListState<SplitT>, persisted to checkpoint backend]
       └─ Serialized via splitSerializer (from Source.getSplitSerializer())
       └─ For Kafka: KafkaPartitionSplitSerializer encodes TopicPartition + offset range
```

**Data structure:** For Kafka, snapshot contains:
```java
KafkaPartitionSplit {
    TopicPartition topicPartition,
    long startingOffset,      // offset we're reading from
    long stoppingOffset,      // stopping criterion (if bounded)
}
```

#### B. Checkpoint Completion Flow

```
CheckpointCoordinator (JobManager)
    ├─ Waits for all tasks to acknowledge snapshot complete
    └─ Notifies when checkpoint durably committed
    ↓
StreamTask.notifyCheckpointComplete(checkpointId)
    ↓
SourceOperator.notifyCheckpointComplete(checkpointId)  [Line 640-643]
    │
    └─ sourceReader.notifyCheckpointComplete(checkpointId)
       [SourceReader interface, line 141]
       └─ KafkaSourceReader implementation (in flink-connector-kafka):
          ├─ For each KafkaPartitionState tracked:
          │   ├─ Extract latest offset from snapshotted state
          │   ├─ Build Map<TopicPartition, OffsetAndMetadata>:
          │   │   ├─ TopicPartition key
          │   │   └─ OffsetAndMetadata {
          │   │       offset: lastConsumedOffset + 1,  [next to consume]
          │   │       metadata: checkpointId (optional)
          │   │   }
          │   │
          │   └─ consumer.commitSync(Map<TopicPartition, OffsetAndMetadata>)
          │       [Kafka Consumer API, line 109-114]
          │       └─ Sends OffsetCommit request to broker
          │           ├─ Broker updates __consumer_offsets topic
          │           └─ Persists committed offset durably
          │
          └─ On failure: offsets NOT committed (no notifyCheckpointComplete)
             → Flink restores from checkpoint
             → SplitEnumerator restores topology
             → SourceReaders rewind to snapshotted offsets
             → KafkaSourceReaders call consumer.seek(TopicPartition, offset)
```

#### C. Recovery Path

```
TaskManager restart after failure
    ↓
SourceOperator.initializeState(StateInitializationContext context)
    ├─ Restores readerState from checkpoint backend
    │
    └─ For each split in restored state:
        ├─ SplitEnumerator.restoreEnumerator() — restores partition discovery state
        │
        └─ SourceReader.addSplits(restoredSplits)
            └─ KafkaSourceReader:
                ├─ consumer.assign(TopicPartitions)
                └─ consumer.seek(TopicPartition, restoredOffset)
                   [Position cursor at snapshotted offset]
                   └─ Next poll() continues from exact offset
```

**Guarantee:** Exactly-once semantics achieved via:
1. **Snapshot atomicity:** All splits snapshotted at same checkpointId
2. **Idempotent offset commits:** commitSync(offset) is idempotent (same offset = no-op on broker)
3. **Transactional write-read:** If downstream operators commit external state at checkpointId, they can use checkpointId to deduplicate (exactly-once end-to-end)

**For capital markets:**
- **Trade ingestion pipeline:** Checkpoint interval determines latency between order execution and analytics visibility
- **Risk scoring:** Snapshot captures mid-computation state (orders in flight) + offset state; ensures risk model doesn't double-count orders on recovery
- **Pricing feeds:** Multiple topic subscriptions snapshotted together; clock skew prevented by single checkpointId

---

## Thread Architecture: Kafka Fetcher/Sender vs Flink SplitFetcherManager

### Kafka Internal Threading

```
KafkaConsumer (Single-threaded application thread)
    └─ poll() call → FutureRecordMetadata + internal network I/O
    ├─ Fetcher (internal, implicit background work)
    │   └─ poll() collects messages from broker fetch responses
    │   └─ send() triggers deserialization
    │   └─ Offset tracking (uncommitted offsets in memory)
    │
    └─ NetworkClient (async I/O)
        ├─ Selector (NIO)
        └─ Future-based send/receive (managed internally)

KafkaProducer (Any thread; thread-safe)
    └─ send(ProducerRecord) → Future<RecordMetadata>
    ├─ Accumulator (batching, buffering)
    ├─ Sender thread (dedicated background thread)
    │   └─ Periodically flushes batches to brokers
    │   └─ Handles retries, compression, idempotence
    │
    └─ NetworkClient (async I/O, same as consumer)
```

### Flink SplitFetcherManager Threading

```
SourceOperator.pollNext() (StreamTask thread, on mailbox)
    │
    ├─ Blocking call: FutureCompletingBlockingQueue.poll()
    │   └─ Waits for SplitFetcherManager to put records
    │
    └─ Non-blocking return to StreamTask
        └─ StreamTask checks SourceOperator.isAvailable()
           ├─ Future resolves when data ready
           └─ Resumes after data arrival
    ↓
SplitFetcherManager (Internal thread pool)
    ├─ Thread pool: N fetcher threads
    ├─ Each SplitFetcher wraps SplitReader (e.g., KafkaConsumer poll)
    ├─ FetchTask queued: calls SplitReader.fetch()
    │   └─ BLOCKING: polls KafkaConsumer, may sleep
    │   └─ Returns RecordsWithSplitIds<ConsumerRecord>
    │
    └─ Records → FutureCompletingBlockingQueue
        └─ Signals SourceOperator that data available
            └─ Wakes up StreamTask (completes isAvailable future)
    ↓
SourceReaderBase.pollNext() (StreamTask thread, continues polling)
    ├─ Non-blocking iteration over queued records
    ├─ RecordEmitter.emitRecord() (per record)
    └─ Returns InputStatus.MORE_AVAILABLE

Key difference:
- Kafka: Producer has background Sender thread; Consumer is single-threaded poll()
- Flink: SourceReaderBase uses SplitFetcherManager thread pool to decouple blocking I/O from task thread
         → Enables reactive, non-blocking progress (isAvailable() futures)
         → Multiple SplitFetchers can run in parallel (more partition concurrency)
```

---

## Consumer Group Coordination Model

### Kafka Broker-Based Coordination

```
KafkaConsumer.subscribe(List<String> topics)
    ├─ Sends FindCoordinator request to any broker
    ├─ Broker responds with coordinator broker ID
    └─ Connects to coordinator broker
    ↓
Coordinator broker manages consumer group:
    ├─ Group state: EMPTY, PREPARING_REBALANCE, STABLE, COMPLETING_REBALANCE, DEAD
    ├─ Member metadata: {memberId, topics, assignmentBytes}
    ├─ Partition assignment: via ConsumerPartitionAssignor (e.g., RangeAssignor, StickyAssignor)
    ├─ Heartbeat protocol: member sends Heartbeat every session.timeout.ms / 3
    └─ Rebalance trigger:
        ├─ New member joins group
        ├─ Member leaves (graceful close) or dies (heartbeat timeout)
        └─ Topic metadata changes (e.g., new partition added)
    ↓
Rebalance Sequence:
    1. Coordinator detects change → sends RevokePartitions to all members
    2. Members call ConsumerRebalanceListener.onPartitionsRevoked()
       └─ Flink may commit offsets here (rare; usually at checkpoint)
    3. Members seek to new assignment
    4. Coordinator assigns new partitions (via assignor)
    5. Members call ConsumerRebalanceListener.onPartitionsAssigned()
       └─ Update internal state, seek to assigned partitions
    6. Member sends JoinGroup response with assignment
    7. Coordinator marks group STABLE
```

### Flink SplitEnumerator Simulation

```
Flink does NOT use Kafka consumer group coordination directly:
Instead, Flink replicates the role:

Source.createEnumerator() (JobManager)
    └─ Instantiates SplitEnumerator<KafkaTopicPartitionSplit, KafkaSourceEnumeratorState>
        ├─ On start(): Queries Kafka broker for partition list (via admin API or metadata)
        │   └─ Gets all TopicPartitions for subscribed topics
        │
        ├─ Manually assigns splits to readers via SplitEnumeratorContext.assignSplit()
        │   └─ Replaces Kafka group coordinator role
        │   └─ Flink scheduler decides which reader (subtask) reads which partition
        │
        └─ On snapshotState(): Returns partition topology + current assignment
            └─ Replaces Kafka broker's __consumer_offsets role

Advantage: Flink's split assignment is locality-aware and deterministic across recovery.
Disadvantage: Requires Flink to handle rebalance manually (if topology changes).
```

---

## Key Integration Points: How Kafka API is Wrapped

### 1. Producer Integration (Egress)

```
Flink SinkFunction/SinkV2
    ├─ Creates KafkaProducer<K, V>(Properties with KafkaProducer.KEY_SERIALIZER_CLASS_CONFIG, VALUE_SERIALIZER_CLASS_CONFIG)
    │
    ├─ invoke(T element):
    │   ├─ Convert T → ProducerRecord<K, V>
    │   │   ├─ Extract key (e.g., first field of POJO)
    │   │   ├─ Payload = value
    │   │   └─ Topic from sink config
    │   │
    │   └─ producer.send(ProducerRecord, Callback)
    │       ├─ ProducerRecord → internal:
    │       │   ├─ Key serialized via Serializer<K>
    │       │   ├─ Value serialized via Serializer<V>
    │       │   └─ Routed to partition
    │       │
    │       └─ Callback triggered on broker ack or error
    │           ├─ Update sink metrics (records sent, bytes sent)
    │           └─ Propagate errors to Flink (failed record count)
    │
    └─ flush() + close() on checkpointComplete / endOfStream
```

### 2. Consumer Integration (Ingress)

```
flink-connector-kafka Source<Out, KafkaPartitionSplit, KafkaSourceEnumeratorState>
    ├─ SplitEnumerator role: Discover partitions
    │   ├─ Create KafkaConsumer(Properties with subscribe/assign)
    │   ├─ Poll partition metadata (via KafkaConsumer.partitionsFor() or admin client)
    │   └─ Return TopicPartitions as splits
    │
    └─ SourceReader role: Consume splits
        ├─ KafkaSourceReader extends SourceReaderBase
        │
        ├─ Creates KafkaConsumer<byte[], byte[]>(Properties with Serializer.class="org.apache.kafka.common.serialization.ByteArraySerializer")
        │   └─ Note: Both key/value are byte[] (raw bytes)
        │   └─ Deserialization deferred to Flink layer
        │
        ├─ SplitReader.fetch():
        │   ├─ For each assigned TopicPartition (split):
        │   │   ├─ consumer.poll(Duration) → ConsumerRecords<byte[], byte[]>
        │   │   ├─ For each ConsumerRecord:
        │   │   │   ├─ Extract raw bytes: record.key(), record.value()
        │   │   │   ├─ Wrap in KafkaSourceFetcher.Record<byte[], byte[]>
        │   │   │   │   ├─ Include: offset, partition, topic, timestamp
        │   │   │   │   └─ Track in KafkaPartitionState.nextOffset
        │   │   │   │
        │   │   │   └─ Yield to queue
        │   │   │
        │   │   └─ Flush committed offsets (optional, usually deferred to notifyCheckpointComplete)
        │   │
        │   └─ Return RecordsWithSplitIds<KafkaRecord>
        │
        ├─ RecordEmitter.emitRecord(KafkaRecord, output, KafkaPartitionState):
        │   ├─ Call DeserializationSchema<T>.deserialize(record.value())
        │   │   └─ Kafka DeserializationSchema (e.g., JSONSerde, AvroDe)
        │   │   └─ Returns T (domain type)
        │   │
        │   ├─ Extract timestamp, key (if needed) from KafkaRecord
        │   │
        │   ├─ output.collect(T)  [Downstream processing]
        │   │
        │   └─ KafkaPartitionState.nextOffset = record.offset() + 1
        │
        ├─ snapshotState(checkpointId):
        │   └─ Return List<KafkaPartitionSplit> with current offset ranges
        │
        └─ notifyCheckpointComplete(checkpointId):
            ├─ For each partition:
            │   ├─ Build OffsetAndMetadata { offset: KafkaPartitionState.nextOffset, metadata: checkpointId.toString() }
            │   └─ consumer.commitSync(Map<TopicPartition, OffsetAndMetadata>)
            │       └─ Persists committed offset to broker
            │
            └─ On next failure/restore: consumer.seek(partition, committedOffset) resumes from checkpoint
```

---

## Summary

The Kafka-Flink data pipeline integrates two sophisticated distributed systems:

1. **Kafka** provides:
   - **Producer API** for write scalability: ProducerRecord → Serializer → KafkaProducer → Brokers
   - **Consumer API** for read scalability: Brokers → KafkaConsumer → Deserializer → ConsumerRecord
   - **Offset management**: OffsetAndMetadata persists consumer position in __consumer_offsets topic
   - **Consumer group coordination**: Broker-based rebalancing and member management

2. **Flink** provides:
   - **Source API** abstraction: SplitEnumerator discovers source splits; SourceReaders consume them independently
   - **Distributed runtime**: SourceOperator on TaskManager wraps SourceReader; manages checkpointing and recovery
   - **Connector-base framework**: SourceReaderBase implements standard patterns (SplitFetcherManager, RecordEmitter) reducing boilerplate
   - **Dual-serde boundary**: Kafka Serializer/Deserializer for client-side typed message interchange; Flink DeserializationSchema for framework-level type integration

3. **Checkpoint-Offset integration** creates exactly-once semantics:
   - SourceOperator.snapshotState() captures SourceReader state (offsets) to Flink's distributed checkpoint store
   - SourceOperator.notifyCheckpointComplete() triggers KafkaConsumer.commitSync() to persist committed offsets to Kafka broker
   - On recovery, SourceReader.addSplits() + consumer.seek() resumes from snapshotted offset
   - Idempotent offset commits + deterministic replay guarantee no message loss or duplication (assuming idempotent downstream sink)

4. **For capital markets**, this architecture enables:
   - **Trade ingestion pipelines** with sub-second latency and exactly-once delivery
   - **Multi-topic aggregation** (orders, executions, prices) with coordinated checkpoints
   - **Risk scoring** that is crash-consistent and auditable
   - **Scalable parallel consumption** of high-frequency tick data from partitioned Kafka topics

The three-layer design (Kafka client ↔ Flink Source API ↔ Flink Runtime) maintains clean separation of concerns: Kafka handles network and persistence; Flink handles distribution and fault tolerance; connectors (in separate repos) bridge the two.
