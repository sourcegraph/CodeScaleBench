# Kafka Message Lifecycle

## Q1: Producer-Side Batching and Transmission

When a producer calls `KafkaProducer.send(record)`, the message travels through several stages before reaching the network:

### Serialization and Partition Assignment
- **Entry point**: `KafkaProducer.send(ProducerRecord, Callback)` in `clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java:941`
- The record is first passed through interceptors via `ProducerInterceptor.onSend()` (`clients/src/main/java/org/apache/kafka/clients/producer/ProducerInterceptor.java:42-45`)
- The key and value are serialized independently using configured serializers:
  - Key serialization at line 999: `keySerializerPlugin.get().serialize(record.topic(), record.headers(), record.key())`
  - Value serialization at line 1007: `valueSerializerPlugin.get().serialize(record.topic(), record.headers(), record.value())`
- Partition assignment occurs via `partition()` method (line 1017) which uses the configured partitioner (default: `BuiltInPartitioner` in `clients/src/main/java/org/apache/kafka/clients/producer/internals/BuiltInPartitioner.java`)

### Batching in RecordAccumulator
- **RecordAccumulator role**: `clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java:68` - "This class acts as a queue that accumulates records into MemoryRecords instances to be sent to the server"
- Message is appended to accumulator via `accumulator.append()` (line 1029-1030):
  - Method signature: `RecordAccumulator.append(String topic, int partition, long timestamp, byte[] key, byte[] value, Header[] headers, AppendCallbacks callbacks, long maxTimeToBlock, long nowMs, Cluster cluster)` at line 275
- The append process (lines 294-358):
  1. Determines effective partition based on partition info and broker availability
  2. Attempts to append to existing in-flight batch via `tryAppend()` (line 319)
  3. If batch is full or doesn't exist, allocates new buffer from buffer pool (line 333)
  4. Creates new `ProducerBatch` with `MemoryRecordsBuilder` (line 394): `ProducerBatch(new TopicPartition(topic, partition), recordsBuilder, nowMs)`
  5. Appends record to batch via `ProducerBatch.tryAppend()` which writes the serialized key/value to a `MemoryRecordsBuilder`

### Record Batching Format
- **Batch creation**: `RecordAccumulator.appendNewBatch()` at line 375
- Records are grouped using `ProducerBatch` which wraps a `MemoryRecordsBuilder` (line 393)
- `MemoryRecordsBuilder` encodes records in the current record format (MAGIC value) with:
  - Record batch header metadata
  - Compression codec settings
  - Timestamp information
  - Producer ID and sequence numbers (if idempotent/transactional)

### Sender Thread and Network Transmission
- **Sender thread class**: `clients/src/main/java/org/apache/kafka/clients/producer/internals/Sender.java:79` - "The background thread that handles the sending of produce requests to the Kafka cluster"
- **Main sender loop**: `Sender.runOnce()` at line 305
- **Producer data sending**: `sendProducerData()` at line 357:
  1. Calls `accumulator.ready(metadataSnapshot, now)` (line 360) to identify partitions with ready batches
  2. Returns list of ready nodes that have batches ready for transmission
  3. Calls `accumulator.drain(metadataSnapshot, result.readyNodes, this.maxRequestSize, now)` (line 395) to extract batches from accumulator
- **Ready criteria**: Batches become ready when:
  - Batch size threshold is reached (determined by `batch.size` config), OR
  - Linger time expires (determined by `linger.ms` config), OR
  - Producer is flushed

### Network Request Creation and Transmission
- **Produce requests**: `Sender.sendProduceRequests()` at line 856 sends collated batches
- For each ready node, a `ProduceRequest` is created containing:
  - Required acknowledgments (`acks` setting: 0, 1, or -1 for all)
  - Timeout value
  - TopicPartition → MemoryRecords mapping (batches)
- **Client send**: Via `KafkaClient.send()` which queues the request for network transmission
- **Batch state**: Once sent, batch is moved to in-flight tracking via `addToInflightBatches()` (line 396)

### Callback Mechanism
- **AppendCallbacks**: Wrapper class at line 1558 in KafkaProducer that coordinates:
  - Producer interceptor callbacks
  - User-provided callback
  - Future metadata updates when batch completes
- **Batch completion**: `ProducerBatch.complete(baseOffset, logAppendTime)` at line 218 or `completeExceptionally()` at line 231 fires all callbacks

