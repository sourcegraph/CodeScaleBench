# Apache Kafka Codebase Orientation

## 1. Build System and Broker Startup

### Build System
Apache Kafka uses **Gradle** as its build system. The main build configuration is defined in:
- `/workspace/build.gradle` - Root build file with plugins and global configurations
- `/workspace/gradle` - Directory containing Gradle plugins and dependency management
- `/workspace/gradle/dependencies.gradle` - Centralized dependency version management
- `/workspace/settings.gradle` - Gradle settings with module definitions

The codebase is organized into multiple Gradle subprojects (modules), each with their own `build.gradle` or inheriting from parent configuration.

### Broker Startup - Main Entry Point

**Primary Entry Point Class**: `kafka.Kafka` (located at `/workspace/core/src/main/scala/kafka/Kafka.scala`)

The startup flow is as follows:

1. **Command Line Entry**: `kafka.Kafka.main(args: Array[String])`
   - Accepts a single argument: path to `server.properties` file
   - Supports optional `--override` parameters to override config values
   - Example: `java kafka.Kafka /path/to/server.properties --override broker.id=1`

2. **Configuration Loading** (`kafka.Kafka.getPropsFromArgs()`):
   - Loads properties from the server.properties file using `Utils.loadProps()`
   - Applies command-line overrides using `--override` flags
   - Returns a `Properties` object with all configuration

3. **Server Type Selection** (`kafka.Kafka.buildServer()`):
   - Creates a `KafkaConfig` object from properties: `KafkaConfig.fromProps(props, doLog = false)`
   - Checks if ZooKeeper is required: `config.requiresZookeeper`
   - For ZooKeeper mode: creates `KafkaServer` instance
   - For KRaft mode (Kafka Raft): creates `KafkaRaftServer` instance
   - Both implement the `Server` trait for unified interface

4. **Key Classes Involved**:
   - **`kafka.Kafka`** - Entry point object
   - **`kafka.server.KafkaConfig`** - Immutable broker configuration loaded from server.properties
   - **`kafka.server.KafkaServer`** - Main broker implementation for ZooKeeper mode
   - **`kafka.server.KafkaRaftServer`** - Broker implementation for KRaft mode (new consensus)
   - **`kafka.server.Server`** - Trait defining broker interface (startup/shutdown)

5. **Startup Sequence**:
   - Signal handler registration (for graceful shutdown on SIGTERM/SIGINT)
   - Shutdown hook attachment via `Exit.addShutdownHook()`
   - Server startup via `server.startup()`
   - Server awaits termination via `server.awaitShutdown()`

6. **Key Initialization Components in KafkaServer**:
   - **Metrics**: `metrics: Metrics`, `kafkaYammerMetrics: KafkaYammerMetrics`
   - **Socket Server**: `socketServer: SocketServer` (handles client connections)
   - **Request Handlers**: `dataPlaneRequestProcessor: KafkaApis`, `controlPlaneRequestProcessor: KafkaApis`
   - **Log Manager**: `_logManager: LogManager` (manages partitions and logs)
   - **Replica Manager**: `_replicaManager: ReplicaManager` (handles replication)
   - **Controller**: `kafkaController: KafkaController` (metadata management, leadership)
   - **Admin Manager**: `adminManager: ZkAdminManager` (topic/partition admin operations)
   - **Coordinator Managers**: For groups and transactions
   - **Configuration**: `dynamicConfigManager: ZkConfigManager` (for dynamic config updates)

## 2. Module Structure

Kafka is organized into multiple modules with clear responsibilities:

### Core Modules (in `/workspace/core/src/main`)

