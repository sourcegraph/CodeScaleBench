# Apache Kafka Codebase Orientation

## 1. Build System and Broker Startup

### Build System

Apache Kafka 3.9.0 uses **Gradle** as its build system with multi-project structure:

- **Root build file**: `/workspace/build.gradle` (3,564 lines)
- **Build wrapper**: `./gradlew` (Gradle wrapper for environment consistency)
- **Project definition**: `/workspace/settings.gradle` (defines all modules)
- **Dependency management**: `/workspace/gradle/dependencies.gradle` (centralized dependency versions)

**Key Build Plugins:**
- Java Library plugin (Java/Scala mixed projects)
- Checkstyle (code style verification)
- SpotBugs (static code analysis)
- Jacoco (test coverage)
- Maven Publish (artifact publishing)
- Shadow (fat JAR creation for clients)
- Spotless (code formatting - Java 11+)
- Scoverage (Scala code coverage)
- Apache RAT (license header verification)

**Supported Versions:**
- Java: 8, 11, 17, 21 (Java 11+ preferred for broker)
- Scala: 2.12 and 2.13 (2.13 default)

### Broker Startup Entry Point

**Primary Entry Class**: `/workspace/core/src/main/scala/kafka/Kafka.scala`

This is the main Scala singleton object that serves as the broker's entry point. The main method accepts a server properties file and optional configuration overrides:

```
Usage: java kafka.Kafka server.properties [--override property=value]*
```

**Startup Flow:**

1. **Parse Arguments** - Loads the server.properties configuration file with optional command-line overrides
2. **Select Server Type** - Based on `process.roles` config:
   - **Legacy Mode**: Instantiates `KafkaServer` (ZooKeeper-based)
   - **Modern Mode**: Instantiates `KafkaRaftServer` (KRaft/embedded Raft consensus)
3. **Initialize Server** - Calls `server.startup()` to initialize broker components
4. **Run Server** - Calls `server.awaitShutdown()` to block and wait for termination
5. **Shutdown** - Calls `server.shutdown()` when termination signal received (SIGTERM/SIGINT)

### Key Classes Involved in Broker Initialization

#### **KafkaServer** (ZooKeeper Mode)
**File**: `/workspace/core/src/main/scala/kafka/server/KafkaServer.scala`

This is the legacy broker implementation for ZooKeeper-based clusters. During startup it initializes:

1. **Socket Server** - Network I/O handlers for client requests
   - Listener registration (PLAINTEXT, SSL, SASL)
   - Request handler pools (data plane, control plane)
   - Files: `/workspace/core/src/main/scala/kafka/network/SocketServer.scala`

2. **Log Manager** - Storage layer for topics and partitions
   - Log directory initialization and recovery
   - Log segment creation and management
   - Files: `/workspace/core/src/main/scala/kafka/log/LogManager.scala`

3. **Replica Manager** - Handles replication and leadership
   - Partition replica management
   - Leader/follower synchronization
   - Files: `/workspace/core/src/main/scala/kafka/server/ReplicaManager.scala`

4. **KafkaController** - Cluster state machine (if controller eligible)
   - Leader election
   - Partition assignment
   - Metadata management
   - Files: `/workspace/core/src/main/scala/kafka/controller/KafkaController.scala`

5. **Group Coordinator** - Consumer group management
   - Group metadata storage
   - Rebalance orchestration
   - Files: Located in `/workspace/group-coordinator`

6. **Transaction Coordinator** - Transaction state management
   - Transaction log management
   - Abort/commit coordination
   - Files: `/workspace/transaction-coordinator`

7. **Metrics Reporters** - Monitoring and metrics collection
   - JMX metrics registration
   - Custom metric reporters
   - Files: Metrics-related code in core and server modules

#### **KafkaRaftServer** (KRaft Mode)
**File**: `/workspace/core/src/main/scala/kafka/server/KafkaRaftServer.scala`

Modern broker implementation using embedded Raft consensus protocol. Differences from KafkaServer:

- No external ZooKeeper dependency
- Embedded Raft quorum for metadata storage
- Unified controller/broker roles
- Dynamic role assignment (broker, controller, or both)
- Metadata snapshots and checkpoints
- Files: `/workspace/metadata` and `/workspace/raft` modules contain KRaft-specific logic

#### **KafkaConfig**
**File**: `/workspace/core/src/main/scala/kafka/server/KafkaConfig.scala`

Extends `AbstractKafkaConfig` and provides:
- Type-safe access to all broker configuration parameters
- Getters for each configuration (e.g., `def numIoThreads`, `def logDirs`)
- Configuration validation at startup
- Synonym handling (e.g., `broker.id` vs `node.id` for compatibility)

### Configuration Defaults

**Default configuration locations:**
- ZooKeeper mode: `/workspace/config/server.properties`
- KRaft mode: `/workspace/config/kraft/server.properties`

---

## 2. Module Structure

Kafka is organized into a sophisticated multi-module architecture. Each module has clear responsibilities and dependencies:

### **Core Modules by Domain**

#### **clients** (`/workspace/clients`)
**Purpose**: Producer and Consumer client libraries and common utilities
**Responsibility**:
- Producer API for message publishing
- Consumer API for message consumption
- Metadata management and topic discovery
- Network communication protocols
- Common protocol definitions

**Key Classes**:
- `org.apache.kafka.clients.producer.KafkaProducer` - Producer implementation
- `org.apache.kafka.clients.consumer.KafkaConsumer` - Consumer implementation
- `org.apache.kafka.clients.admin.KafkaAdminClient` - Admin operations
- `org.apache.kafka.common.protocol.*` - Protocol definitions

#### **core** (`/workspace/core`)
**Purpose**: Broker implementation, log management, and coordination
**Responsibility**:
- Legacy ZooKeeper-based broker (`KafkaServer`)
- Log storage and management
- Replication and leadership
- Cluster control
- Request handling and routing

**Key Packages**:
- `kafka.server.*` - Server/broker implementation (~500+ files)
- `kafka.log.*` - Log storage, log cleaner, unified log
- `kafka.controller.*` - Cluster controller and state machine
- `kafka.coordinator.*` - Coordination services
- `kafka.network.*` - Network I/O and request handling
- `kafka.security.*` - Authentication and authorization
- `kafka.zk.*` - ZooKeeper integration

#### **metadata** (`/workspace/metadata`)
**Purpose**: Metadata management and KRaft controller
**Responsibility**:
- Metadata structures and snapshots
- KRaft consensus protocol metadata handling
- Controller state machine implementation
- Metadata changelog and replay
- Metadata image and deltas

**Key Packages**:
- `org.apache.kafka.metadata.*` - Metadata structures
- `org.apache.kafka.controller.*` - Modern KRaft-based controller

#### **raft** (`/workspace/raft`)
**Purpose**: Raft consensus protocol implementation
**Responsibility**:
- Raft log management
- Quorum leader election
- Replication and synchronization
- RPC protocol for Raft