---

## Q2: Broker-Side Append and Replication

When a produce request arrives at the broker, it is processed through several layers:

### Request Routing
- **KafkaApis handler**: `core/src/main/scala/kafka/server/KafkaApis.scala:388` - `handleProduceRequest(request: RequestChannel.Request, requestLocal: RequestLocal)`
- Extracts `ProduceRequest` from request body (line 389)
- Performs authorization checks and validates records (lines 391-442)
- Routes authorized records to appropriate partitions in a map: `topicIdToPartitionData`

### Replica Manager Coordination
- **Append entry point**: `KafkaApis` calls `ReplicaManager.appendRecords()` or `ReplicaManager.appendRecordsToLeader()` (line 627 in `core/src/main/scala/kafka/server/ReplicaManager.scala`)
- **Method signature** (line 674-682):
  ```
  def appendRecords(timeout: Long, requiredAcks: Short, internalTopicsAllowed: Boolean,
                    origin: AppendOrigin, entriesPerPartition: Map[TopicIdPartition, MemoryRecords],
                    responseCallback: Map[TopicIdPartition, PartitionResponse] => Unit, ...)
  ```

### Local Log Append
- **Local append execution**: `ReplicaManager.appendToLocalLog()` at line 1370
- For each TopicPartition:
  1. Gets partition via `getPartitionOrException(topicIdPartition)` (line 1407)
  2. Calls `Partition.appendRecordsToLeader()` which delegates to `UnifiedLog.appendAsLeader()`
- **UnifiedLog append**: `storage/src/main/java/org/apache/kafka/storage/internals/log/UnifiedLog.java:104` and line 1040
  - Method: `UnifiedLog.appendAsLeaderWithRecordVersion(MemoryRecords records, int leaderEpoch, RecordVersion recordVersion)`
  - Calls internal `append()` method which:
    1. Validates records using `LogValidator` (converts record formats if needed)
    2. Assigns offsets to records
    3. Writes records to current active `LogSegment`
    4. Updates in-memory index structures
    5. Returns `LogAppendInfo` containing: first offset, last offset, timestamps, etc.

### Replication Coordination
- **Replication model**: After local append, broker coordinates replication based on `requiredAcks`:
  - **acks=0**: No acknowledgment required; response sent immediately before replication
  - **acks=1**: Only leader acknowledgment required; response sent after local log append
  - **acks=-1 (all)**: Wait for in-sync replicas (ISR) to acknowledge before responding
- **Delayed produce handling**: For `acks=-1`, `ReplicaManager.maybeAddDelayedProduce()` creates a `DelayedProduce` operation
  - Class: `core/src/main/scala/kafka/server/DelayedProduce.scala:57`
  - Waits for `DelayedOperation.onComplete()` callback which fires when:
    1. Required ISR count acknowledges the append, OR
    2. Timeout expires
  - Upon completion, `sendResponseCallback` is invoked with final `PartitionResponse` status

### Follower Replication
- **ReplicaFetcher threads**: `core/src/main/scala/kafka/server/ReplicaFetcher.scala` fetch data from leader
- Each follower broker runs fetch requests to the leader for assigned partitions
- Fetched data is appended locally via `ReplicaManager.appendRecordsToFollower()`
- Follower updates its replica state and sends acknowledgment to leader
- Leader tracks ISR membership and updates high watermark when replicas acknowledge

### Response Callback
- **sendResponseCallback**: Closure defined at line 449 in `KafkaApis.scala`
- Merges responses from all partitions (authorized, unauthorized, non-existing, invalid)
- Applies quota throttling if needed (lines 484-495)
- Sends `ProduceResponse` containing:
  - For each partition: partition index, error code, base offset, log append timestamp
  - If `acks=0`, sent immediately without waiting for replication

---

## Q3: Consumer-Side Fetch and Delivery

When a consumer calls `poll()`, it retrieves messages through the following stages:

### Fetch Request Preparation and Sending
- **Consumer poll entry point**: `KafkaConsumer.poll(Duration timeout)`
- Internally calls `ClassicKafkaConsumer.poll()` which:
  1. Calls `pollForFetches(timer)` at line 690 in `clients/src/main/java/org/apache/kafka/clients/consumer/internals/ClassicKafkaConsumer.java`
  2. Calls `Fetcher.sendFetches()` at line 105 in `clients/src/main/java/org/apache/kafka/clients/consumer/internals/Fetcher.java`

