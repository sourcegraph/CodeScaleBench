# Apache Kafka Codebase Orientation

## 1. Build System and Broker Startup

### Build System

**Build Tool:** Gradle 8.8

**Key Build Files:**
- `/workspace/build.gradle` - Root build configuration (primary configuration file)
- `/workspace/settings.gradle` - Module definitions and project structure
- `/workspace/gradle/dependencies.gradle` - Centralized dependency management
- `/workspace/gradle-wrapper.properties` - Gradle wrapper version specification

**Gradle Configuration Highlights:**
- Supports Scala 2.12 (deprecated) and Scala 2.13 (default)
- Java version support: Java 8, 11, 17, 21 (Java 8/11 are deprecated for 3.7+)
- Custom Gradle plugins for: Spotbugs (static analysis), Scoverage (Scala code coverage), Shadow JAR (fat JARs), Spotless (code formatting), OWASP Dependency Check, Apache Rat (license compliance)
- Gradle Enterprise integration for build scanning
- Organized into 30+ subprojects with clear module hierarchy

**Build Commands:**
```bash
./gradlew build                    # Full build
./gradlew core:build              # Build specific module
./gradlew core:test               # Run tests for module
./gradlew spotlessApply           # Format code
./gradlew assembleDist            # Create distribution tarball
```

---

### Broker Startup

**Main Entry Point:** `/workspace/core/src/main/scala/kafka/Kafka.scala`

**Entry Point Details:**
```scala
// Main method bootstraps the broker
object Kafka {
  def main(args: Array[String]): Unit = {
    // Parses command-line arguments
    // Creates KafkaConfig from properties
    // Instantiates either KafkaServer (ZK-based) or KafkaRaftServer (KRaft mode)
    // Registers shutdown hooks for graceful shutdown
  }
}
```

**Startup Script:** `/workspace/bin/kafka-server-start.sh`
- Wrapper script that calls `kafka-run-class.sh`
- Loads `server.properties` configuration file
- Sets JVM options (default: `-Xmx1G -Xms1G`)
- Executes: `kafka-run-class.sh kafka.Kafka "$@"`

---

### Key Classes Involved in Broker Initialization

**1. KafkaServer (ZooKeeper-based broker)**
- **File:** `/workspace/core/src/main/scala/kafka/server/KafkaServer.scala` (~2000 lines)
- **Purpose:** Main broker implementation for classic ZooKeeper-coordinated clusters
- **Responsibilities:**
  - Broker metadata initialization (ID, rack, listeners)
  - Request channel and socket server setup
  - API version management and request routing
  - Replica manager initialization for log replication
  - Coordinator manager setup (consumer groups, transactions)
  - ZooKeeper client initialization and cluster metadata sync
  - Graceful shutdown coordination
- **Key Initialization Methods:**
  - `startup()` - Performs broker startup sequence
  - `awaitShutdown()` - Blocks until shutdown signal
  - `shutdown()` - Graceful shutdown with timeout

**2. KafkaRaftServer (KRaft mode broker)**
- **File:** `/workspace/core/src/main/scala/kafka/server/KafkaRaftServer.scala`
- **Purpose:** KRaft-mode broker implementation (KIP-500 - removing ZooKeeper dependency)
- **Features:**
  - Built-in metadata quorum coordination
  - No external ZooKeeper dependency
  - Uses embedded Raft consensus protocol

**3. KafkaConfig (Configuration Manager)**
- **File:** `/workspace/core/src/main/scala/kafka/server/KafkaConfig.scala` (~800 lines)
- **Purpose:** Configuration parsing, validation, and management
- **Key Methods:**
  - `fromProps(props: Properties): KafkaConfig` - Parse properties into config object
  - `configDef: ConfigDef` - Central configuration definition registry
  - Provides type-safe access to all broker configuration values
- **Config Sources (precedence order):**
  1. Dynamic broker-specific configs (ZK: `/configs/brokers/{brokerId}`)
  2. Dynamic cluster-wide defaults (ZK: `/configs/brokers/<default>`)
  3. Static broker config (server.properties file)
  4. Default values defined in KafkaConfig

**4. SocketServer (Network I/O)**
- **File:** `/workspace/core/src/main/scala/kafka/network/SocketServer.scala`
- **Purpose:** Manages network listeners and client connections
- **Responsibilities:**
  - Creates and manages listening sockets for each configured listener (PLAINTEXT, SSL, SASL_PLAINTEXT, etc.)
  - Accepts incoming client connections
  - Coordinates with RequestChannel for request/response handling

**5. RequestChannel (Request Dispatcher)**
- **File:** `/workspace/core/src/main/scala/kafka/network/RequestChannel.scala`
- **Purpose:** Async request/response queue for decoupled request handling
- **Features:**
  - Buffers requests from network layer
  - Routes responses back to clients
  - Supports request priority and quota enforcement

**6. KafkaRequestHandler (Request Processing Threads)**
- **File:** `/workspace/core/src/main/scala/kafka/server/KafkaRequestHandler.scala` (194 lines)
- **Purpose:** Worker threads that process requests
- **Structure:**
  - `KafkaRequestHandlerPool` - Thread pool manager
  - `KafkaRequestHandler` - Individual worker thread (extends Runnable)
  - Configurable thread count via `num.io.threads` (default: 8)