**Key Classes**:
- `org.apache.kafka.raft.RaftClient` - Raft client interface
- `org.apache.kafka.raft.QuorumState` - Quorum state machine

#### **server** (`/workspace/server`)
**Purpose**: Modern Java-based server infrastructure (shared utilities)
**Responsibility**:
- Common server utilities and abstractions
- Configuration management utilities
- Server interfaces for Reconfigurable components

#### **server-common** (`/workspace/server-common`)
**Purpose**: Shared server utilities
**Responsibility**:
- Shared protocols and utilities between components
- Configuration structures

#### **storage** (`/workspace/storage`)
**Purpose**: Storage layer abstraction
**Responsibility**:
- Storage API definitions
- Log storage implementations
- Record batch operations

#### **group-coordinator** (`/workspace/group-coordinator`)
**Purpose**: Consumer group coordination
**Responsibility**:
- Consumer group state machine
- Group member management
- Rebalance coordination
- Static membership handling

#### **transaction-coordinator** (`/workspace/transaction-coordinator`)
**Purpose**: Transactional message coordination
**Responsibility**:
- Transaction state management
- Transaction log handling
- Abort/commit operations

#### **streams** (`/workspace/streams`)
**Purpose**: Kafka Streams topology processing library
**Responsibility**:
- Stream processing topology builder
- State store management
- Stream processing operations
- Exactly-once/at-least-once semantics

**Sub-modules**:
- `streams/core` - Core topology engine
- `streams/examples` - Example applications
- `streams/upgrade-system-tests` - Upgrade testing

#### **connect** (`/workspace/connect`)
**Purpose**: Kafka Connect distributed data integration framework
**Responsibility**:
- Connector plugin API
- Connector runtime (standalone and distributed)
- Source and sink connectors (file, S3, etc.)
- Data transformation plugins
- MirrorMaker 2.0 (cluster mirroring)

**Sub-modules**:
- `connect/api` - Plugin API
- `connect/runtime` - Connector runtime
- `connect/file` - File source/sink
- `connect/mirror` - MirrorMaker 2.0
- `connect/transforms` - Built-in transformations

#### **tools** (`/workspace/tools`)
**Purpose**: Command-line administrative and testing tools
**Responsibility**:
- Topic management (create, describe, delete)
- Consumer/Producer performance testing
- Replica verification
- Leadership election control
- Metadata quorum management

**Key Tools**:
- `TopicCommand` - Topic CRUD operations
- `ConsumerPerformance` - Consumer latency/throughput testing
- `ProducerPerformance` - Producer throughput testing
- `StreamsResetter` - Reset Kafka Streams state
- `TransactionsCommand` - Transaction management
- `MetadataQuorumCommand` - KRaft quorum control
- 15+ additional administrative tools

#### **trogdor** (`/workspace/trogdor`)
**Purpose**: Distributed workload generation and testing framework
**Responsibility**:
- Performance benchmarking
- Chaos engineering (fault injection)
- Cluster testing automation
- Histogram-based latency tracking
- Network partition simulation

#### **shell** (`/workspace/shell`)
**Purpose**: Interactive Kafka Shell interface
**Responsibility**:
- REPL-style interactive shell
- Quick cluster exploration

### **Module Dependency Graph**

```
Core (Broker)
├── depends on: Clients, Metadata, Raft, Storage, Group-Coordinator, Transaction-Coordinator
│
Streams
├── depends on: Clients
│
Connect
├── depends on: Clients
│
Tools
├── depends on: Clients, Core
│
Metadata
├── depends on: Raft, Server-Common
│
Raft
├── depends on: Server-Common
│
Clients (base layer)
├── depends on: nothing (foundation)
```

### **Cross-Cutting Concerns**

1. **Configuration** - Centralized in `/workspace/server/config/` and `/workspace/core/scala/server/`
2. **Metrics** - JMX metrics throughout all modules
3. **Security** - Authentication and authorization frameworks
4. **Logging** - log4j2-based logging with Kafka-specific appenders

---

## 3. Topic Creation Flow

Topic creation in Kafka is a complex, distributed operation ensuring durability and consistency across the cluster. Here's the complete end-to-end flow:

### **Phase 1: Client-Side Topic Creation**

**Entry Point**: `/workspace/tools/src/main/java/org/apache/kafka/tools/TopicCommand.java`

Client uses the Kafka Admin API to create a topic:

```
TopicCommand
  ↓
Admin.createTopics(NewTopic)
  ↓
AdminClient (org.apache.kafka.clients.admin.KafkaAdminClient)
  ↓
CreateTopicsRequest (protocol message)
  ↓
Broker Socket Server
```

### **Phase 2: Broker Request Handling**

**Request Handler**: `/workspace/core/src/main/scala/kafka/server/KafkaApis.scala` (lines 208, 2002-2098)

The broker's request handler routes CREATE_TOPICS requests:

1. **Authorization Check** - Validates client has CLUSTER or TOPIC CREATE permission
2. **Controller Routing** - Routes to active controller (may forward across network)
3. **Validation** - Filters internal topics, validates configuration

Key handler signature:
```scala
def handleCreateTopicsRequest(request: RequestChannel.Request): Unit
```

### **Phase 3: Admin Manager - Topic Creation Orchestration**

**Implementation**: `/workspace/core/src/main/scala/kafka/server/ZkAdminManager.scala` (lines 159-258)

The `createTopics` method performs the core creation logic:

1. **Validate topic doesn't exist** - Check metadata cache for existing topic
2. **Calculate replica assignments**:
   - If auto-assign: Uses `AdminUtils.assignReplicasToBrokers()` to distribute replicas across brokers
   - If manual: Validates provided replica assignments
3. **Validate configuration** - Checks topic config validity with validators
4. **Write to ZooKeeper** (if in ZK mode):
   - Path: `/config/topics/{topic-name}` - Topic configuration
   - Path: `/brokers/topics/{topic-name}` - Partition assignment
   - Path: `/brokers/topics/{topic-name}/partitions/{partition}/state` - Partition state

### **Phase 4: ZooKeeper Updates**

**Implementation**: `/workspace/core/src/main/scala/kafka/zk/AdminZkClient.scala` (lines 102-150)

```scala
def createTopicWithAssignment(topic: String,
                              config: Properties,
                              partitionReplicaAssignment: Map[Int, Seq[Int]],
                              validate: Boolean = true): Unit
```

This method:
1. Validates topic create policy
2. Stores topic configuration: `zkClient.setOrCreateEntityConfigs(ConfigType.TOPIC, topic, config)`
3. Creates partition assignment in ZK: `zkClient.createTopicAssignment(topic, topicId, assignment)`

**ZooKeeper paths created:**
- `/config/topics/{topic}` - Configuration properties
- `/brokers/topics/{topic}` - Replica assignment with broker IDs
- Topic ID stored in assignment metadata