| Module | Package | Responsibility |
|--------|---------|-----------------|
| **kafka.server** | `/core/src/main/scala/kafka/server/` | Broker server implementation, request handling, state management |
| **kafka.controller** | `/core/src/main/scala/kafka/controller/` | Leader election, partition assignment, metadata management |
| **kafka.log** | `/core/src/main/scala/kafka/log/` | Log storage, segment management, log cleanup/compaction |
| **kafka.cluster** | `/core/src/main/scala/kafka/cluster/` | Broker and partition abstractions, replica management |
| **kafka.zk** | `/core/src/main/scala/kafka/zk/` | ZooKeeper client wrapper, path management, state coordination |
| **kafka.network** | `/core/src/main/scala/kafka/network/` | Socket server, request/response channel, protocol handling |
| **kafka.coordinator** | `/core/src/main/scala/kafka/coordinator/` | Group coordinator, transaction coordinator |
| **kafka.metrics** | `/core/src/main/scala/kafka/metrics/` | Metrics reporters and management |
| **kafka.tools** | `/core/src/main/scala/kafka/tools/` | CLI tools for admin operations |
| **kafka.utils** | `/core/src/main/scala/kafka/utils/` | Utility functions, logging, scheduling |
| **kafka.raft** | `/core/src/main/scala/kafka/raft/` | KRaft consensus protocol implementation |
| **kafka.migration** | `/core/src/main/scala/kafka/migration/` | ZooKeeper to KRaft migration utilities |

### Supporting Modules

| Module | Location | Responsibility |
|--------|----------|-----------------|
| **server** | `/workspace/server/src/main/java/` | Java implementations of server configs and components |
| **clients** | `/workspace/clients/src/main/` | Java client libraries (Producer, Consumer, Admin) |
| **streams** | `/workspace/streams/src/main/` | Kafka Streams library |
| **group-coordinator** | `/workspace/group-coordinator/src/main/` | Consumer group coordination (new implementation) |
| **transaction-coordinator** | `/workspace/transaction-coordinator/src/main/` | Transactional message handling |
| **storage** | `/workspace/storage/src/main/` | Storage layer abstractions |
| **metadata** | `/workspace/metadata/src/main/` | Metadata encoding/decoding for KRaft |
| **raft** | `/workspace/raft/src/main/` | Raft consensus implementation |
| **connect** | `/workspace/connect/src/main/` | Kafka Connect framework |

### Directory Layout

```
/workspace/
├── core/                    # Main broker implementation (Scala/Java)
├── clients/                 # Client libraries
├── streams/                 # Streams library
├── connect/                 # Kafka Connect
├── server/                  # Server configuration (Java)
├── server-common/           # Shared server code
├── group-coordinator/       # Consumer group coordination
├── transaction-coordinator/ # Transaction coordination
├── storage/                 # Storage abstraction
├── metadata/                # Metadata management
├── raft/                    # Raft consensus
├── tools/                   # CLI tools
├── tests/                   # Integration tests
├── examples/                # Example code
├── config/                  # Default configuration files
├── bin/                     # Startup scripts
├── docker/                  # Docker configuration
└── build.gradle             # Root Gradle build file
```

## 3. Topic Creation Flow

Topic creation in Kafka follows different paths depending on whether the cluster uses ZooKeeper or KRaft mode:

### ZooKeeper Mode Topic Creation Flow

1. **Client Request**: Admin client sends `CreateTopicsRequest`

2. **Broker Request Handler** (`kafka.server.KafkaApis.handleCreateTopicsRequest()`):
   - Located at: `/workspace/core/src/main/scala/kafka/server/KafkaApis.scala`
   - Validates request through authorization
   - Checks if broker is the controller: `zkSupport.controller.isActive`
   - If not controller: returns `NOT_CONTROLLER` error
   - If controller: delegates to controller's `createTopics` method

3. **Controller Processing** (`kafka.controller.KafkaController`):
   - Located at: `/workspace/core/src/main/scala/kafka/controller/KafkaController.scala`
   - Creates topic metadata records
   - Assigns partitions to brokers using replication strategy
   - Stores topic metadata in ZooKeeper at: `/brokers/topics/{topicName}`
   - Stores ISR (In-Sync Replicas) info at: `/isr/{topicName}/{partitionId}`

4. **Broker Metadata Updates**:
   - All brokers watch ZooKeeper paths and receive notifications
   - Topic metadata is updated locally on each broker
   - Log directories are created for assigned partitions

5. **Response**: Returns `CreateTopicsResponse` with success/error status for each topic

### KRaft Mode Topic Creation Flow

1. **Client Request**: Admin client sends `CreateTopicsRequest`