**7. KafkaApis (Request Handler Dispatcher)**
- **File:** `/workspace/core/src/main/scala/kafka/server/KafkaApis.scala` (4,143 lines)
- **Purpose:** Main request dispatcher routing to specific API implementations
- **Structure:**
  - Implements `ApiRequestHandler` trait
  - Contains 30+ handler methods for different request types
  - Routes requests to appropriate handlers based on API key

**8. ReplicaManager (Log Replication)**
- **File:** `/workspace/core/src/main/scala/kafka/server/ReplicaManager.scala`
- **Purpose:** Manages log replication and in-sync replica tracking
- **Responsibilities:**
  - Leader/follower replica coordination
  - Produce and fetch request handling
  - ISR (in-sync replicas) management

---

### Startup Sequence

```
1. kafka-server-start.sh invoked
   ↓
2. Kafka.main(args) executed
   ↓
3. KafkaConfig.fromProps(properties) - Parses config
   ↓
4. buildServer() - Instantiates KafkaServer or KafkaRaftServer
   ↓
5. server.startup() - Broker initialization:
   - SocketServer.startup() - Open network listeners
   - RequestChannel initialization
   - KafkaRequestHandlerPool creation
   - ReplicaManager initialization
   - Coordinator managers (consumer groups, transactions)
   - ZooKeeper client connection (if ZK mode)
   - Metadata sync with cluster
   ↓
6. server.awaitShutdown() - Blocks waiting for shutdown signal
   ↓
7. On SIGTERM/SIGINT:
   - server.shutdown()
   - Graceful shutdown of components
   - Final ZK cleanup (if applicable)
```

---

## 2. Module Structure

Apache Kafka is organized into 30+ modules, organized in `/workspace/settings.gradle`:

### Core Broker Modules

| Module | Location | Lines | Responsibilities |
|--------|----------|-------|-------------------|
| **core** | `/workspace/core` | 30K+ | Main broker implementation, APIs, replication, log management, controller logic |
| **server** | `/workspace/server` | 8K | Server-side utilities and abstractions (Java-based configs, utils) |
| **server-common** | `/workspace/server-common` | 5K | Shared server configuration classes (Configs, ConfigDef) |
| **raft** | `/workspace/raft` | 12K | KRaft consensus implementation for KIP-500 metadata quorum |
| **storage** | `/workspace/storage` | 15K | Log storage, segment management, record codec, remote storage |
| **metadata** | `/workspace/metadata` | 8K | Metadata image and cache management, metadata version handling |

### Coordination and Management Modules

| Module | Location | Responsibilities |
|--------|----------|-------------------|
| **group-coordinator** | `/workspace/group-coordinator` | Consumer group coordination and offset management |
| **transaction-coordinator** | `/workspace/transaction-coordinator` | Transaction coordination for exactly-once semantics |

### Client Modules

| Module | Location | Responsibilities |
|--------|----------|-------------------|
| **clients** | `/workspace/clients` | Java client libraries: Producer, Consumer, Admin Client |

### Integration and Extension Modules

| Module | Location | Responsibilities |
|--------|----------|-------------------|
| **connect** | `/workspace/connect` | Kafka Connect framework (10+ sub-modules) for data pipeline integration |
| **streams** | `/workspace/streams` | Kafka Streams DSL and topology for stream processing (multiple sub-modules) |
| **tools** | `/workspace/tools` | Administrative tools (topic mgmt, ACL mgmt, config management) |

### Auxiliary Modules

| Module | Location | Responsibilities |
|--------|----------|-------------------|
| **log4j-appender** | `/workspace/log4j-appender` | Log4J integration for Kafka logging |
| **trogdor** | `/workspace/trogdor` | Performance testing framework and fault injection |
| **jmh-benchmarks** | `/workspace/jmh-benchmarks` | JMH microbenchmarks for performance measurement |
| **shell** | `/workspace/shell` | Interactive broker shell (REPL-like interface) |
| **examples** | `/workspace/examples` | Code examples for producers, consumers, streams |
| **generator** | `/workspace/generator` | Protocol message code generation (proto -> Java) |
| **tests** | `/workspace/tests` | System-level integration tests |

### Language Distribution