### **Phase 5: Delayed Operation - Waiting for Leaders**

**Implementation**: `/workspace/core/src/main/scala/kafka/server/DelayedCreatePartitions.scala`

A `DelayedCreatePartitions` operation is queued to wait for leader election:

```scala
class DelayedCreatePartitions(delayMs: Long,
                              createMetadata: Seq[CreatePartitionsMetadata],
                              adminManager: ZkAdminManager,
                              responseCallback: Map[String, ApiError] => Unit)
```

This waits for:
- All partitions to have elected leaders
- OR timeout expires
- Checks condition periodically via `tryComplete()`: `missingLeaderCount(topic, partitions) == 0`

### **Phase 6: Controller Watches - Leader Election**

**Implementation**: `/workspace/core/src/main/scala/kafka/controller/KafkaController.scala`

When ZooKeeper watch triggers on `/brokers/topics/{topic}` change:

1. **Controller detects new topic** in topic list
2. **Selects leaders** - Usually first replica in assignment list
3. **Sends LeaderAndIsrRequest** to all brokers with partition state:
   ```
   Partition P → Leader: B0, ISR: [B0, B1, B2], Version: 1
   ```

### **Phase 7: Broker Partition Creation**

**Implementation**: `/workspace/core/src/main/scala/kafka/log/LogManager.scala` (lines 1033+)

When `LeaderAndIsrRequest` arrives, brokers create actual log storage:

```scala
def getOrCreateLog(topicPartition: TopicPartition,
                   isNew: Boolean = false,
                   topicId: Option[Uuid]): UnifiedLog
```

This method:

1. **Creates log directory** - `/log.dir/{topic}-{partition}/`
2. **Creates UnifiedLog instance** with:
   - Index files (`.index`, `.timeindex`)
   - Log segment files (`.log`)
   - Leader epoch cache (`.leader-epoch-checkpoint`)
   - Topic ID metadata
3. **Stores in LogManager cache** for future access

### **Phase 8: Replica Manager - Leadership Establishment**

**Implementation**: `/workspace/core/src/main/scala/kafka/server/ReplicaManager.scala`

```scala
def becomeLeaderOrFollower(correlationId: Int,
                           leaderAndIsrRequest: LeaderAndIsrRequest): LeaderAndIsrResponse
```

For each partition, the ReplicaManager:

1. **Become leader** - Create partition log, register as leader
2. **Become follower** - Create partition log, start replication from leader
3. **Reply to LeaderAndIsrRequest** with partition error codes

### **Phase 9: Controller Finalizes ISR**

**Implementation**: `/workspace/core/src/main/scala/kafka/controller/KafkaController.scala`

After brokers acknowledge leadership:

1. **Verify brokers created logs** via LeaderAndIsrRequest responses
2. **Update In-Sync Replicas (ISR)** in ZooKeeper at `/brokers/topics/{topic}/partitions/{partition}/state`
3. **Update leader epoch** to indicate stable state

### **Phase 10: Metadata Propagation**

**Implementation**: `/workspace/core/src/main/scala/kafka/server/MetadataCache.scala`

All brokers update their metadata cache:

1. **Watch fires** on ZooKeeper path changes
2. **Load new topic metadata** from ZK
3. **Update MetadataCache** with partition leaders and replicas
4. **Metadata fetch requests** return updated topic information to clients

### **Phase 11: Delayed Operation Completion**

Back in Phase 5's `DelayedCreatePartitions`:

1. **Condition check passes** - All partitions now have leaders
2. **Delete operation from purgatory** (delayed operation queue)
3. **Invoke responseCallback** with success
4. **Send CreateTopicsResponse** back to client

### **Complete Sequence Diagram**

```
Client (TopicCommand)
  │
  ├─── CreateTopicsRequest ──→ Broker (KafkaApis)
  │                              │
  │                              ├─── Check authorization
  │                              ├─── Route to controller
  │                              │
  │                              └─── ZkAdminManager.createTopics()
  │                                   │
  │                                   ├─── Validate topic
  │                                   ├─── Calculate replicas
  │                                   │
  │                                   └─── AdminZkClient.createTopicWithAssignment()
  │                                        │
  │                                        └─── Write to ZooKeeper:
  │                                             - /config/topics/{topic}
  │                                             - /brokers/topics/{topic}
  │                                        │
  │                                        └─── Queue DelayedCreatePartitions
  │                                             │
  │                                             └─→ KafkaController watches trigger
  │                                                  │
  │                                                  ├─── Detect new topic
  │                                                  ├─── Select leaders
  │                                                  │
  │                                                  └─── Send LeaderAndIsrRequest
  │                                                       │
  │                                                       ├─→ Each replica broker
  │                                                       │    │
  │                                                       │    ├─── LogManager.getOrCreateLog()
  │                                                       │    │    - Create /log.dir/{topic}-{partition}/
  │                                                       │    │    - Create index + log segment files
  │                                                       │    │
  │                                                       │    └─── ReplicaManager.becomeLeader/Follower()
  │                                                       │         - Register partition
  │                                                       │         - Update leader epoch
  │                                                       │         - Reply with ACK
  │                                                       │
  │                                                       └─── Controller updates ISR in ZK
  │                                                            - Update /brokers/topics/{topic}/partitions/{partition}/state
  │                                                            │
  │                                                            └─→ DelayedCreatePartitions.tryComplete()
  │                                                                 - All leaders elected ✓
  │                                                                 - Invoke responseCallback
  │
  └─── CreateTopicsResponse ←─ Client receives confirmation
```

### **Key Classes Summary**

| Component | File | Responsibility |
|-----------|------|-----------------|
| TopicCommand | tools/src/main/java/.../TopicCommand.java | CLI interface |
| CreateTopicsRequest/Response | clients/.../requests/CreateTopicsRequest.java | Protocol definition |
| KafkaApis | core/src/main/scala/kafka/server/KafkaApis.scala | Request routing (line 2002) |
| ZkAdminManager | core/src/main/scala/kafka/server/ZkAdminManager.scala | Core orchestration (line 159) |
| AdminZkClient | core/src/main/scala/kafka/zk/AdminZkClient.scala | ZK operations (line 102) |
| KafkaController | core/src/main/scala/kafka/controller/KafkaController.scala | Leader election |
| LogManager | core/src/main/scala/kafka/log/LogManager.scala | Log creation (line 1033) |
| ReplicaManager | core/src/main/scala/kafka/server/ReplicaManager.scala | Replica state management |
| DelayedCreatePartitions | core/src/main/scala/kafka/server/DelayedCreatePartitions.scala | Leader wait operation |

---

## 4. Testing Framework

Apache Kafka uses a sophisticated multi-layered testing framework combining unit testing, integration testing, property-based testing, and performance testing.

### **Unit Testing Framework**