2. **Broker Routing**: Non-controller brokers forward request to controller (KRaft cluster leader)

3. **Controller Handler** (`kafka.server.ControllerApis.handleCreateTopics()`):
   - Located at: `/workspace/core/src/main/scala/kafka/server/ControllerApis.scala`
   - Validates authorization
   - Calls `createTopics()` method with context
   - Topic creation is recorded in metadata log (replicated state)

4. **Metadata Log Recording**:
   - Topic and partition records written to metadata topic (`__cluster_metadata`)
   - Records are replicated across controller quorum
   - All brokers replaying metadata log receive updates

5. **Broker Application**:
   - Brokers read metadata log and apply topic records
   - Metadata image is updated locally
   - Log directories created for assigned partitions

### Key Classes and Methods

| Component | Class | Method | Location |
|-----------|-------|--------|----------|
| Request Handler (ZK) | `KafkaApis` | `handleCreateTopicsRequest()` | `/core/src/main/scala/kafka/server/KafkaApis.scala` |
| Request Handler (KRaft) | `ControllerApis` | `handleCreateTopics()` | `/core/src/main/scala/kafka/server/ControllerApis.scala` |
| Controller | `KafkaController` | `createTopics()` | `/core/src/main/scala/kafka/controller/KafkaController.scala` |
| Admin Operations | `ZkAdminManager` | `createTopic()` | `/core/src/main/scala/kafka/server/ZkAdminManager.scala` |
| Partition Assignment | `AdminUtils` | `assignReplicasToBrokers()` | `/core/src/main/scala/kafka/admin/AdminUtils.scala` |
| Log Initialization | `LogManager` | `createLog()` | `/core/src/main/scala/kafka/log/LogManager.scala` |

### Topic Creation Data Flow Example

```
Client (AdminClient.createTopics())
    ↓
Broker Network Layer (SocketServer)
    ↓
Request Handler (KafkaApis/ControllerApis)
    ↓
Authorization Check (AuthHelper)
    ↓
Partition Assignment (AdminUtils/ReplicaAssignment)
    ↓
Metadata Storage (ZooKeeper or Metadata Log)
    ↓
All Brokers Notified (ZK Watch or Metadata Log Replay)
    ↓
Log Creation (LogManager.createLog)
    ↓
Response to Client
```

## 4. Testing Framework

Kafka uses both **unit tests** and **integration tests** with multiple testing frameworks:

### Testing Frameworks and Libraries

1. **JUnit 5 (Jupiter)**
   - Standard framework for both unit and integration tests
   - Uses `@Test` annotation for test methods
   - Located in `/workspace/core/src/test/`

2. **Mockito**
   - Mocking framework for unit tests
   - Creates mock objects and verifies interactions
   - Used extensively in configuration and server tests

3. **ScalaTest** (for Scala tests)
   - Provides additional Scala-specific testing utilities
   - Used in some integration tests

### Unit Test Examples

**Location**: `/workspace/core/src/test/`

1. **Handler Tests** (Java):
   ```java
   // File: /workspace/core/src/test/java/kafka/server/handlers/DescribeTopicPartitionsRequestHandlerTest.java
   @Test
   public void testDescribeTopicPartitions() {
       // Create mock metadata cache
       // Create request
       // Call handler
       // Verify response
   }
   ```

2. **Configuration Tests** (Scala):
   ```scala
   // File: /workspace/core/src/test/scala/unit/kafka/server/DynamicBrokerConfigTest.scala
   class DynamicBrokerConfigTest {
       @Test
       def testConfigUpdate(): Unit = {
           val props = TestUtils.createBrokerConfig(0, null, port = 8181)
           val config = KafkaConfig(props)
           val dynamicConfig = config.dynamicConfig
           dynamicConfig.initialize(None, None)
           // Verify config behavior
       }
   }
   ```

3. **Request Handler Tests** (Scala):
   ```scala
   // File: /workspace/core/src/test/scala/kafka/server/KafkaRequestHandlerTest.scala
   class KafkaRequestHandlerTest {
       @Test
       def testCallbackTiming(): Unit = {
           val metrics = new RequestChannel.Metrics(None)
           val requestChannel = new RequestChannel(10, "", time, metrics)
           // Test request handling
       }
   }
   ```