- **Fetch request creation**: `Fetcher.sendFetches()` and `sendFetchesInternal()` (line 184):
  1. Calls `prepareFetchRequests()` to build map of Node → FetchRequestData for assigned partitions
  2. For each partition: includes current fetch offset, max bytes to fetch, isolation level
  3. Creates `FetchRequest.Builder` via `createFetchRequest(fetchTarget, data)` (line 192)
  4. Sends to each node via `client.send(fetchTarget, request)` (line 193)
  5. Attaches success/failure handlers that call `handleFetchSuccess()` or `handleFetchFailure()`

### Broker-Side Fetch Processing
- **KafkaApis fetch handler**: `core/src/main/scala/kafka/server/KafkaApis.scala:555` - `handleFetchRequest(request: RequestChannel.Request)`
- Extracts `FetchRequest` and creates fetch context
- Validates authorization and partition existence for requested partitions
- **Delayed fetch**: Creates `DelayedFetch` operation via `ReplicaManager.readFromLog()` (line 171 in `core/src/main/scala/kafka/server/DelayedFetch.scala`)
- Reads records from `UnifiedLog.readUncommitted()` or `readCommitted()` based on isolation level
- Returns records as `LogReadResult` containing:
  - Fetched `MemoryRecords` (encoded record batches)
  - High watermark
  - Log start offset
  - Aborted transactions (for transactional reads)

### Fetch Response Processing
- **Success handler**: `Fetcher.handleFetchSuccess()` in `AbstractFetch`
- Receives `ClientResponse` containing `FetchResponse` with MemoryRecords per partition
- Stores response in `FetchBuffer` as `CompletedFetch` objects (each contains FetchResponseData.PartitionData with MemoryRecords)

### Record Deserialization and Collection
- **FetchCollector class**: `clients/src/main/java/org/apache/kafka/clients/consumer/internals/FetchCollector.java:51`
- **collectFetch()** method (line 92):
  1. Iterates through `CompletedFetch` objects in `FetchBuffer`
  2. For each fetch, calls `initialize(completedFetch)` (line 109) which:
     - Calls `handleInitializeSuccess()` (line 228)
     - Returns initialized `CompletedFetch`
  3. Calls `fetchRecords(nextInLineFetch, recordsRemaining)` (line 133):
     - Validates partition is still assigned and fetchable
     - Extracts current fetch position from subscription state
     - Calls `CompletedFetch.fetchRecords(fetchConfig, deserializers, maxRecords)` (line 170)

- **Record deserialization**: Within `CompletedFetch.fetchRecords()`:
  1. Iterates through `RecordBatch` objects in the `MemoryRecords`
  2. For each `RecordBatch`:
     - Validates batch magic version and format
     - Iterates through individual `Record` objects
     - Deserializes key using configured key deserializer
     - Deserializes value using configured value deserializer
     - Creates `ConsumerRecord<K, V>` object with:
       - Topic, partition, offset
       - Timestamp and timestamp type
       - Headers
       - Deserialized key and value
       - LeaderEpoch
       - SerializedKeySize, SerializedValueSize
  3. Returns `List<ConsumerRecord<K, V>>`

- **Fetch returns**: Returns `Fetch<K, V>` object containing all `ConsumerRecord`s from all assigned partitions

### Offset Commit
- **Offset tracking**: `SubscriptionState.position(TopicPartition, FetchPosition)` (line 186 in FetchCollector)
  - Updated after records are returned to track next fetch offset
- **Explicit commit**: Consumer calls `commitSync()` or `commitAsync()` which:
  - Invokes `CommitRequestManager` to send `OffsetCommit` request to group coordinator
  - Updates committed offsets stored on broker in `__consumer_offsets` internal topic
- **Auto-commit**: If `enable.auto.commit=true`, `ConsumerCoordinator` periodically commits offsets

---

## Q4: End-to-End Transformation Points

Listed in order of occurrence as a message flows through the system:

### 1. **Producer Application → Serialized Bytes (Producer-Side)**
- **Location**: `KafkaProducer.doSend()` line 999-1012
- **Transformation**: Java objects (K, V) → byte[] arrays
- **Mechanism**:
  - Key: `keySerializerPlugin.get().serialize(topic, headers, key)` → byte[]
  - Value: `valueSerializerPlugin.get().serialize(topic, headers, value)` → byte[]