**Primary Framework**: JUnit 5 (Jupiter)
- **Version**: 5.10.2
- **Location**: Core tests in `/workspace/core/src/test/scala` and `/workspace/clients/src/test/java`
- **File count**: 328 Scala unit tests, 135 Java unit tests

**Key Annotations**:
- `@Test` - Marks individual test methods
- `@BeforeEach` - Setup before each test
- `@AfterEach` - Teardown after each test
- `@ParameterizedTest` - Runs test with different parameters
- `@ValueSource` - Simple parameter values
- `@MethodSource` - Complex parameter objects
- `@Timeout` - Test timeout with thread mode control

**Example Unit Test Pattern** (from Scala):
```scala
class MyComponentTest {
  private val config = new KafkaConfig(TestUtils.createBrokerConfig(0, null))

  @BeforeEach
  def setUp(): Unit = {
    // initialization
  }

  @Test
  def testSomeFeature(): Unit = {
    // arrange
    val component = new MyComponent(config)

    // act
    val result = component.doSomething()

    // assert
    assertEquals(expected, result)
  }

  @AfterEach
  def tearDown(): Unit = {
    // cleanup
  }
}
```

### **Mocking Framework**

**Primary Framework**: Mockito
- **Version**: Varies by Java version (5.10.0 for Java 11+, 4.11.0 for earlier)
- **Integration**: `mockito-junit-jupiter` for JUnit 5 integration
- **Usage**: Static imports for assertions and mocking

**Mocking Pattern**:
```scala
val handlerMock = mock(classOf[RequestHandler])
when(handlerMock.handle(any())).thenReturn(response)
verify(handlerMock, times(1)).handle(argumentCaptor.capture())
```

### **Assertion Libraries**

- **Primary**: JUnit 5 built-in assertions (`assertEquals`, `assertTrue`, `assertThrows`)
- **Secondary**: Hamcrest matchers for advanced assertions
- **Usage**: Static imports for clean test code

### **Integration Testing Harness**

Apache Kafka provides sophisticated test harnesses for testing with actual broker clusters.

**Test Harness Hierarchy**:
```
QuorumTestHarness (ZK or KRaft setup)
  ↓
KafkaServerTestHarness (Broker lifecycle)
  ↓
IntegrationTestHarness (Client management)
  ↓
BaseProducerSendTest / BaseConsumerTest / BaseAdminIntegrationTest
```

**QuorumTestHarness** (`/workspace/core/src/test/scala/unit/kafka/integration/KafkaServerTestHarness.scala`):
- Sets up ZooKeeper or KRaft clusters
- Implements `@BeforeEach` and `@AfterEach` lifecycle
- Provides `isZKTest()`, `isKRaftTest()`, `isBrokerTest()` for conditional test logic
- Traits: `ZooKeeperQuorumImplementation`, `KRaftQuorumImplementation`

**KafkaServerTestHarness**:
- Manages broker lifecycle: `createBrokers()`, `shutdownServers()`
- Configuration generation: `generateConfigs(): Seq[KafkaConfig]`
- Helper methods: `bootstrapServers()`, `brokers: Buffer[KafkaBroker]`
- Security setup hooks: `configureSecurityBeforeServersStart()`, `configureSecurityAfterServersStart()`

**IntegrationTestHarness**:
- Manages producer/consumer/admin clients
- Properties: `producerConfig`, `consumerConfig`, `adminClientConfig`
- Client lifecycle: Maintains buffers of clients for cleanup
- Security support: Super user setup for security tests

**Example Integration Test**:
```scala
class ProducerIntegrationTest extends BaseProducerSendTest {
  @ParameterizedTest
  @ValueSource(strings = Array("zk", "kraft"))
  def testProducerSend(quorum: String): Unit = {
    val producerProps = new Properties()
    producerProps.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrapServers())
    val producer = registerProducer(new KafkaProducer(producerProps))

    val record = new ProducerRecord(topic, key, value)
    val future = producer.send(record)
    val metadata = future.get()

    assertEquals(0, metadata.partition())
  }
}
```

### **Test Utilities and Helpers**

**TestUtils** (`/workspace/clients/src/test/java/org/apache/kafka/test/TestUtils.java`):
- File operations: `tempDir()`, `tempFile()`
- Random data generation: `SEEDED_RANDOM`, `randomString()`, `randomBytes()`
- Cluster helpers: `singletonCluster()`, `createCluster()`
- Client creation: `createAdminClient()`, `createConsumer()`, `createProducer()`
- Polling: `waitForCondition(condition, timeout, message)`
- Message utilities: Request serialization, ByteBuffer operations

**Mock Objects**:
- `MockTime` - Controllable time for testing timeouts
- `MockSelector` - Network selector simulation
- `MockClient` - Admin client mocking
- `MockMetadataUpdater` - Metadata cache simulation
- `MockSerializer`, `MockDeserializer` - Data format testing
- `MockPartitioner` - Custom partition assignment
- Interceptor mocks: `MockConsumerInterceptor`, `MockProducerInterceptor`

**AdminClientUnitTestEnv** (`/workspace/clients/src/test/java/org/apache/kafka/clients/admin/AdminClientUnitTestEnv.java`):
```java
try (AdminClientUnitTestEnv env = new AdminClientUnitTestEnv(cluster)) {
    Admin admin = env.adminClient();
    // test admin operations
}
```

### **Test Patterns and Conventions**

**Naming Conventions**:
- Unit Tests: `*Test.scala` or `*Test.java`
- Integration Tests: `*IntegrationTest.scala` or `*IntegrationTest.java`
- Test methods: `test<Feature>()` pattern (e.g., `testProducerSend`)

**Setup/Teardown Pattern**:
```scala
@BeforeEach
override def setUp(testInfo: TestInfo): Unit = {
  super.setUp(testInfo)
  // setup code
}

@AfterEach
override def tearDown(): Unit = {
  TestUtils.shutdownServers(_brokers)
  super.tearDown()
}
```

**Parameterized Test Pattern**:
```scala
@ParameterizedTest
@ValueSource(strings = Array("plaintext", "ssl", "sasl"))
def testWithDifferentSecurityProtocols(protocol: String): Unit = {
  // runs once for each value
}
```

**Try-with-resources for Auto-cleanup**:
```java
try (AdminClientUnitTestEnv env = new AdminClientUnitTestEnv(cluster)) {
    Admin admin = env.adminClient();
    // test code - auto cleanup at end
}
```

**Mocking Pattern**:
```scala
val logManagerMock = mock(classOf[LogManager])
when(logManagerMock.liveLogDirs).thenReturn(Array(tmpDir))
verify(logManagerMock, times(2)).createLog(any(), any())
```

**Wait for Condition Pattern**:
```java
TestUtils.waitForCondition(
    () -> broker.logManager.logs.size() > 0,
    5000,
    "Log not created in time"
)
```

**Timeout Control**:
```scala
@Timeout(value = 15, unit = TimeUnit.SECONDS,
         threadMode = Timeout.ThreadMode.SEPARATE_THREAD)
def testLongRunning(): Unit = { }
```