### Integration Test Examples

**Location**: `/workspace/core/src/test/scala/integration/`

Tests that start actual Kafka clusters:

```scala
// File examples:
// /workspace/core/src/test/scala/integration/kafka/api/ConsumerTopicCreationTest.scala
// /workspace/core/src/test/scala/integration/kafka/api/RackAwareAutoTopicCreationTest.scala
// /workspace/core/src/test/scala/integration/kafka/admin/RemoteTopicCrudTest.scala
```

### Test Utilities

- **TestUtils** (`kafka.utils.TestUtils`)
  - `createBrokerConfig()` - Create broker configuration for testing
  - `waitUntilTrue()` - Wait for condition with timeout
  - Mock object creation utilities

- **Test Fixtures**
  - Default configuration files in `/workspace/config/`
  - Example: `/workspace/config/server.properties`

### Writing Tests for Kafka Components

1. **For Unit Tests**:
   - Create a new class in `/workspace/core/src/test/scala/unit/kafka/`
   - Extend test class or use `@Test` annotation
   - Use `TestUtils.createBrokerConfig()` for configuration
   - Use Mockito for mocking dependencies

2. **For Integration Tests**:
   - Create test in `/workspace/core/src/test/scala/integration/`
   - Use test cluster utilities to start brokers
   - Verify behavior through actual broker operations
   - Clean up resources after test (JUnit lifecycle)

3. **Test Organization**:
   - Follow module structure (e.g., test for `kafka.server` goes in `test/scala/unit/kafka/server/`)
   - Use descriptive test names (e.g., `testConfigUpdateDynamically`)
   - Include both positive and negative test cases

## 5. Configuration System

Kafka's configuration is hierarchical and supports both static (startup) and dynamic (runtime) configuration:

### Configuration Architecture

**Configuration Definition Chain** (merged in this order):

1. **AbstractKafkaConfig.CONFIG_DEF** - Master config definition (located at `/workspace/server/src/main/java/org/apache/kafka/server/config/AbstractKafkaConfig.java`)

This merges multiple configuration sources:
```java
public static final ConfigDef CONFIG_DEF = Utils.mergeConfigs(Arrays.asList(
    RemoteLogManagerConfig.configDef(),
    ZkConfigs.CONFIG_DEF,
    ServerConfigs.CONFIG_DEF,           // Broker-specific configs
    KRaftConfigs.CONFIG_DEF,            // KRaft-specific configs
    SocketServerConfigs.CONFIG_DEF,     // Network configs
    ReplicationConfigs.CONFIG_DEF,      // Replication configs
    GroupCoordinatorConfig.XXX,         // Consumer group configs
    CleanerConfig.CONFIG_DEF,           // Log cleaner configs
    LogConfig.SERVER_CONFIG_DEF,        // Log configs
    TransactionLogConfigs.CONFIG_DEF,   // Transaction configs
    QuorumConfig.CONFIG_DEF,            // Quorum configs
    MetricConfigs.CONFIG_DEF,           // Metrics configs
    QuotaConfigs.CONFIG_DEF,            // Quota configs
    // ... and more
));
```

### Configuration Definition Files

| File | Location | Responsibility |
|------|----------|-----------------|
| **ServerConfigs** | `/workspace/server/src/main/java/org/apache/kafka/server/config/ServerConfigs.java` | Core broker parameters (broker.id, message.max.bytes, num.io.threads, etc.) |
| **ZkConfigs** | `/workspace/server/src/main/java/org/apache/kafka/server/config/ZkConfigs.java` | ZooKeeper-related parameters |
| **KRaftConfigs** | `/workspace/server/src/main/java/org/apache/kafka/server/config/KRaftConfigs.java` | KRaft-specific parameters |
| **SocketServerConfigs** | `/workspace/server/src/main/java/org/apache/kafka/network/SocketServerConfigs.java` | Network listener configuration |
| **LogConfig** | `/workspace/storage/src/main/java/org/apache/kafka/storage/internals/log/LogConfig.java` | Log segment configuration |