- **Files**:
  - Serializers defined in: `org.apache.kafka.common.serialization.*`
  - Wrapper: `clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java:999-1012`

### 2. **Serialized Bytes → ProducerBatch (MemoryRecords) (Producer-Side)**
- **Location**: `RecordAccumulator.appendNewBatch()` line 393-396
- **Transformation**: Serialized bytes + metadata → RecordBatch binary format
- **Mechanism**:
  - Creates `MemoryRecordsBuilder` with compression codec and record format version
  - Appends serialized key/value via `ProducerBatch.tryAppend()`
  - Encodes in current RecordBatch format (v2 with magic value) including:
    - Base offset, sequence numbers
    - Producer ID/epoch
    - Compression codec
    - Timestamps
    - CRC checksum
- **Files**:
  - `clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java:375-400`
  - `clients/src/main/java/org/apache/kafka/clients/producer/internals/ProducerBatch.java:60-100`
  - `org.apache.kafka.common.record.MemoryRecordsBuilder`

### 3. **RecordBatch → Network Transmission (Producer to Broker)**
- **Location**: `Sender.sendProduceRequests()` line 856
- **Transformation**: MemoryRecords → ProduceRequest protocol frames → TCP/Network
- **Mechanism**:
  - Batches are wrapped in `ProduceRequest` with partition/acks/timeout metadata
  - Request is serialized using Kafka protocol encoder
  - Sent to broker as byte stream over network connection
- **Files**:
  - `clients/src/main/java/org/apache/kafka/clients/producer/internals/Sender.java:856`
  - `org.apache.kafka.common.requests.ProduceRequest`
  - `org.apache.kafka.common.protocol.*` (protocol codec)

### 4. **Network → Broker RecordBatch (Broker-Side)**
- **Location**: `KafkaApis.handleProduceRequest()` line 389-429
- **Transformation**: ProduceRequest protocol frames → TopicPartition → MemoryRecords
- **Mechanism**:
  - Network layer decodes ProduceRequest
  - KafkaApis extracts records per partition
  - Records remain as MemoryRecords binary format
- **Files**:
  - `core/src/main/scala/kafka/server/KafkaApis.scala:389-429`
  - Protocol decoding in request handlers

### 5. **Broker Memory → Persistent Log Storage (Broker-Side)**
- **Location**: `UnifiedLog.appendAsLeaderWithRecordVersion()` line 1040-1042 in UnifiedLog.java
- **Transformation**: MemoryRecords (in-memory bytes) → log segment files on disk
- **Mechanism**:
  - `LogValidator` validates/converts record format if needed
  - Offset assignment (sequential offsets from log end offset)
  - Records written to current `LogSegment` in FileChannel
  - Index structures (offset index, timestamp index) updated in memory
  - Periodic flush to fsync log segment to disk
  - Log recovery on broker restart uses these persisted segments
- **Files**:
  - `storage/src/main/java/org/apache/kafka/storage/internals/log/UnifiedLog.java:104-1043`
  - `storage/src/main/java/org/apache/kafka/storage/internals/log/LogSegment.java:249-252`
  - Log files at: `<log.dir>/<topic>-<partition>/`

### 6. **Broker Log → FetchResponse (Broker to Consumer)**
- **Location**: `KafkaApis.handleFetchRequest()` line 627-650
- **Transformation**: Log storage (MemoryRecords) → FetchResponse protocol frames → TCP
- **Mechanism**:
  - ReplicaManager reads from log via offset/max bytes
  - Returns LogReadResult with MemoryRecords
  - FetchResponse encodes records with partition metadata
  - Serialized to network format
- **Files**:
  - `core/src/main/scala/kafka/server/KafkaApis.scala:555-650`
  - `core/src/main/scala/kafka/server/DelayedFetch.scala:50-73`
  - `org.apache.kafka.common.requests.FetchResponse`

### 7. **Network → Consumer RecordBatch (Consumer-Side)**
- **Location**: `Fetcher.handleFetchSuccess()` (in AbstractFetch)
- **Transformation**: FetchResponse protocol frames → CompletedFetch with MemoryRecords
- **Mechanism**:
  - Network layer decodes FetchResponse
  - Creates CompletedFetch per partition containing FetchResponseData.PartitionData
  - Records stored as MemoryRecords in FetchBuffer