### **Security Testing Support**

**Security Protocols Supported**:
- PLAINTEXT - No security
- SSL/TLS - Certificate-based encryption
- SASL - Multiple authentication mechanisms
  - PLAIN (username/password)
  - SCRAM (salted challenge response)
  - OAUTHBEARER (OAuth 2.0)
  - GSSAPI (Kerberos)

**Security Configuration Hooks** (in IntegrationTestHarness):
```scala
protected def securityProtocol: SecurityProtocol = SecurityProtocol.PLAINTEXT
protected def trustStoreFile: Option[File] = None
protected def serverSaslProperties: Option[Properties] = None
protected def clientSaslProperties: Option[Properties] = None
```

### **Performance and Load Testing - Trogdor**

**Framework**: Distributed workload generation and testing
**Location**: `/workspace/trogdor`

**Purpose**: Automated performance testing and chaos engineering
**Architecture**:
- Coordinator: Central task manager
- Agents: Run on cluster nodes
- Tasks: JSON specifications

**Task Types**:

1. **Workloads** (performance testing):
   - `ProduceBenchSpec` - Producer latency (p50, p95, p99 percentiles)
   - `ConsumeBenchSpec` - Consumer latency
   - `RoundTripWorkload` - End-to-end latency
   - `ConnectionStressSpec` - Connection pool testing

2. **Faults** (chaos engineering):
   - `ProcessStopFault` - SIGSTOP/SIGCONT signals
   - `NetworkPartitionFault` - Network isolation
   - `DegradedNetworkFault` - Latency/packet loss
   - `KiboshFault` - Disk I/O manipulation

**Example Task Specification**:
```json
{
  "class": "org.apache.kafka.trogdor.workload.ProduceBenchSpec",
  "startMs": 1000,
  "durationMs": 30000,
  "targetMessagesPerSec": 10000,
  "activeTopics": {
    "test-topic": {
      "numPartitions": 10,
      "replicationFactor": 3
    }
  }
}
```

### **Test Configuration and JVM Settings**

**JVM Settings** (from build.gradle):
```gradle
defaultMaxHeapSize = "2g"
defaultJvmArgs = ["-Xss4m", "-XX:+UseParallelGC"]
```

**Parallel Execution**:
- `maxParallelForks` - Parallel test execution
- `maxScalaacThreads` - Scala compiler threads
- Property-based testing: jqwik 1.8.3 for property-based tests

**Test Lifecycle Configuration**:
- `ignoreFailures` - Continue on test failure
- `maxTestRetries` - Flaky test retry limit
- `maxTestRetryFailures` - Max flaky test failures before stopping

### **Key Test Base Classes Reference**

| Class | Location | Purpose |
|-------|----------|---------|
| `QuorumTestHarness` | core/src/test/scala/.../KafkaServerTestHarness.scala | ZK or KRaft cluster setup |
| `KafkaServerTestHarness` | Same | Broker lifecycle management |
| `IntegrationTestHarness` | core/src/test/scala/integration/kafka/api/IntegrationTestHarness.scala | Client integration tests |
| `BaseProducerSendTest` | core/src/test/scala/integration/kafka/api/BaseProducerSendTest.scala | Producer tests |
| `AdminClientUnitTestEnv` | clients/src/test/java/.../AdminClientUnitTestEnv.java | Mock admin client |
| `TestUtils` | clients/src/test/java/org/apache/kafka/test/TestUtils.java | Utility helpers |

---

## 5. Configuration System

Apache Kafka has a sophisticated configuration system that supports static startup configuration, dynamic runtime updates, validation, and rich metadata for documentation and UI generation.

### **Configuration Registry Location**

**Primary Registry**: `/workspace/server/src/main/java/org/apache/kafka/server/config/AbstractKafkaConfig.java`

This class defines `CONFIG_DEF` which merges configuration definitions from multiple specialized classes:

```java
public static final ConfigDef CONFIG_DEF = Utils.mergeConfigs(Arrays.asList(
    RemoteLogManagerConfig.configDef(),
    ZkConfigs.CONFIG_DEF,
    ServerConfigs.CONFIG_DEF,           // General server configs
    KRaftConfigs.CONFIG_DEF,            // KRaft-specific configs
    SocketServerConfigs.CONFIG_DEF,     // Network configs
    ReplicationConfigs.CONFIG_DEF,      // Replication configs
    GroupCoordinatorConfig.configDef(), // Group coordination
    CleanerConfig.CONFIG_DEF,           // Log cleaner configs
    LogConfig.SERVER_CONFIG_DEF,        // Log retention/rolling
    TransactionLogConfigs.CONFIG_DEF,   // Transaction log
    QuorumConfig.CONFIG_DEF,            // Raft quorum
    MetricConfigs.CONFIG_DEF,           // Metrics
    QuotaConfigs.CONFIG_DEF,            // Resource quotas
    BrokerSecurityConfigs.CONFIG_DEF,   // Security
    DelegationTokenManagerConfigs.CONFIG_DEF,
    PasswordEncoderConfigs.CONFIG_DEF
));
```

### **Configuration Definition Pattern**

**ConfigDef Framework**: `/workspace/clients/src/main/java/org/apache/kafka/common/config/ConfigDef.java`

The `ConfigDef` class provides a fluent API for defining configurations:

```java
public class ConfigDef {
    public ConfigDef define(String name, Type type, Object defaultValue,
                           Validator validator, Importance importance,
                           String documentation)
}
```

**Example from ServerConfigs.java**:
```java
public static final String BROKER_ID_CONFIG = "broker.id";
public static final int BROKER_ID_DEFAULT = -1;
public static final String BROKER_ID_DOC = "The broker id for this server...";

public static final ConfigDef CONFIG_DEF = new ConfigDef()
    .define(BROKER_ID_CONFIG, INT, BROKER_ID_DEFAULT, HIGH, BROKER_ID_DOC)
    .define(NUM_IO_THREADS_CONFIG, INT, NUM_IO_THREADS_DEFAULT,
            atLeast(1), HIGH, NUM_IO_THREADS_DOC)
    .define(COMPRESSION_TYPE_CONFIG, STRING, DEFAULT_COMPRESSION_TYPE,
            ConfigDef.ValidString.in(BrokerCompressionType.names()),
            HIGH, COMPRESSION_TYPE_DOC);
```

### **Configuration Types**

| Type | Java Type | Example | Validator |
|------|-----------|---------|-----------|
| `INT` | Integer | 8, 9092 | `atLeast(1)`, `between(1, 100)` |
| `LONG` | Long | 3600000, 1073741824 | `atLeast(0)`, `between(0, 1000000)` |
| `STRING` | String | "plaintext", "/tmp/kafka" | `ValidString.in(options)`, `NonEmptyString` |
| `BOOLEAN` | Boolean | true, false | N/A (built-in validation) |
| `CLASS` | Class<?> | "org.example.MyClass" | `NonNullValidator` |
| `DOUBLE` | Double | 0.1, 1.5 | `Range.between()` |
| `LIST` | List<String> | "opt1,opt2,opt3" | `ListSize.atMostOfSize(5)` |
| `PASSWORD` | String | "secret123" | Sensitive (hidden in logs) |