### Configuration Precedence (Broker Configs)

1. **DYNAMIC_BROKER_CONFIG** - Per-broker dynamic config (ZK: `/configs/brokers/{brokerId}`)
2. **DYNAMIC_DEFAULT_BROKER_CONFIG** - Cluster-wide defaults (ZK: `/configs/brokers/<default>`)
3. **STATIC_BROKER_CONFIG** - From server.properties startup file
4. **DEFAULT_CONFIG** - Built-in defaults in CONFIG_DEF

### Configuration Loading

**Primary Config Class**: `kafka.server.KafkaConfig` (Scala wrapper)

```scala
// Located at: /workspace/core/src/main/scala/kafka/server/KafkaConfig.scala
class KafkaConfig(props: java.util.Map[_, _], doLog: Boolean = true)
  extends AbstractKafkaConfig(AbstractKafkaConfig.CONFIG_DEF, props, ...)

object KafkaConfig {
  def fromProps(props: Properties): KafkaConfig = new KafkaConfig(props)
  def fromProps(props: Properties, doLog: Boolean): KafkaConfig = new KafkaConfig(props, doLog)
}
```

### Dynamic Configuration Management

**Class**: `kafka.server.DynamicBrokerConfig` (located at `/workspace/core/src/main/scala/kafka/server/DynamicBrokerConfig.scala`)

Handles configuration updates at runtime:

```scala
object DynamicBrokerConfig {
  // All configs that can be dynamically updated
  val AllDynamicConfigs = DynamicSecurityConfigs ++
    LogCleaner.ReconfigurableConfigs ++
    DynamicLogConfig.ReconfigurableConfigs ++
    DynamicThreadPool.ReconfigurableConfigs ++
    Set(MetricConfigs.METRIC_REPORTER_CLASSES_CONFIG) ++
    DynamicListenerConfig.ReconfigurableConfigs ++
    SocketServer.ReconfigurableConfigs ++
    DynamicProducerStateManagerConfig ++
    DynamicRemoteLogConfig.ReconfigurableConfigs
}

// Reconfigurable components
class DynamicLogConfig(logManager: LogManager, server: KafkaBroker)
  extends BrokerReconfigurable with Logging
class DynamicListenerConfig(server: KafkaBroker)
  extends BrokerReconfigurable with Logging
class DynamicMetricsReporters(brokerId: Int, config: KafkaConfig, metrics: Metrics, clusterId: String)
  extends Reconfigurable
```

### Configuration Validation

Configuration validation happens in two places:

1. **At Startup**: `KafkaConfig` constructor validates against `CONFIG_DEF`
2. **At Dynamic Update**: `DynamicBrokerConfig.validateConfigs()` validates only the changed properties

Each config has defined:
- Type (STRING, INT, LONG, BOOLEAN, LIST, DOUBLE, etc.)
- Default value
- Validator function (e.g., Range.atLeast(0))
- Documentation string
- Importance level (HIGH, MEDIUM, LOW)

### Configuration Parameter Examples

```java
// From ServerConfigs.java

// Basic config
public static final String BROKER_ID_CONFIG = "broker.id";
public static final int BROKER_ID_DEFAULT = -1;
public static final String BROKER_ID_DOC = "The broker id for this server...";

// Config with validation
public static final String NUM_IO_THREADS_CONFIG = "num.io.threads";
public static final int NUM_IO_THREADS_DEFAULT = 8;
public static final String NUM_IO_THREADS_DOC = "The number of threads...";
// Validation: Range.atLeast(1)

// Dynamic config
public static final String COMPRESSION_TYPE_CONFIG = "compression.type";
// Can be updated dynamically without broker restart
```

### Storage of Dynamic Configurations

**ZooKeeper Mode**:
- Stored in ZooKeeper under `/config/brokers/`
- Per-broker: `/config/brokers/{brokerId}`
- Cluster-wide defaults: `/config/brokers/<default>`
- Changes trigger `ConfigHandler` callbacks

**KRaft Mode**:
- Stored in metadata topic (`__cluster_metadata`)
- Replicated across controller quorum
- Applied through metadata log replay