- **Files**:
  - `clients/src/main/java/org/apache/kafka/clients/consumer/internals/Fetcher.java:184-199`
  - `clients/src/main/java/org/apache/kafka/clients/consumer/internals/CompletedFetch.java`

### 8. **RecordBatch → Deserialized ConsumerRecords (Consumer-Side)**
- **Location**: `FetchCollector.collectFetch()` line 92-147, particularly `FetchCollector.fetchRecords()` line 150-212
- **Transformation**: MemoryRecords (binary batches) → ConsumerRecord<K, V> objects with deserialized data
- **Mechanism**:
  1. Iterates RecordBatch objects in MemoryRecords
  2. For each Record in batch:
     - Extracts raw bytes for key and value
     - Applies key deserializer: `deserializers.keyDeserializer().deserialize(topic, headers, keyBytes)`
     - Applies value deserializer: `deserializers.valueDeserializer().deserialize(topic, headers, valueBytes)`
     - Creates ConsumerRecord with deserialized K, V objects
  3. Returns List<ConsumerRecord<K, V>>
- **Files**:
  - `clients/src/main/java/org/apache/kafka/clients/consumer/internals/FetchCollector.java:92-212`
  - `clients/src/main/java/org/apache/kafka/clients/consumer/ConsumerRecord.java`
  - Deserializers in: `org.apache.kafka.common.serialization.*`

### 9. **ConsumerRecord Objects → Application Code (Final Delivery)**
- **Location**: Consumer returns `ConsumerRecords<K, V>` from `poll(Duration timeout)`
- **Transformation**: ConsumerRecord objects → application-accessible data
- **Mechanism**:
  - Fetch returned to `KafkaConsumer` wrapper
  - Wrapped in `ConsumerRecords` collection
  - Application iterates records via `for (ConsumerRecord<K, V> record : records)` or `recordsByPartition(TopicPartition)`
- **Files**:
  - `clients/src/main/java/org/apache/kafka/clients/consumer/KafkaConsumer.java`
  - `clients/src/main/java/org/apache/kafka/clients/consumer/ConsumerRecords.java`

---

## Evidence

### Producer Flow Files
- `clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java:941-1045` - send() method and doSend() logic
- `clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java:68-400` - batching and append logic
- `clients/src/main/java/org/apache/kafka/clients/producer/internals/Sender.java:79-444` - send thread and network transmission
- `clients/src/main/java/org/apache/kafka/clients/producer/internals/ProducerBatch.java:60-300` - batch completion callbacks

### Broker Flow Files
- `core/src/main/scala/kafka/server/KafkaApis.scala:388-500` - produce request handling
- `core/src/main/scala/kafka/server/ReplicaManager.scala:627-750` - append coordination and replication
- `storage/src/main/java/org/apache/kafka/storage/internals/log/UnifiedLog.java:104-1043` - log storage
- `core/src/main/scala/kafka/server/DelayedProduce.scala:57` - replication wait handling
- `core/src/main/scala/kafka/cluster/Partition.scala:1330-1360` - partition append delegation

### Consumer Flow Files
- `clients/src/main/java/org/apache/kafka/clients/consumer/internals/Fetcher.java:59-200` - fetch request creation and sending
- `core/src/main/scala/kafka/server/KafkaApis.scala:555-650` - fetch request handling
- `core/src/main/scala/kafka/server/DelayedFetch.scala:50-73` - fetch delayed operation
- `clients/src/main/java/org/apache/kafka/clients/consumer/internals/FetchCollector.java:51-250` - record collection and deserialization
- `clients/src/main/java/org/apache/kafka/clients/consumer/internals/CompletedFetch.java` - fetch response container

### Key Components Referenced
- `org.apache.kafka.common.record.MemoryRecords` - in-memory binary record container
- `org.apache.kafka.common.record.MemoryRecordsBuilder` - builder for record batches
- `org.apache.kafka.common.record.RecordBatch` - individual batch metadata
- `org.apache.kafka.common.requests.ProduceRequest/ProduceResponse` - protocol messages
- `org.apache.kafka.common.requests.FetchRequest/FetchResponse` - protocol messages
- `org.apache.kafka.common.serialization.Serializer/Deserializer` - user-defined codec implementations
- `org.apache.kafka.clients.consumer.ConsumerRecord<K, V>` - final deserialized message format