### **Validators**

**Built-in Validator Classes** (in `ConfigDef`):

1. **Range Validators**:
   ```java
   import static org.apache.kafka.common.config.ConfigDef.Range.atLeast;

   .define(THREADS_CONFIG, INT, 10, atLeast(1), HIGH, "Thread count")
   .define(TIMEOUT_CONFIG, LONG, 5000, between(100, 600000), HIGH, "Timeout ms")
   ```

2. **String Validators**:
   ```java
   .define(COMPRESSION_TYPE, STRING, "snappy",
           ConfigDef.ValidString.in("none", "snappy", "lz4", "gzip", "zstd"),
           HIGH, "Compression type")

   .define(BROKER_RACK, STRING, null,
           ConfigDef.NonNullValidator(), MEDIUM, "Broker rack")
   ```

3. **List Validators**:
   ```java
   .define(LISTENERS, LIST, "PLAINTEXT://0.0.0.0:9092",
           ConfigDef.ListSize.atMostOfSize(10), HIGH, "Listeners")
   ```

4. **Custom Validators**:
   ```java
   .define(INTER_BROKER_PROTOCOL, STRING, "3.7-IV3",
           new MetadataVersionValidator(), MEDIUM, "Protocol version")
   ```

### **Validation Process**

**Validation happens in two places**:

1. **Startup Validation** (in `AbstractKafkaConfig` constructor):
   - Type parsing and conversion
   - Validator execution
   - Post-processing and re-validation
   - Error logging

2. **Dynamic Update Validation** (in `DynamicBrokerConfig.processReconfiguration()`):
   - Type validation
   - Reconfigurable component validation
   - BrokerReconfigurable validation hooks

### **Configuration Access**

**In KafkaConfig** (`/workspace/core/src/main/scala/kafka/server/KafkaConfig.scala`):

```scala
// Direct getters
def numIoThreads = getInt(ServerConfigs.NUM_IO_THREADS_CONFIG)
def logDirs = getList(ServerLogConfigs.LOG_DIRS_CONFIG).asScala.toSeq
def brokerRack = Option(getString(ServerConfigs.BROKER_RACK_CONFIG))
def zookeeperConnect = Option(getString(ZkConfigs.ZK_CONNECT_CONFIG))

// Helper methods
def getInt(configName: String): Int
def getLong(configName: String): Long
def getString(configName: String): String
def getBoolean(configName: String): Boolean
def getList(configName: String): java.util.List[String]
```

### **Dynamic Configuration Updates**

**Order of Precedence** (from `DynamicBrokerConfig`):
```
1. DYNAMIC_BROKER_CONFIG (/configs/brokers/{brokerId} in ZK)
2. DYNAMIC_DEFAULT_BROKER_CONFIG (/configs/brokers/<default> in ZK)
3. STATIC_BROKER_CONFIG (server.properties file)
4. DEFAULT_CONFIG (hardcoded defaults)
```

**Reconfigurable Components**:

Implement `Reconfigurable` or `BrokerReconfigurable` interface:

```scala
trait Reconfigurable {
    def reconfigurableConfigs(): java.util.Set[String]
    def validateReconfiguration(configs: java.util.Map[String, _]): Unit
    def reconfigure(configs: java.util.Map[String, _]): Unit
}

trait BrokerReconfigurable {
    def reconfigurableConfigs: Set[String]
    def validateReconfiguration(newConfig: KafkaConfig): Unit
    def reconfigure(oldConfig: KafkaConfig, newConfig: KafkaConfig): Unit
}
```

**DynamicBrokerConfig Handlers** (register in `addReconfigurables()`):
- `DynamicLogConfig` - Log configuration updates
- `DynamicListenerConfig` - Listener/SSL configuration
- `BrokerDynamicThreadPool` - Thread pool size updates
- `SocketServer` - Socket server configuration
- `DynamicClientQuotaCallback` - Quota updates
- `DynamicMetricsReporters` - Metrics reporter updates

### **Configuration Synonyms and Aliases**

Some configurations have multiple names for backwards compatibility:

**Example** (from `DynamicBrokerConfig`):
```scala
ServerLogConfigs.LOG_ROLL_TIME_MILLIS_CONFIG
  ↔ ServerLogConfigs.LOG_ROLL_TIME_HOURS_CONFIG

ServerLogConfigs.LOG_RETENTION_TIME_MILLIS_CONFIG
  ↔ ServerLogConfigs.LOG_RETENTION_TIME_MINUTES_CONFIG
  ↔ ServerLogConfigs.LOG_RETENTION_TIME_HOURS_CONFIG

ServerConfigs.BROKER_ID_CONFIG
  ↔ KRaftConfigs.NODE_ID_CONFIG (for KRaft compatibility)
```

**Listener-Specific Overrides**:
```
listener.name.{listenerName}.{configName}

Example: listener.name.PLAINTEXT.ssl.keystore.location
```

### **Configuration Metadata**

Each configuration has rich metadata:

```java
public static class ConfigKey {
    public final String name;              // e.g., "broker.id"
    public final Type type;                // e.g., Type.INT
    public final String documentation;    // Help text
    public final Object defaultValue;     // Default value
    public final Validator validator;     // Validation logic
    public final Importance importance;   // HIGH, MEDIUM, LOW
    public final String group;            // Configuration group
    public final int orderInGroup;        // UI order
    public final Width width;             // UI width
    public final String displayName;      // Display name
    public final List<String> dependents; // Dependent configs
    public final Recommender recommender; // Value suggestions
    public final boolean internal;        // Hidden/internal
}
```

### **Password Encryption for Dynamic Configs**

Dynamic passwords are encrypted using `PasswordEncoder`:

```scala
private def toPersistentProps(configProps: Properties): Properties = {
    val props = configProps.clone().asInstanceOf[Properties]

    configProps.asScala.forKeyValue { (name, value) =>
        if (isPasswordConfig(name))
            props.setProperty(name, passwordEncoder.encode(new Password(value)))
    }
    props
}
```

### **Configuration Files**

**ZooKeeper Mode** (`/workspace/config/server.properties`):
```properties
broker.id=0
listeners=PLAINTEXT://:9092
advertised.listeners=PLAINTEXT://your.host.name:9092
log.dirs=/tmp/kafka-logs
num.partitions=1
num.recovery.threads.per.data.dir=1
offsets.topic.replication.factor=1
zookeeper.connect=localhost:2181
group.initial.rebalance.delay.ms=0
```