## 6. Adding a New Broker Configuration Parameter

To add a new broker configuration parameter, follow these steps:

### Step 1: Define the Configuration

**File**: `/workspace/server/src/main/java/org/apache/kafka/server/config/ServerConfigs.java` (or appropriate config file)

```java
// Define config constants
public static final String MY_NEW_CONFIG = "my.new.config";
public static final int MY_NEW_CONFIG_DEFAULT = 100;  // or appropriate default
public static final String MY_NEW_CONFIG_DOC = "Documentation explaining what this config does...";
public static final String MY_NEW_CONFIG_IMPORTANCE = "HIGH";  // or MEDIUM, LOW

// If config has validation constraints:
// Add Range validator: Range.atLeast(0), Range.between(1, 100), etc.
// Add validator function if custom validation needed
```

Add to the config definition:
```java
.define(
    MY_NEW_CONFIG,
    ConfigDef.Type.INT,
    MY_NEW_CONFIG_DEFAULT,
    Range.atLeast(0),
    ConfigDef.Importance.HIGH,
    MY_NEW_CONFIG_DOC
)
```

### Step 2: Add Getter Method to KafkaConfig

**File**: `/workspace/core/src/main/scala/kafka/server/KafkaConfig.scala`

Add a lazy val that retrieves the configuration:
```scala
lazy val myNewConfig = getInt(ServerConfigs.MY_NEW_CONFIG)
```

### Step 3: Determine if Config is Dynamic

Check if the config can be updated without restarting:

**If Static Only**:
- Add to appropriate config class (ZkConfigs, KRaftConfigs, etc.)
- No additional steps needed

**If Dynamic**:
- Add to `DynamicBrokerConfig.AllDynamicConfigs` set
- Create a handler class implementing `Reconfigurable` interface
- Or add to existing handler class (e.g., `DynamicLogConfig`)

### Step 4: Implement Dynamic Update Handler (if applicable)

**File**: `/workspace/core/src/main/scala/kafka/server/DynamicBrokerConfig.scala`

Create or update a handler class:
```scala
class MyNewConfigHandler extends BrokerReconfigurable with Logging {
  override def reconfigurableConfigs: util.Set[String] =
    Collections.singleton(ServerConfigs.MY_NEW_CONFIG)

  override def validateReconfiguration(configs: util.Map[String, Any]): Unit = {
    // Additional validation logic (optional)
    val newValue = configs.get(ServerConfigs.MY_NEW_CONFIG).asInstanceOf[Integer]
    if (newValue < 0) {
      throw new ConfigException(s"Value must be non-negative, got $newValue")
    }
  }

  override def reconfigure(configs: util.Map[String, Any]): Unit = {
    // Apply configuration changes
    val newValue = configs.get(ServerConfigs.MY_NEW_CONFIG).asInstanceOf[Integer]
    // Update internal state or notify components
    info(s"Updated my.new.config to $newValue")
  }
}
```

Register in `KafkaServer.startup()`:
```scala
config.dynamicConfig.addBrokerReconfigurable(new MyNewConfigHandler())
```

### Step 5: Add Validation Logic (if needed)

**File**: `/workspace/server/src/main/java/org/apache/kafka/server/config/ServerConfigs.java`

Add validator if custom validation beyond range checks:
```java
public static void validateMyNewConfig(Config config) {
  int value = config.getInt(MY_NEW_CONFIG);
  if (/* some complex validation */) {
    throw new ConfigException(MY_NEW_CONFIG, value, "Error message");
  }
}
```

### Step 6: Add Tests

**Unit Test**: `/workspace/core/src/test/scala/unit/kafka/server/DynamicBrokerConfigTest.scala`

```scala
@Test
def testMyNewConfigUpdate(): Unit = {
  val props = TestUtils.createBrokerConfig(0, null, port = 8181)
  props.put(ServerConfigs.MY_NEW_CONFIG, "50")
  val config = KafkaConfig(props)

  // Test initial value
  assertEquals(50, config.myNewConfig)

  // Test dynamic update
  val updateProps = new Properties()
  updateProps.put(ServerConfigs.MY_NEW_CONFIG, "75")
  config.dynamicConfig.updateBrokerConfig(0, updateProps)

  // Verify update applied
  assertEquals(75, config.myNewConfig)
}
```