- **Scala:** Core broker logic (kafka/server/* packages, most of core module)
- **Java:** Client libraries, utilities, configuration, newer code
- **Mixed:** Most modules contain both languages, gradual Java migration underway

---

### Module Dependencies

```
clients
  ↓
core (depends on clients)
  ├→ server (depends on clients)
  ├→ storage (log management)
  ├→ raft (KRaft consensus)
  ├→ metadata (metadata handling)
  ├→ group-coordinator
  └→ transaction-coordinator

streams (depends on clients)
connect (depends on clients)
tools (depends on clients and core)
```

---

## 3. Topic Creation Flow

### High-Level Overview

Topic creation follows this path:
```
Client (CreateTopicsRequest)
  ↓
Broker Network Layer
  ↓
RequestChannel (queue)
  ↓
KafkaRequestHandler (worker thread)
  ↓
KafkaApis.handleCreateTopicsRequest()
  ↓
[ZK Mode] ZkAdminManager.createTopics()
or
[KRaft Mode] ControllerApis.createTopics()
  ↓
Topic metadata update & storage
  ↓
CreateTopicsResponse sent back to client
```

---

### Detailed Request Handler Path

**1. Network Reception (SocketServer)**
- **File:** `/workspace/core/src/main/scala/kafka/network/SocketServer.scala`
- Client sends CreateTopicsRequest via one of the configured listeners
- SocketServer's NetworkReceiver thread reads from socket

**2. Request Queuing (RequestChannel)**
- **File:** `/workspace/core/src/main/scala/kafka/network/RequestChannel.scala`
- Request wrapped in `RequestChannel.Request` object containing:
  - Raw bytes
  - Client information
  - Source listener
  - Callback for response sending
- Request enqueued to shared queue

**3. Worker Thread Processing (KafkaRequestHandler)**
- **File:** `/workspace/core/src/main/scala/kafka/server/KafkaRequestHandler.scala`
- Thread pool (`KafkaRequestHandlerPool`) with configurable size (`num.io.threads`)
- Each worker thread:
  - Dequeues request from RequestChannel
  - Invokes `handler.handle(request)`
  - Metric tracking (request latency, throughput)

**4. Request Dispatch (KafkaApis)**
- **File:** `/workspace/core/src/main/scala/kafka/server/KafkaApis.scala` (lines 1-200 contain dispatcher logic)
- Router determines API type from request header
- Routes to specific handler method: `handleCreateTopicsRequest(request)`

---

### CreateTopics Request Handling

**Handler Method:**
```scala
// kafka/server/KafkaApis.scala
def handleCreateTopicsRequest(request: RequestChannel.Request): Unit = {
  val createTopicsRequest = request.body[CreateTopicsRequest]
  val results = new CreatableTopicResultCollection(...)

  // 1. Extract quota for request
  val controllerMutationQuota = quotas.controllerMutation.newQuotaFor(request)

  // 2. Define response callback
  def sendResponseCallback(results: CreatableTopicResultCollection): Unit = {
    val response = new CreateTopicsResponse(new CreateTopicsResponseData()
      .setResults(results)
      .setThrottleTimeMs(...))
    requestHelper.sendResponseMaybeThrottleWithControllerQuota(
      request, response, controllerMutationQuota)
  }

  // 3. Validate each topic in request
  for (topic in createTopicsRequest.topics()) {
    // Validate topic name (no reserved names, valid characters)
    // Validate replication factor
    // Validate partition count
  }

  // 4. Route to appropriate handler
  if (zkSupport.isPresent) {
    // ZK mode: synchronous via ZkAdminManager
    zkSupport.get.adminManager.createTopics(timeout, results, ...)
  } else {
    // KRaft mode: async via controller RPC
    controller.createTopics(request, results, sendResponseCallback)
  }
}
```

---

### ZooKeeper Mode Topic Creation

**Class:** `/workspace/core/src/main/scala/kafka/server/ZkAdminManager.scala`

**Method:** `createTopics(timeout, results, ...)`

**Process:**
1. **Validation:**
   - Check if topic already exists in ZK
   - Validate configuration parameters
   - Check broker availability for replication

2. **Assignment:**
   - Calculate replica assignment using `AdminUtils.assignReplicasToBrokers(...)`
   - Consider broker rack information if configured
   - Ensure proper distribution across brokers

3. **ZK Updates:**
   - Write topic metadata to ZK: `/brokers/topics/{topic}`
   - Write partition metadata: `/brokers/topics/{topic}/partitions/{partition}`
   - Write configuration: `/config/topics/{topic}`

4. **Broker Notification:**
   - Brokers watch ZK paths and detect topic creation
   - Trigger ReplicaManager to create log directories
   - Leader election for new partitions

5. **Response:**
   - Update results with success or error codes
   - Send CreateTopicsResponse back to client

---

### KRaft Mode Topic Creation

**Class:** `/workspace/core/src/main/scala/kafka/server/ControllerApis.scala`

**Method:** `createTopics(request, results, sendResponseCallback)`

**Process:**
1. **Metadata Log Entry:**
   - Controller writes topic creation command to metadata log (Raft-replicated)
   - Topic UUID generated
   - Partition replica assignments created

2. **State Machine Update:**
   - Metadata state machine processes log entries
   - Maintains in-memory metadata image
   - Publishes updates to all brokers

3. **Broker Coordination:**
   - Brokers subscribe to metadata updates
   - Detect new topic partition assignments
   - Create replicas locally

4. **Response:**
   - Callback triggered when metadata applied
   - CreateTopicsResponse sent with results

---

### Key Classes and Methods Summary

| Class | File | Method | Purpose |
|-------|------|--------|---------|
| **KafkaApis** | core/.../KafkaApis.scala | `handleCreateTopicsRequest()` | Main entry point for request handling |
| **ZkAdminManager** | core/.../ZkAdminManager.scala | `createTopics()` | ZK-mode topic creation logic |
| **ControllerApis** | core/.../ControllerApis.scala | `createTopics()` | KRaft-mode topic creation |
| **AdminUtils** | core/.../AdminUtils.scala | `assignReplicasToBrokers()` | Replica assignment algorithm |
| **ReplicaManager** | core/.../ReplicaManager.scala | `makeFollowers()`, `makeLeaders()` | Replica creation and leadership |
| **RequestHelper** | core/.../RequestHelper.scala | `sendResponseMaybeThrottleWithControllerQuota()` | Response sending with quota |

---

### Request/Response Protocol

**CreateTopicsRequest (from client):**
```
CreateTopicsRequest {
  topic1: {
    numPartitions: 3,
    replicationFactor: 2,
    configs: {
      "compression.type": "snappy",
      "min.insync.replicas": "2"
    }
  }
  ...
}
```

**CreateTopicsResponse (to client):**
```
CreateTopicsResponse {
  throttleTimeMs: 0,
  results: [
    {
      name: "topic1",
      topicId: <UUID>,
      errorCode: 0,  // 0 = success, other = error code
      errorMessage: null
    }
  ]
}
```

---

## 4. Testing Framework

### Test Frameworks and Tools

**Primary Frameworks:**
- **JUnit 5 (Jupiter)** - Standard unit and integration test runner
- **ScalaTest** - Scala test framework (FlatSpec, BeforeAndAfterEach traits)
- **Mockito** - Object mocking (version 4.9 for Scala 2.12, 5.x for 2.13+)
- **JMH** - Java Microbenchmarks for performance testing

**Gradle Configuration:**
```gradle
useJUnitPlatform {
  includeEngines 'junit-jupiter'
}
testCompile('org.scalatest:scalatest_2.13:3.2.x')
testCompile('org.mockito:mockito-core:5.x')
```

---

### Test Directory Structure

```
/workspace/core/src/test/
├── scala/
│   ├── unit/kafka/
│   │   ├── server/              (40+ server unit tests)
│   │   │   ├── KafkaConfigTest.scala
│   │   │   ├── ControllerApisTest.scala
│   │   │   ├── FetchRequestTest.scala
│   │   │   ├── ProduceRequestTest.scala
│   │   │   └── ...
│   │   ├── log/                 (Log unit tests)
│   │   ├── controller/          (Controller unit tests)
│   │   ├── network/             (Network unit tests)
│   │   └── ...
│   └── integration/kafka/
│       ├── server/              (Multi-broker integration tests)
│       │   ├── DynamicBrokerReconfigurationTest.scala
│       │   ├── KRaftClusterTest.scala
│       │   ├── MetadataVersionIntegrationTest.scala
│       │   └── ...
│       ├── cluster/             (Full cluster tests)
│       ├── api/                 (API integration tests)
│       │   ├── ConsumerTopicCreationTest.scala
│       │   ├── RackAwareAutoTopicCreationTest.scala
│       │   └── ...
│       └── ...
├── java/
│   └── kafka/test/              (Test utilities and helpers)
│       ├── ApiUtils.java
│       ├── MockController.java
│       ├── ClusterInstance.java
│       └── ...
└── resources/                   (Test configuration files)
    ├── server.properties
    ├── log4j.properties
    └── ...
```

---

### Unit Test Examples

**File:** `/workspace/core/src/test/scala/unit/kafka/server/KafkaConfigTest.scala`

**Purpose:** Test configuration parsing and validation

**Pattern:**
```scala
class KafkaConfigTest extends AnyFlatSpec with BeforeAndAfterEach {
  override def beforeEach(): Unit = {
    // Setup
  }

  "KafkaConfig" should "parse valid properties" in {
    val props = new Properties()
    props.put("broker.id", "1")
    props.put("log.dirs", "/var/log/kafka")

    val config = KafkaConfig.fromProps(props)

    assert(config.brokerId == 1)
    assert(config.logDirs.contains("/var/log/kafka"))
  }

  it should "reject invalid broker.id" in {
    val props = new Properties()
    props.put("broker.id", "-1")

    assertThrows[ConfigException] {
      KafkaConfig.fromProps(props)
    }
  }
}
```

**File:** `/workspace/core/src/test/scala/unit/kafka/server/ControllerApisTest.scala`

**Purpose:** Test controller API request handlers

**Key Testing Patterns:**
```scala
class ControllerApisTest {

  // Mock quota factory
  case class MockControllerMutationQuota(quota: Int) extends ControllerMutationQuota {
    var permitsRecorded = 0.0
    override def isExceeded: Boolean = permitsRecorded > quota
    override def record(permits: Double): Unit = permitsRecorded += permits
  }

  @Test
  def testCreateTopicsWithQuotaExceeded(): Unit = {
    // Create mock request
    val createTopicsRequest = new CreateTopicsRequest.Builder(
      new CreateTopicsRequestData()
        .setTopics(new CreatableTopicCollection(...))
    ).build()

    val request = createMockRequest(createTopicsRequest)

    // Create handler with mock quota
    val quota = MockControllerMutationQuota(quota = 100)
    val handler = new ControllerApis(...)

    // Handle request
    handler.handleCreateTopicsRequest(request)

    // Verify response
    val response = captureResponse()
    assertEquals(Errors.THROTTLED_QUOTA_EXCEEDED, response.errorCode())
  }
}
```

---

### Integration Test Examples

**File:** `/workspace/core/src/test/scala/integration/kafka/server/DynamicBrokerReconfigurationTest.scala`

**Purpose:** Test dynamic broker configuration updates

**Test Harness:**
```scala
class DynamicBrokerReconfigurationTest extends KafkaServerTestHarness {
  override def brokerCount: Int = 3

  @Test
  def testDynamicConfigUpdate(): Unit = {
    // Cluster starts with 3 brokers (automatic via KafkaServerTestHarness)

    // Update broker config dynamically
    alterBrokerConfigs("0", new Properties() {
      put(ServerConfigs.LOG_RETENTION_HOURS_CONFIG, "24")
    })

    // Verify change took effect
    val config = brokers(0).config
    assertEquals(24 * 60 * 60 * 1000, config.logRetentionMs)
  }
}
```

**Base Class:** `/workspace/core/src/test/scala/kafka/integration/KafkaServerTestHarness.scala`

**Features:**
- Automatic multi-broker cluster startup/shutdown
- Methods: `brokers()`, `createTopic()`, `adminClient`
- Fixture management with `beforeEach()`, `afterEach()`
- Helper methods for common operations

---

### KRaft Integration Tests

**File:** `/workspace/core/src/test/scala/integration/kafka/server/KRaftClusterTest.scala`

**Test Harness:** `/workspace/core/src/test/scala/integration/kafka/server/QuorumTestHarness.scala`

**KRaft-Specific Features:**
```scala
class MyKRaftTest extends QuorumTestHarness {
  override def controllers: Int = 1  // Controller count
  override def brokers: Int = 3      // Broker count

  // Cluster runs in KRaft mode automatically
}
```

---

### Test Utilities

**File:** `/workspace/core/src/test/java/kafka/test/MockController.java`

**Provides:**
- Mock controller for unit tests
- Stub implementations of controller methods
- No actual metadata log or state machine

**File:** `/workspace/core/src/test/java/kafka/test/ClusterInstance.java`

**Provides:**
- Generic cluster abstraction
- Works with both ZK and KRaft clusters
- Unified API for cluster operations

---

### Running Tests

```bash
# Run all tests
./gradlew test

# Run only unit tests
./gradlew unitTest

# Run only integration tests
./gradlew integrationTest

# Run specific test class
./gradlew test --tests ControllerApisTest

# Run specific test method
./gradlew test --tests ControllerApisTest.testCreateTopics

# Run tests with verbose output
./gradlew test --info

# Run with retries (for flaky tests)
./gradlew test -PmaxTestRetries=3

# Run tests for specific module
./gradlew core:test
./gradlew clients:test
```

---

## 5. Configuration System

### Configuration Registry Architecture

**Primary Registry:** `/workspace/server/src/main/java/org/apache/kafka/server/config/AbstractKafkaConfig.java`

**Configuration Definition:** `AbstractKafkaConfig.CONFIG_DEF`

```java
public abstract class AbstractKafkaConfig extends AbstractConfig {
  public static final ConfigDef CONFIG_DEF = Utils.mergeConfigs(Arrays.asList(
    RemoteLogManagerConfig.configDef(),
    ZkConfigs.CONFIG_DEF,
    ServerConfigs.CONFIG_DEF,          // Broker-level configs
    KRaftConfigs.CONFIG_DEF,           // KRaft-specific configs
    SocketServerConfigs.CONFIG_DEF,    // Network configs
    ReplicationConfigs.CONFIG_DEF,     // Replication configs
    GroupCoordinatorConfig.*_CONFIG_DEF,  // Consumer group configs
    CleanerConfig.CONFIG_DEF,          // Log cleaner configs
    LogConfig.SERVER_CONFIG_DEF,       // Log/topic configs
    QuotaConfigs.CONFIG_DEF,           // Quota configs
    // ... 10+ more config sources
  ));
}
```

**Config Hierarchy:**
```
AbstractKafkaConfig.CONFIG_DEF (master registry)
├── ServerConfigs.CONFIG_DEF
│   └── broker.id, listeners, num.io.threads, etc.
├── ZkConfigs.CONFIG_DEF
│   └── zookeeper.connect, zookeeper.session.timeout.ms, etc.
├── KRaftConfigs.CONFIG_DEF
│   └── process.roles, node.id, controller.quorum.voters, etc.
├── LogConfig.SERVER_CONFIG_DEF
│   └── log.retention.hours, log.segment.bytes, etc.
├── ReplicationConfigs.CONFIG_DEF
│   └── default.replication.factor, min.insync.replicas, etc.
└── ... (20+ more)
```

---

### ServerConfigs Definition Location

**File:** `/workspace/server/src/main/java/org/apache/kafka/server/config/ServerConfigs.java` (~400 lines)

**Structure of Config Definition:**
```java
public class ServerConfigs {
  // Constants for each config
  public static final String BROKER_ID_CONFIG = "broker.id";
  public static final int BROKER_ID_DEFAULT = -1;
  public static final String BROKER_ID_DOC = "The broker id for this server...";

  // Config type and validation
  public static final ConfigDef CONFIG_DEF = new ConfigDef()
    .define(
      BROKER_ID_CONFIG,           // Name
      INT,                         // Type
      BROKER_ID_DEFAULT,          // Default value
      HIGH,                        // Importance
      BROKER_ID_DOC              // Documentation
    )
    .define(
      NUM_IO_THREADS_CONFIG,
      INT,
      NUM_IO_THREADS_DEFAULT,
      atLeast(1),                 // Validator
      HIGH,
      NUM_IO_THREADS_DOC
    )
    // ... more configs
}
```

---

### KafkaConfig Wrapper

**File:** `/workspace/core/src/main/scala/kafka/server/KafkaConfig.scala` (~800 lines)

**Purpose:** Type-safe wrapper around CONFIG_DEF

**Key Components:**

1. **Configuration Parsing:**
```scala
object KafkaConfig {
  def fromProps(props: Properties, doLog: Boolean): KafkaConfig = {
    // 1. Validate against CONFIG_DEF
    // 2. Apply defaults from CONFIG_DEF
    // 3. Handle special cases (listeners, security, etc.)
    // 4. Create KafkaConfig instance
  }
}
```

2. **Type-Safe Access:**
```scala
class KafkaConfig(...) extends AbstractConfig(...) {
  def brokerId: Int = getInt(BROKER_ID_CONFIG)
  def numIoThreads: Int = getInt(NUM_IO_THREADS_CONFIG)
  def logDirs: Seq[String] = getList(LOG_DIRS_CONFIG).asScala
  def listeners: Seq[EndPoint] = ...  // Complex parsing
}
```

3. **Configuration Synonyms:**
- Multiple names for same config
- Example: `log.roll.ms` vs `log.roll.hours` (both set log rolling)
- Defined in `DynamicBrokerConfig.brokerConfigSynonyms()`

---

### Topic Configuration

**File:** `/workspace/storage/src/main/java/org/apache/kafka/storage/internals/log/LogConfig.java` (~600 lines)

**Topic-Level Configs (TopicConfig):**
```java
public class LogConfig extends AbstractConfig {
  public static final String COMPRESSION_TYPE_CONFIG = "compression.type";
  public static final String MIN_INSYNC_REPLICAS_CONFIG = "min.insync.replicas";
  public static final String RETENTION_BYTES_CONFIG = "retention.bytes";
  public static final String RETENTION_MS_CONFIG = "retention.ms";
  public static final String SEGMENT_BYTES_CONFIG = "segment.bytes";
  public static final String SEGMENT_MS_CONFIG = "segment.ms";
  // ... 30+ topic-level configs

  public static final ConfigDef SERVER_CONFIG_DEF = new ConfigDef()
    .define(COMPRESSION_TYPE_CONFIG, ...)
    // ...
}
```

---

### Dynamic Configuration System

**File:** `/workspace/core/src/main/scala/kafka/server/DynamicBrokerConfig.scala` (~500 lines)

**Dynamic vs Static Configs:**
```scala
object DynamicBrokerConfig {
  // All configs that can be updated at runtime
  val AllDynamicConfigs = Set(
    // Security: SSL/SASL configs
    "ssl.keystore.password",
    "ssl.key.password",
    // Log cleaner
    "log.cleaner.enable",
    "log.cleaner.threads",
    // Network
    "num.network.threads",
    // ... ~50 total
  )

  // Validation
  def validateConfigs(props: Properties, perBrokerConfig: Boolean): Unit = {
    if (!perBrokerConfig) {
      checkInvalidProps(perBrokerConfigs(props),
        "Cannot update these configs at default cluster level")
    }
  }
}
```

**Config Precedence Order (for dynamic configs):**
```
1. DYNAMIC_BROKER_CONFIG
   - Per-broker in ZK: /configs/brokers/{brokerId}
2. DYNAMIC_DEFAULT_BROKER_CONFIG
   - Cluster-wide in ZK: /configs/brokers/<default>
3. STATIC_BROKER_CONFIG
   - From server.properties file
4. DEFAULT_CONFIG
   - Built-in defaults in ConfigDef
```

---

### Config Validation

**ConfigDef Validators:**
```java
// Range validators
atLeast(1)              // Value >= 1
between(0, 100)         // 0 <= Value <= 100

// Valid list validators
ValidList(List("gzip", "snappy", "lz4"))

// Custom validators
ValidString.in("read-committed", "read-uncommitted")
```

**Example from ServerConfigs:**
```java
.define(NUM_IO_THREADS_CONFIG, INT, NUM_IO_THREADS_DEFAULT,
        atLeast(1),  // Validator: must be >= 1
        HIGH, NUM_IO_THREADS_DOC)
```

---

### Configuration Update Flow

**Dynamic Update Process:**
```
1. Admin client calls AlterConfigs(resource, config_entries)
   ↓
2. Broker receives AlterConfigsRequest
   ↓
3. ControllerApis.handleAlterConfigsRequest()
   ↓
4. DynamicBrokerConfig.validateConfigs()
   - Checks if config is dynamic
   - Validates value against ConfigDef
   - Checks per-broker vs cluster-wide restrictions
   ↓
5. Write to ZK: /configs/brokers/{id}
   ↓
6. Broker watches ZK path, detects update
   ↓
7. DynamicBrokerConfig.reloadConfigs()
   - Parses new values
   - Calls reconfigure listeners (e.g., SecurityConfig, LogCleaner)
   ↓
8. Response sent with success
```

---

## 6. Adding a New Broker Configuration Parameter

### Complete Step-by-Step Process

**Scenario:** Add new broker config `my.custom.parameter` (type: INT, default: 100, dynamic: true)

---

### Step 1: Define the Configuration

**File:** `/workspace/server/src/main/java/org/apache/kafka/server/config/ServerConfigs.java`

**Action:** Add public constants and update CONFIG_DEF

```java
public class ServerConfigs {
  // Add static constants
  public static final String MY_CUSTOM_PARAMETER_CONFIG = "my.custom.parameter";
  public static final int MY_CUSTOM_PARAMETER_DEFAULT = 100;
  public static final String MY_CUSTOM_PARAMETER_DOC =
    "Description of what this parameter controls. " +
    "This is visible in documentation and config help.";

  public static final ConfigDef CONFIG_DEF = new ConfigDef()
    // ... existing configs ...
    .define(
      MY_CUSTOM_PARAMETER_CONFIG,      // Config name
      INT,                              // Type (INT, STRING, BOOLEAN, LONG, etc.)
      MY_CUSTOM_PARAMETER_DEFAULT,     // Default value
      atLeast(0),                       // Optional validator (or omit)
      MEDIUM,                           // Importance (HIGH, MEDIUM, LOW)
      MY_CUSTOM_PARAMETER_DOC          // Documentation string
    )
}
```

**Type Options:**
```
STRING, INT, LONG, DOUBLE, BOOLEAN, LIST, CLASS
```

**Importance Options:**
```
HIGH    - Important for correct operation
MEDIUM  - Important for performance/tuning
LOW     - Optional/rarely needed
```

---

### Step 2: Add Type-Safe Accessor in KafkaConfig

**File:** `/workspace/core/src/main/scala/kafka/server/KafkaConfig.scala`

**Action:** Add getter method to class body

```scala
class KafkaConfig(props: Properties) extends AbstractConfig(...) {
  // ... existing getters ...

  def myCustomParameter: Int = getInt(ServerConfigs.MY_CUSTOM_PARAMETER_CONFIG)

  // If it's a complex type, add parsing logic
  // def myComplexParam: ComplexType = {
  //   val raw = getString(...)
  //   // Parse and return
  // }
}
```

**Alternative for more complex access:**
```scala
// If config has multiple related values:
def myCustomParameterMs: Long = {
  get(ServerConfigs.MY_CUSTOM_PARAMETER_CONFIG) match {
    case -1 => NO_TIMEOUT
    case ms => ms
  }
}
```

---

### Step 3: Mark as Dynamic (If Applicable)

**File:** `/workspace/core/src/main/scala/kafka/server/DynamicBrokerConfig.scala`

**If config should be updateable at runtime:**

```scala
object DynamicBrokerConfig {
  // Create a new config set for your feature
  private[server] val DynamicCustomConfigs = Set(
    ServerConfigs.MY_CUSTOM_PARAMETER_CONFIG
  )

  val AllDynamicConfigs = DynamicSecurityConfigs ++
    LogCleaner.ReconfigurableConfigs ++
    DynamicLogConfig.ReconfigurableConfigs ++
    // ... existing ...
    DynamicCustomConfigs  // Add your set
}
```

**If config should be static (non-dynamic), skip this step.**

---

### Step 4: Implement Config Update Handler (If Dynamic)

**File:** Create or update config handler class**

**Example:** If your config affects thread pool, implement `Reconfigurable`:

```scala
// In kafka/server/MyCustomFeature.scala
class MyCustomFeature(...) extends Reconfigurable {

  override def reconfigure(configs: util.Map[String, _]): Unit = {
    val oldValue = currentValue
    val newValue = configs.get(MY_CUSTOM_PARAMETER_CONFIG).asInstanceOf[Int]

    if (oldValue != newValue) {
      // Apply the change
      updateThreadPoolSize(newValue)
    }
  }

  override def validateReconfiguration(configs: util.Map[String, _]): Unit = {
    // Optional: validate before applying
    val newValue = configs.get(MY_CUSTOM_PARAMETER_CONFIG).asInstanceOf[Int]
    if (newValue < 0) {
      throw new ConfigException("Value must be non-negative")
    }
  }

  override def reconfigurableConfigs(): util.Set[String] = {
    Collections.singleton(ServerConfigs.MY_CUSTOM_PARAMETER_CONFIG)
  }
}
```

**Register the handler in KafkaServer.startup():**
```scala
// In kafka/server/KafkaServer.scala
val myCustomFeature = new MyCustomFeature(config)
dynamicBrokerConfig.addReconfigurable(myCustomFeature)
```

---

### Step 5: Handle Validation (Optional)

**If complex validation needed beyond ConfigDef validators:**

**File:** `/workspace/core/src/main/scala/kafka/server/KafkaServer.scala`

```scala
def validateConfig(config: KafkaConfig): Unit = {
  // Custom validation logic
  if (config.myCustomParameter > 0 && config.anotherConfig < 0) {
    throw new ConfigException("my.custom.parameter requires anotherConfig >= 0")
  }
}
```

---

### Step 6: Use the Config in Your Component

**File:** Wherever your feature is implemented

```scala
// Example in replica manager
class ReplicaManager(config: KafkaConfig, ...) {

  private var customParam = config.myCustomParameter

  // Register for dynamic updates (if dynamic)
  dynamicBrokerConfig.addReconfigurable(
    new Reconfigurable {
      override def reconfigure(configs: util.Map[String, _]): Unit = {
        customParam = configs.get("my.custom.parameter").asInstanceOf[Int]
        // Apply change
      }
      override def reconfigurableConfigs() =
        Collections.singleton("my.custom.parameter")
    }
  )

  // Use in your logic
  def someMethod(): Unit = {
    val timeout = customParam * 1000  // Convert to milliseconds
    // ... use timeout ...
  }
}
```

---

### Step 7: Add Configuration to Template

**File:** `/workspace/config/server.properties`

```properties
# Custom configuration
# Description of what this parameter does
my.custom.parameter=100
```

**File:** `/workspace/config/kraft/server.properties` (for KRaft mode)

```properties
# Custom configuration for KRaft mode
my.custom.parameter=100
```

---

### Step 8: Update Documentation

**File:** `/workspace/docs/ops.html` or markdown docs

**Add section:**
```
## my.custom.parameter

**Type:** int
**Default:** 100
**Valid Range:** >= 0
**Dynamic:** Yes (can be updated with AlterConfigs)
**Scope:** per-broker

Description of the configuration parameter and when to tune it.
```

---

### Step 9: Add Unit Tests

**File:** `/workspace/core/src/test/scala/unit/kafka/server/KafkaConfigTest.scala`

```scala
class KafkaConfigTest extends AnyFlatSpec with BeforeAndAfterEach {

  "KafkaConfig" should "parse my.custom.parameter correctly" in {
    val props = new Properties()
    props.put("broker.id", "1")
    props.put("log.dirs", "/tmp/logs")
    props.put("my.custom.parameter", "200")

    val config = KafkaConfig.fromProps(props)

    assert(config.myCustomParameter == 200)
  }

  it should "use default value when not specified" in {
    val props = new Properties()
    props.put("broker.id", "1")
    props.put("log.dirs", "/tmp/logs")
    // my.custom.parameter not specified

    val config = KafkaConfig.fromProps(props)

    assert(config.myCustomParameter == 100)  // Default
  }

  it should "reject invalid values" in {
    val props = new Properties()
    props.put("broker.id", "1")
    props.put("log.dirs", "/tmp/logs")
    props.put("my.custom.parameter", "-1")  // Invalid

    assertThrows[ConfigException] {
      KafkaConfig.fromProps(props)
    }
  }
}
```

---

### Step 10: Add Integration Tests (If Dynamic)

**File:** `/workspace/core/src/test/scala/integration/kafka/server/DynamicBrokerReconfigurationTest.scala`

```scala
class DynamicBrokerReconfigurationTest extends KafkaServerTestHarness {

  @Test
  def testDynamicMyCustomParameterUpdate(): Unit = {
    val brokerId = "0"

    // Get initial value
    val broker = brokers(0)
    val initialValue = broker.config.myCustomParameter
    assert(initialValue == 100)  // Default

    // Update dynamically
    alterBrokerConfigs(brokerId, new Properties() {
      put("my.custom.parameter", "200")
    })

    // Verify change was applied
    val updatedValue = broker.config.myCustomParameter
    assert(updatedValue == 200)

    // Verify broker behavior reflects new value
    // ... add assertions specific to your feature ...
  }
}
```

---

### Step 11: Build and Test

```bash
# Format code
./gradlew spotlessApply

# Compile
./gradlew core:classes

# Run unit tests
./gradlew core:test --tests KafkaConfigTest

# Run all tests
./gradlew test

# Build distribution
./gradlew assembleDist
```

---

### Complete Configuration Checklist

When adding a new broker config, ensure you've completed:

- [ ] Define config constant in `ServerConfigs.java`
- [ ] Add to `CONFIG_DEF` with type, default, validator, importance
- [ ] Add getter in `KafkaConfig.scala` (or use `get()` directly)
- [ ] Update `DynamicBrokerConfig.scala` if config is dynamic
- [ ] Implement `Reconfigurable` handler if config needs live updates
- [ ] Add config to `server.properties` template
- [ ] Add config to `kraft/server.properties` if KRaft-specific behavior
- [ ] Update documentation
- [ ] Add unit tests in `KafkaConfigTest.scala`
- [ ] Add integration tests if dynamic
- [ ] Update code that uses the config
- [ ] Test with full build: `./gradlew test`
- [ ] Verify in config help output (run `KafkaConfig.main()`)

---

### Testing Config Help Output

**To view generated config documentation:**

```bash
cd /workspace
./gradlew :core:compileScala

java -cp "core/build/classes/main:$(./gradlew -q :core:printClasspath)" \
  kafka.server.KafkaConfig > /tmp/kafka-config.html

# Open in browser
open /tmp/kafka-config.html
```

---

## Summary

This comprehensive guide covers:

1. **Build System:** Gradle-based with 30+ modules
2. **Broker Startup:** Entry point through `Kafka.scala`, KafkaServer/KafkaRaftServer initialization
3. **Module Structure:** Clear separation between core broker, clients, streams, connect, coordination
4. **Topic Creation Flow:** Request handling pipeline from network to storage
5. **Testing:** Unit tests with JUnit5/ScalaTest, integration tests with test harness
6. **Configuration System:** ConfigDef-based registry with dynamic update support
7. **Adding Configs:** 11-step process including definition, handlers, validation, testing

The Kafka codebase demonstrates enterprise-grade architecture with careful attention to extensibility, testability, and operational flexibility.