**KRaft Mode** (`/workspace/config/kraft/server.properties`):
```properties
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@localhost:9093
listeners=PLAINTEXT://:9092,CONTROLLER://:9093
controller.listener.names=CONTROLLER
log.dirs=/tmp/kraft-combined-logs
```

---

## 6. Adding a New Broker Config

If you need to add a new broker configuration parameter, follow this step-by-step process:

### **Step 1: Define Configuration Constants**

**Choose appropriate config class** based on the parameter domain:

| Domain | File | Class |
|--------|------|-------|
| General server | `/workspace/server/src/main/java/org/apache/kafka/server/config/ServerConfigs.java` | `ServerConfigs` |
| Log/retention | `/workspace/server-common/src/main/java/org/apache/kafka/server/config/ServerLogConfigs.java` | `ServerLogConfigs` |
| Replication | `/workspace/server/src/main/java/org/apache/kafka/server/config/ReplicationConfigs.java` | `ReplicationConfigs` |
| Network/socket | `/workspace/core/src/main/scala/kafka/network/SocketServerConfigs.scala` | `SocketServerConfigs` |
| KRaft-specific | `/workspace/core/src/main/scala/kafka/server/KRaftConfigs.scala` | `KRaftConfigs` |
| Quotas | `/workspace/clients/src/main/java/org/apache/kafka/common/config/QuotaConfigs.java` | `QuotaConfigs` |

**Add three constants** in the chosen class:

```java
// Configuration name constant (follows kafka naming convention: all.lowercase.with.dots)
public static final String MY_NEW_CONFIG = "my.new.config";

// Default value constant
public static final int/String/boolean MY_NEW_CONFIG_DEFAULT = <value>;

// Documentation constant (human-readable description)
public static final String MY_NEW_CONFIG_DOC = "Description of this configuration parameter...";
```

**Example**:
```java
public static final String REPLICA_SOCKET_RECEIVE_BUFFER_BYTES_CONFIG = "replica.socket.receive.buffer.bytes";
public static final int REPLICA_SOCKET_RECEIVE_BUFFER_BYTES_DEFAULT = 65536;
public static final String REPLICA_SOCKET_RECEIVE_BUFFER_BYTES_DOC =
    "The socket receive buffer for network requests to the leader for replicating data";
```

### **Step 2: Add to ConfigDef**

In the same file, add a `.define()` call to the class's `CONFIG_DEF`:

**Basic Pattern**:
```java
.define(CONFIG_NAME, TYPE, DEFAULT_VALUE, [VALIDATOR], IMPORTANCE, DOCUMENTATION)
```

**With Validator**:
```java
import static org.apache.kafka.common.config.ConfigDef.Range.atLeast;
import static org.apache.kafka.common.config.ConfigDef.Range.between;

public static final ConfigDef CONFIG_DEF = new ConfigDef()
    // ... other configs ...
    .define(MY_NEW_CONFIG, INT, MY_NEW_CONFIG_DEFAULT,
            atLeast(0), HIGH, MY_NEW_CONFIG_DOC)
```

**Importance Levels**:
- `HIGH` - Critical configuration (must understand to run Kafka)
- `MEDIUM` - Important but optional
- `LOW` - Advanced tuning parameter

**Type Specification**:
```java
import org.apache.kafka.common.config.ConfigDef.Type;

Type.INT          // 32-bit integer
Type.LONG         // 64-bit integer
Type.STRING       // String value
Type.BOOLEAN      // Boolean value
Type.CLASS        // Java class name
Type.DOUBLE       // Floating-point
Type.LIST         // Comma-separated list
Type.PASSWORD     // Sensitive string (hidden in logs)
```

**Common Validator Examples**:
```java
// Integer with minimum
atLeast(1)

// Integer with range
between(1, 100)

// String with options
ConfigDef.ValidString.in("plaintext", "ssl", "sasl")

// Non-empty string
ConfigDef.NonEmptyString()

// Custom validator
new MyCustomValidator()
```

### **Step 3: Integrate with AbstractKafkaConfig**

In `/workspace/server/src/main/java/org/apache/kafka/server/config/AbstractKafkaConfig.java`:

**If using existing config class**: No action needed (already merged in line 45-68)

**If creating NEW config class**: Add to merge list:
```java
public static final ConfigDef CONFIG_DEF = Utils.mergeConfigs(Arrays.asList(
    RemoteLogManagerConfig.configDef(),
    ZkConfigs.CONFIG_DEF,
    ServerConfigs.CONFIG_DEF,
    MyNewConfigs.CONFIG_DEF,  // ← Add here if new class
    // ... rest of configs ...
));
```

### **Step 4: Create KafkaConfig Accessor**

Add a getter method in `/workspace/core/src/main/scala/kafka/server/KafkaConfig.scala`:

```scala
// For simple types
def myNewConfig = getInt(ServerConfigs.MY_NEW_CONFIG)
def myStringConfig = getString(MyConfigs.MY_STRING_CONFIG)
def myBooleanConfig = getBoolean(MyConfigs.MY_BOOLEAN_CONFIG)

// For nullable/optional configs
def optionalRack = Option(getString(ServerConfigs.BROKER_RACK_CONFIG))

// For list configs
def logDirs = getList(ServerLogConfigs.LOG_DIRS_CONFIG).asScala.toSeq
```

**Getter Methods Available**:
- `getInt(configName: String): Int`
- `getLong(configName: String): Long`
- `getString(configName: String): String`
- `getBoolean(configName: String): Boolean`
- `getList(configName: String): java.util.List[String]`
- `getDouble(configName: String): Double`

### **Step 5: Mark as Dynamic (if applicable)**

If the config can be updated **without broker restart**:

**Option A: Add to existing dynamic config set**

In `/workspace/core/src/main/scala/kafka/server/DynamicBrokerConfig.scala` (line 92-100):

```scala
val AllDynamicConfigs = DynamicSecurityConfigs ++
    LogCleaner.ReconfigurableConfigs ++
    DynamicLogConfig.ReconfigurableConfigs ++
    DynamicThreadPool.ReconfigurableConfigs ++
    Set(MetricConfigs.METRIC_REPORTER_CLASSES_CONFIG,
        MyConfigs.MY_NEW_CONFIG)  // ← Add here
    // ... rest ...
```

**Option B: Create specialized dynamic handler**

```scala
object DynamicMyConfig {
    val ReconfigurableConfigs = Set(MyConfigs.MY_NEW_CONFIG)

    def validateReconfiguration(currentConfig: KafkaConfig,
                               newConfig: KafkaConfig): Unit = {
        // Validation logic
        val newValue = newConfig.myNewConfig
        val oldValue = currentConfig.myNewConfig

        if (newValue < 0)
            throw new ConfigException("Value must be >= 0")
    }
}

class BrokerDynamicMyConfig(server: KafkaBroker) extends BrokerReconfigurable {
    override def reconfigurableConfigs: Set[String] =
        DynamicMyConfig.ReconfigurableConfigs

    override def validateReconfiguration(newConfig: KafkaConfig): Unit = {
        DynamicMyConfig.validateReconfiguration(server.config, newConfig)
    }

    override def reconfigure(oldConfig: KafkaConfig,
                            newConfig: KafkaConfig): Unit = {
        if (newConfig.myNewConfig != oldConfig.myNewConfig) {
            // Apply the configuration change
            server.someComponent.updateConfig(newConfig.myNewConfig)
        }
    }
}
```