**Validation Test**:
```scala
@Test
def testMyNewConfigValidation(): Unit = {
  val props = TestUtils.createBrokerConfig(0, null, port = 8181)
  props.put(ServerConfigs.MY_NEW_CONFIG, "-10")  // Invalid: negative value

  assertThrows[ConfigException] {
    KafkaConfig(props)
  }
}
```

**Integration Test**: `/workspace/core/src/test/scala/integration/kafka/` (if needed)

### Step 7: Update Documentation

Update these files to document the new parameter:

1. **Configuration Documentation**:
   - Server config markdown files in `/workspace/docs/`
   - Your MY_NEW_CONFIG_DOC string serves as source

2. **Configuration File Example**:
   - Update `/workspace/config/server.properties` with example
   - Update `/workspace/config/kraft/server.properties` if KRaft-specific

3. **Breaking Changes** (if applicable):
   - Document in upgrade guide
   - Update compatibility matrix if needed

### Step 8: Build and Test

```bash
# Build the specific module
gradle build -p core

# Run tests for the module
gradle test -p core --tests DynamicBrokerConfigTest

# Run integration tests if added
gradle integrationTest -p core
```

### Configuration Parameter Checklist

- [ ] Define constant in appropriate `*Configs.java` file
- [ ] Add default value constant
- [ ] Add documentation string
- [ ] Add to `CONFIG_DEF` with type, default, validators
- [ ] Add getter method in `KafkaConfig.scala`
- [ ] Determine if static or dynamic
- [ ] If dynamic: create/update `Reconfigurable` handler
- [ ] If dynamic: add to `AllDynamicConfigs` or appropriate set
- [ ] Add unit tests for default and updated values
- [ ] Add validation tests (if applicable)
- [ ] Add integration test (if dynamic)
- [ ] Update documentation files
- [ ] Update example server.properties files
- [ ] Run full test suite and verify no regressions

### Example: Adding "my.queue.size" Configuration

```java
// ServerConfigs.java
public static final String MY_QUEUE_SIZE_CONFIG = "my.queue.size";
public static final int MY_QUEUE_SIZE_DEFAULT = 1000;
public static final String MY_QUEUE_SIZE_DOC = "The size of the internal queue for processing requests";

// In CONFIG_DEF
.define(
    MY_QUEUE_SIZE_CONFIG,
    ConfigDef.Type.INT,
    MY_QUEUE_SIZE_DEFAULT,
    Range.atLeast(1),
    ConfigDef.Importance.MEDIUM,
    MY_QUEUE_SIZE_DOC
)
```

```scala
// KafkaConfig.scala
lazy val myQueueSize = getInt(ServerConfigs.MY_QUEUE_SIZE_CONFIG)
```

```scala
// DynamicBrokerConfig.scala (if dynamic)
class MyQueueConfigHandler(server: KafkaBroker) extends BrokerReconfigurable {
  override def reconfigurableConfigs = Collections.singleton(ServerConfigs.MY_QUEUE_SIZE_CONFIG)

  override def reconfigure(configs: util.Map[String, Any]): Unit = {
    val newSize = configs.get(ServerConfigs.MY_QUEUE_SIZE_CONFIG).asInstanceOf[Integer]
    server.requestQueue.resizeQueue(newSize)  // Update server's queue
  }
}
```

---

## Summary of Key Takeaways

1. **Build System**: Gradle-based with modular structure
2. **Startup**: Entry point is `kafka.Kafka`, loads config, creates appropriate server type (ZK or KRaft)
3. **Modules**: Well-organized by responsibility (server, network, coordinator, etc.)
4. **Topic Creation**: Follows request → controller → metadata store → broker update path
5. **Testing**: JUnit 5 + Mockito for unit tests, integration tests use actual broker instances
6. **Configuration**: Hierarchical with dynamic update support, defined in `*Configs.java` classes
7. **Adding Config**: Define in `*Configs.java`, add getter in `KafkaConfig`, implement handler if dynamic, write tests