### **Step 6: Register Reconfigurable Handler**

In `/workspace/core/src/main/scala/kafka/server/DynamicBrokerConfig.scala` (lines 260-275):

```scala
def addReconfigurables(kafkaServer: KafkaServer): Unit = {
    // ... existing registrations ...
    addBrokerReconfigurable(new BrokerDynamicMyConfig(kafkaServer))  // ← Add here
}
```

### **Step 7: Add Validation Logic**

Validation occurs in two phases:

**Static Validation** (at broker startup):

In `/workspace/core/src/main/scala/kafka/server/KafkaConfig.scala` (lines 855-1093):

```scala
def validateValues(): Unit = {
    // ... existing validations ...

    if (myNewConfig < 0)
        throw new ConfigException(s"my.new.config must be >= 0, got $myNewConfig")

    if (myNewConfig > maxValue)
        throw new ConfigException(s"my.new.config cannot exceed $maxValue")
}
```

**Dynamic Validation** (when updating via AdminClient):

In your `BrokerReconfigurable.validateReconfiguration()` method:

```scala
override def validateReconfiguration(newConfig: KafkaConfig): Unit = {
    val oldValue = server.config.myNewConfig
    val newValue = newConfig.myNewConfig

    // Check for invalid values
    if (newValue < 0)
        throw new ConfigException("my.new.config must be >= 0")

    // Check for incompatible changes
    if (newValue != oldValue && server.isRunning)
        throw new ConfigException("my.new.config cannot be changed after broker start")
}
```

### **Step 8: Write Tests**

**Unit Test** (in `/workspace/core/src/test/scala/unit/kafka/server/KafkaConfigTest.scala`):

```scala
@Test
def testMyNewConfigParsing(): Unit = {
    val props = TestUtils.createBrokerConfig(0, TestUtils.MockZkConnect)
    props.setProperty("my.new.config", "123")

    val config = KafkaConfig.fromProps(props)
    assertEquals(123, config.myNewConfig)
}

@Test
def testMyNewConfigValidation(): Unit = {
    val props = TestUtils.createBrokerConfig(0, TestUtils.MockZkConnect)
    props.setProperty("my.new.config", "-1")  // Invalid

    assertThrows(classOf[ConfigException], () => KafkaConfig.fromProps(props))
}
```

**Dynamic Update Test** (in `/workspace/core/src/test/scala/unit/kafka/server/DynamicBrokerConfigTest.scala`):

```scala
@Test
def testDynamicMyNewConfigUpdate(): Unit = {
    val origProps = TestUtils.createBrokerConfig(0, null, port = 8181)
    origProps.put("my.new.config", "100")

    val config = KafkaConfig(origProps)
    val serverMock = Mockito.mock(classOf[KafkaBroker])
    Mockito.when(serverMock.config).thenReturn(config)

    config.dynamicConfig.initialize(None, None)
    config.dynamicConfig.addBrokerReconfigurable(new BrokerDynamicMyConfig(serverMock))

    val updateProps = new Properties()
    updateProps.put("my.new.config", "200")
    config.dynamicConfig.updateDefaultConfig(updateProps)

    assertEquals(200, config.myNewConfig)
}
```

### **Step 9: Test End-to-End**

Run tests to verify configuration works:

```bash
# Test configuration parsing
./gradlew :core:test --tests "*KafkaConfigTest*"

# Test dynamic configuration
./gradlew :core:test --tests "*DynamicBrokerConfigTest*"

# Broader test to ensure nothing broke
./gradlew :core:test
```

### **Configuration Precedence Summary**

When your config is accessed, these sources are checked in order:

1. **Dynamic broker-specific** (ZK `/configs/brokers/{brokerId}`)
2. **Dynamic cluster-level default** (ZK `/configs/brokers/<default>`)
3. **Static configuration** (server.properties)
4. **Hardcoded default** (CONFIG_DEF default value)

### **Important Patterns**

**Per-Broker vs Cluster-Level**:
```scala
// Per-broker configs (only set at specific broker, not default)
private val PerBrokerConfigs = Set(
    ServerConfigs.NUM_IO_THREADS_CONFIG,
    // Other per-broker configs
)

// Cluster-level configs (can be set at default level)
private val ClusterLevelConfigs = Set(
    SocketServerConfigs.MAX_CONNECTIONS_CONFIG,
    // Other cluster-level configs
)
```

**Password Config Handling**:
```scala
private def isPasswordConfig(name: String): Boolean = {
    name.endsWith(".password") ||
    name.endsWith(".secret") ||
    name == "my.secret.config"  // Add your password config here
}
```

**Listener Overrides**:
```
listener.name.PLAINTEXT.my.new.config=value
listener.name.SSL.my.new.config=value
```

### **Checklist for Adding New Config**

- [ ] Define constants (NAME, DEFAULT, DOC) in appropriate config class
- [ ] Add `.define()` entry to ConfigDef with type, default, validator, importance
- [ ] Verify ConfigDef is merged in AbstractKafkaConfig
- [ ] Add getter method in KafkaConfig.scala
- [ ] Add validation logic in `validateValues()` if static validation needed
- [ ] If dynamic: add to AllDynamicConfigs or create BrokerReconfigurable handler
- [ ] If dynamic: register handler in `addReconfigurables()`
- [ ] Write unit tests for static parsing and validation
- [ ] Write unit tests for dynamic reconfiguration (if applicable)
- [ ] Run integration tests to verify config works end-to-end
- [ ] Document config in KIP (Kafka Improvement Proposal) for new configs

---

## Summary

This orientation document covers the essential components of Apache Kafka's architecture:

1. **Build & Startup**: Gradle-based build system with two broker implementations (ZooKeeper and KRaft modes)
2. **Modules**: 15+ specialized modules with clear separation of concerns
3. **Topic Creation**: Complex distributed flow involving ZooKeeper coordination, leader election, and log creation
4. **Testing**: Comprehensive testing framework with unit, integration, parameterized, and performance testing
5. **Configuration**: Sophisticated system supporting static and dynamic configurations with validation
6. **Config Addition**: Clear process following established patterns throughout the codebase

The codebase demonstrates sophisticated architectural patterns including:
- Clear module boundaries with explicit dependencies
- Extensive use of base classes and traits for common functionality
- Comprehensive validation at multiple levels
- Support for dynamic reconfiguration without downtime
- Extensive test coverage with multiple testing strategies
- Rich configuration metadata for documentation and tooling
