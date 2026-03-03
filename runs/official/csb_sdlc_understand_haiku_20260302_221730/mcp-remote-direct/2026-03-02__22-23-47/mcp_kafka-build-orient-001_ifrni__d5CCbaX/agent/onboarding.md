# Apache Kafka Codebase Orientation

## 1. Build System and Broker Startup

### Build System
Kafka uses **Gradle** as its build system. The main build configuration files are:
- **`build.gradle`** - Root build configuration
- **`gradle.properties`** - Gradle properties and library versions
- **`settings.gradle`** - Gradle settings and module definitions
- **`wrapper.gradle`** - Gradle wrapper configuration

The build is organized as a multi-module project with separate directories for different components (core, clients, server, streams, connect, etc.).

### Broker Startup Entry Point

The main entry point for starting a Kafka broker is the **`kafka.Kafka`** class (`core/src/main/scala/kafka/Kafka.scala`). The flow is:

1. **`main(args: Array[String])`** method in `kafka.Kafka` object:
   - Parses command-line arguments and server.properties configuration
   - Calls `buildServer(serverProps)` which creates either a `KafkaServer` (ZooKeeper mode) or `KafkaRaftServer` (KRaft mode) based on configuration
   - Registers signal handlers for graceful shutdown
   - Calls `server.startup()` to initialize the broker
   - Calls `server.awaitShutdown()` to keep the broker running

### Key Classes Involved in Broker Initialization

1. **`kafka.Kafka`** (`core/src/main/scala/kafka/Kafka.scala`):
   - Main entry point with `main()` method
   - Handles command-line parsing and server instantiation

2. **`kafka.server.KafkaServer`** (`core/src/main/scala/kafka/server/KafkaServer.scala`):
   - Represents the lifecycle of a single Kafka broker
   - Main class for ZooKeeper-based deployments
   - Extends `KafkaBroker` and implements `Server` trait

3. **`kafka.server.KafkaRaftServer`** (`core/src/main/scala/kafka/server/KafkaRaftServer.scala`):
   - KRaft (Kafka Raft) mode broker implementation
   - Used when `process.roles` is configured

### KafkaServer Startup Process

The `KafkaServer.startup()` method performs the following initialization steps:

1. **ZooKeeper Initialization** - Connect to ZooKeeper and verify cluster ID
2. **Metadata Loading** - Load metadata properties from disk
3. **Broker ID Generation** - Determine broker ID
4. **Scheduler Startup** - Create and start KafkaScheduler
5. **Metrics Initialization** - Initialize metrics and reporters
6. **Log Manager Startup** - Create and start LogManager (handles log storage)
7. **Remote Log Manager** - Optional RemoteLogManager initialization
8. **Metadata Cache Setup** - Initialize ZkMetadataCache
9. **Socket Server Creation** - Create SocketServer for network communication
10. **Alter Partition Manager** - Start AlterPartitionManager for partition metadata changes
11. **Controller Registration** - Initialize KafkaController (if broker is controller)
12. **Replica Manager** - Start ReplicaManager for replica management
13. **Request Handler Pool** - Create request handler threads
14. **Admin Manager** - Start ZkAdminManager for administrative operations
15. **Group & Transaction Coordinators** - Initialize coordinators
16. **Server State Transition** - Transition broker state to RUNNING

Key components initialized:
- **SocketServer**: Handles network requests
- **LogManager**: Manages log storage and recovery
- **ReplicaManager**: Handles replication logic
- **KafkaController**: Manages cluster-wide metadata and elections
- **GroupCoordinator**: Manages consumer groups
- **TransactionCoordinator**: Manages transactions
- **KafkaApis**: Handles request processing

---

## 2. Module Structure

Kafka is organized into the following core modules:

### Core Modules

1. **`core/`** - Kafka Broker Core
   - Contains the main broker implementation
   - Key packages:
     - `kafka.server` - Broker lifecycle, request handling, admin operations
     - `kafka.network` - Socket server and request channel
     - `kafka.log` - Log storage and management
     - `kafka.controller` - Cluster controller (leader election, ISR management)
     - `kafka.zk` - ZooKeeper client interactions
     - `kafka.cluster` - Cluster metadata representations
   - Contains unit and integration tests

2. **`server/`** - Server Configuration and Utilities
   - Contains `org.apache.kafka.server.*` package implementations
   - Server-level configuration definitions
   - Cross-module server utilities
   - Future home for moving broker-agnostic server code out of core

3. **`server-common/`** - Server-Common Shared Code
   - Shared utilities used across server modules
   - Configuration classes used by both ZK and KRaft modes

4. **`clients/`** - Client Libraries
   - Java client implementations
   - Producer and Consumer APIs
   - Admin client
   - Authentication and security implementations
   - Protocol definitions and request/response classes

5. **`metadata/`** - Metadata Management (KRaft)
   - Controller and replication control
   - Metadata image and state machine
   - Used by KRaft mode for cluster coordination
   - Replaces ZooKeeper in KRaft mode

6. **`raft/`** - Raft Consensus Implementation
   - Raft algorithm implementation for KRaft mode
   - Log and state machine abstractions

7. **`group-coordinator/`** - Group Coordinator
   - Consumer group coordination logic
   - Group membership management
   - Rebalancing protocol implementation

8. **`transaction-coordinator/`** - Transaction Coordinator
   - Transactional message handling
   - Transaction state management
   - Producer ID management

9. **`storage/`** - Storage Layer
   - Log format implementations
   - Storage internals (segments, indexes)
   - Tiered storage support
   - Remote log manager

10. **`connect/`** - Kafka Connect
    - Connect framework implementation
    - Connector APIs and utilities
    - Distributed mode coordinator

11. **`streams/`** - Kafka Streams
    - Stream processing library
    - Topology builders
    - State stores
    - Processing logic

12. **`tools/`** - Administrative Tools
    - Command-line tools
    - Log inspection tools
    - Topic management tools

13. **`config/`** - Configuration Files
    - Sample server.properties files
    - KRaft mode configuration examples
    - Configuration documentation

14. **`tests/`** - System Tests
    - Trogdor performance testing framework
    - Integration test utilities
    - System-level test harnesses

### Dependency Flow

```
clients/
  └─ Common protocol definitions, exceptions, configs
    └─ core/
        ├─ Uses clients for protocol handling
        └─ Uses metadata/ for KRaft coordination
          ├─ Uses raft/ for consensus
          ├─ Uses storage/ for log management
          ├─ Uses group-coordinator/ for groups
          └─ Uses transaction-coordinator/ for transactions
```

---

## 3. Topic Creation Flow

Topic creation is a complex end-to-end process involving the client, broker, and cluster coordinator. Here's the complete flow:

### Request Path

1. **Client Initiates** - Client calls `AdminClient.createTopics()` which sends a `CreateTopicsRequest`

2. **Request Arrives at Broker** - SocketServer receives request and puts it in RequestChannel

3. **Request Handling** - KafkaApis processes the request:
   - Method: `KafkaApis.handleCreateTopicsRequest()` (`core/src/main/scala/kafka/server/KafkaApis.scala:2002`)
   - Determines if ZK mode (uses ZkAdminManager) or KRaft mode (uses Controller)

### ZooKeeper Mode Flow (Most Common)

1. **KafkaApis.handleCreateTopicsRequest()** (`core/src/main/scala/kafka/server/KafkaApis.scala:2002`)
   - Extracts `CreateTopicsRequest` data
   - Gets ZK admin manager
   - Calls `zkSupport.adminManager.createTopics()`

2. **ZkAdminManager.createTopics()** (`core/src/main/scala/kafka/server/ZkAdminManager.scala:159`)
   - **Validation Phase**:
     - Checks if topic already exists
     - Validates topic configuration (no null values)
     - Checks that both `numPartitions` and `assignments` are not provided together
   - **Assignment Phase**:
     - Resolves number of partitions (uses default if not specified)
     - Resolves replication factor (uses default if not specified)
     - If manual assignment provided: validates broker IDs
     - If auto assignment: calls `AdminUtils.assignReplicasToBrokers()` to generate replica assignments
   - **Policy Validation**:
     - Calls `CreateTopicPolicy.validate()` if policy is configured
     - Validates topic configuration values
   - **Topic Creation**:
     - If `validateOnly=true`: returns validation results
     - If `validateOnly=false`: Calls `adminZkClient.createTopicWithAssignment()` to create topic in ZooKeeper

3. **AdminZkClient.createTopicWithAssignment()** - Writes to ZooKeeper:
   - Creates `/brokers/topics/{topicName}` znode with partition assignments
   - Creates `/config/topics/{topicName}` znode with topic configuration
   - Creates `/admin/delete_topics/{topicName}` if needed for deletion tracking

4. **Controller Watches ZooKeeper** - `KafkaController` has watchers on `/brokers/topics`:
   - Detects new topic creation
   - Creates ISR (In-Sync Replicas) entries
   - Triggers leader election for each partition
   - Updates metadata cache

5. **Leader Election** - For each partition:
   - Controller selects first replica in assignment as initial leader
   - Updates `/brokers/topics/{topicName}/partitions/{partitionId}/state` with leader info
   - Sends `LeaderAndIsrRequest` to brokers to update partition leadership

6. **Broker State Update**:
   - Each broker receives `LeaderAndIsrRequest`
   - Updates local metadata cache
   - Initializes logs for assigned partitions
   - Starts replication if needed

### KRaft Mode Flow

1. **KafkaApis.handleCreateTopicsRequest()** - Forwards to KRaft controller
   - Calls `forwardingManager.forward()` or direct controller API
   - Sends `CreateTopicsRequest` to the KRaft controller leader

2. **ReplicationControlManager.createTopics()** (`metadata/src/main/java/org/apache/kafka/controller/ReplicationControlManager.java:587`)
   - Validates topic creation request
   - Records metadata events in the Raft log
   - Returns `CreateTopicsResponseData` with results

3. **Metadata Log Processing**:
   - Raft log entries are replicated across controller cluster
   - State machine applies entries to create topics
   - Brokers subscribe to metadata updates and apply changes

### Key Classes and Methods

| Component | Class/Method | File | Purpose |
|-----------|--------------|------|---------|
| Request | `CreateTopicsRequest` | `clients/src/main/java/org/apache/kafka/common/requests/CreateTopicsRequest.java` | Client request object |
| Handler | `KafkaApis.handleCreateTopicsRequest()` | `core/src/main/scala/kafka/server/KafkaApis.scala:2002` | Request entry point |
| ZK Manager | `ZkAdminManager.createTopics()` | `core/src/main/scala/kafka/server/ZkAdminManager.scala:159` | ZK mode topic creation |
| ZK Client | `AdminZkClient.createTopicWithAssignment()` | Core code | ZK write operation |
| Policy | `CreateTopicPolicy.validate()` | `clients/src/main/java/org/apache/kafka/server/policy/CreateTopicPolicy.java` | Custom validation |
| Controller | `ReplicationControlManager.createTopics()` | `metadata/src/main/java/org/apache/kafka/controller/ReplicationControlManager.java:587` | KRaft topic creation |
| Response | `CreateTopicsResponse` | `clients/src/main/java/org/apache/kafka/common/requests/CreateTopicsResponse.java` | Response to client |

### Topic Creation Configuration

Topic configuration is specified as key-value pairs:
- Cleanup policy (delete, compact)
- Retention settings (hours, bytes, ms)
- Compression type
- Min.insync.replicas
- etc.

These are validated against `LogConfig` and can be customized per topic.

---

## 4. Testing Framework

Kafka uses a comprehensive testing approach with multiple frameworks and patterns:

### Testing Frameworks

1. **JUnit 5 (Jupiter)** - Primary test framework
   - Used for all new tests
   - Supports parameterized testing, custom extensions
   - Configuration: `junit-platform.properties` files in test resources

2. **ScalaTest** - Legacy Scala test framework
   - Used for some older Scala tests
   - FunSuite, WordSpec styles
   - Being gradually migrated to JUnit 5

3. **Mockito** - Mocking framework
   - For mocking dependencies
   - Verification of interactions

### Test Annotations and Extensions

1. **`@ClusterTest`** - Single cluster configuration test
   - Runs test with one specific cluster configuration
   - Located in `core/src/test/java/kafka/test/annotation/ClusterTest.java`

2. **`@ClusterTests`** - Multiple cluster configurations
   - Runs same test with multiple cluster setups
   - Supports both ZK and KRaft modes

3. **`@ClusterTemplate`** - Dynamic cluster generation
   - Custom cluster configuration provider
   - For parameterized cluster testing

4. **`@ExtendWith(ClusterTestExtensions.class)`** - Test extension
   - JUnit 5 extension for cluster setup/teardown
   - Handles test invocation for multiple cluster configs
   - File: `core/src/test/java/kafka/test/junit/ClusterTestExtensions.java`

### Test Harnesses

1. **`IntegrationTestHarness`** (`core/src/test/scala/integration/kafka/api/IntegrationTestHarness.scala`)
   - Base class for integration tests
   - Manages Kafka cluster (ZK-based)
   - Sets up producers/consumers
   - Provides `brokerCount()` and broker access methods

2. **`KafkaServerTestHarness`** - Base test harness
   - Lower-level server test setup
   - Manual server creation and lifecycle control

3. **`QuorumTestHarness`** (`core/src/test/scala/integration/kafka/server/QuorumTestHarness.scala`)
   - Supports both ZK and KRaft test modes
   - Abstraction for cluster creation
   - Methods: `getControllerIdOpt()`, `waitForBrokersInMetadata()`, etc.

4. **`ClusterInstance`** - Test cluster representation
   - Injectable into test methods via JUnit 5 parameters
   - Provides methods to access brokers, admin clients, producers, consumers
   - File: `core/src/test/java/kafka/test/ClusterInstance.java`

### Example Test Pattern

```scala
@ExtendWith(Array(classOf[ClusterTestExtensions]))
class SomeTest {

  @ClusterTest(clusterSize = 3, brokerConfigs = [/* configs */])
  def testWithSpecificConfig(cluster: ClusterInstance): Unit = {
    // Test implementation
    cluster.brokers() // Access brokers
    cluster.bootstrapServers() // Get bootstrap servers
  }

  @ClusterTests(
    new ClusterTest(clusterSize = 1, types = [Type.ZK, Type.KRAFT])
  )
  def testOnBothModes(cluster: ClusterInstance): Unit = {
    // Runs on both ZK and KRaft modes
  }
}
```

### Unit vs Integration Tests

**Unit Tests** (`core/src/test/scala/unit/`):
- Test individual classes/methods in isolation
- Use mocks for dependencies
- Fast execution
- Located in parallel `core/src/test/` directory structure

**Integration Tests** (`core/src/test/scala/integration/`, `core/src/test/java/`):
- Start real Kafka clusters
- Test end-to-end functionality
- Use ClusterTestExtensions for setup
- Slower but more comprehensive

### Test Resources

- Configuration files: `core/src/test/resources/`
- Log4j config: `log4j.properties`
- JUnit Platform config: `junit-platform.properties`

### Running Tests

Tests are organized by:
- **Module**: Each module has `src/test/` directory
- **Language**: Scala tests in `scala/`, Java tests in `java/`
- **Category**: `unit/` vs `integration/`

---

## 5. Configuration System

Kafka has a comprehensive configuration system supporting static and dynamic broker configurations.

### Configuration Architecture

#### Configuration Definition

All configuration is defined in a centralized `ConfigDef` object:

1. **`AbstractKafkaConfig.CONFIG_DEF`** (`server/src/main/java/org/apache/kafka/server/config/AbstractKafkaConfig.java`)
   - Merges multiple configuration sources:
     - `RemoteLogManagerConfig.configDef()`
     - `ZkConfigs.CONFIG_DEF`
     - `ServerConfigs.CONFIG_DEF`
     - `KRaftConfigs.CONFIG_DEF`
     - `SocketServerConfigs.CONFIG_DEF`
     - `ReplicationConfigs.CONFIG_DEF`
     - `GroupCoordinatorConfig.GROUP_COORDINATOR_CONFIG_DEF`
     - `LogConfig.SERVER_CONFIG_DEF`
     - Transaction, Quota, Security configs, etc.

2. **`KafkaConfig`** (`core/src/main/scala/kafka/server/KafkaConfig.scala`)
   - Extends `AbstractKafkaConfig`
   - Provides typed getters for all configuration values
   - Created from `Properties` via `KafkaConfig.fromProps()`

#### Configuration Precedence Order

Broker configurations follow this precedence (highest to lowest):
1. **DYNAMIC_BROKER_CONFIG** - Per-broker dynamic config in ZK at `/configs/brokers/{brokerId}`
2. **DYNAMIC_DEFAULT_CONFIG** - Cluster-wide dynamic defaults in ZK at `/configs/brokers/<default>`
3. **STATIC_BROKER_CONFIG** - Values from `server.properties` file
4. **DEFAULT_CONFIG** - Hardcoded defaults in `KafkaConfig`

#### Configuration Sources

1. **Static Configuration** - `server.properties` file
   - Example: `config/server.properties`
   - Loaded at broker startup via `Utils.loadProps()`
   - Includes broker ID, ZooKeeper connect, port, log directory, replication factor defaults, etc.

2. **Dynamic Configuration** - ZooKeeper
   - Stored in ZK znodes under `/config/brokers/`
   - Can be updated without broker restart
   - Changes propagate via ZK watcher mechanism

### Configuration Management

#### Static Configuration Loading

```
main() -> Kafka.scala:50
  Utils.loadProps(args(0)) // Load server.properties
  KafkaConfig.fromProps(props)
```

#### Dynamic Configuration

1. **`DynamicBrokerConfig`** (`core/src/main/scala/kafka/server/DynamicBrokerConfig.scala`)
   - Manages dynamic configuration updates
   - Maintains in-memory cache of dynamic configs
   - Provides method to update and validate config changes
   - Notifies `Reconfigurable` components of changes

2. **Configuration Handlers** (`core/src/main/scala/kafka/server/ConfigHandler.scala`)
   - `BrokerConfigHandler` - Handles broker-level config changes
   - `TopicConfigHandler` - Handles topic-level config changes
   - `QuotaConfigHandler` - Handles quota changes
   - Implement callback interfaces for config updates

3. **ZooKeeper Watcher** - `ZkConfigManager`
   - Watches ZK config paths for changes
   - Triggers `ConfigHandler` callbacks when configs change
   - Updates run on dedicated threads to avoid blocking broker

### Configuration Validation

1. **At Startup**:
   - `AbstractConfig` validates all values against `ConfigDef`
   - Type checking, range validation, enum validation
   - Throws `ConfigException` on invalid values

2. **For Topic Configs**:
   - `LogConfig` validates topic-specific settings
   - `CreateTopicPolicy.validate()` allows custom validation logic
   - Supports synonyms (e.g., `log.roll.ms` vs `log.roll.hours`)

3. **For Dynamic Updates**:
   - `DynamicBrokerConfig.validateReconfiguration()` validates changes
   - Calls `validateReconfiguration()` on registered `Reconfigurable` components
   - Examples: SecurityConfigs, LogCleaner configs, Listener configs

### Important Configuration Classes

| Class | Location | Purpose |
|-------|----------|---------|
| `ConfigDef` | commons | Defines valid configs with types, defaults, validators |
| `AbstractKafkaConfig` | `server/src/main/java/org/apache/kafka/server/config/` | Base config class with merged CONFIG_DEF |
| `KafkaConfig` | `core/src/main/scala/kafka/server/` | Broker-specific config with typed getters |
| `DynamicBrokerConfig` | `core/src/main/scala/kafka/server/` | Dynamic config management |
| `ConfigHandler` | `core/src/main/scala/kafka/server/` | Callbacks for config changes |
| `LogConfig` | `storage/src/main/java/org/apache/kafka/storage/internals/log/` | Log/topic-specific configs |

### Configuration Examples

**Server Configuration Keys**:
- `broker.id` - Unique broker identifier
- `listeners` - Network endpoints to listen on
- `log.dirs` - Log storage directories
- `num.partitions` - Default partition count for auto-created topics
- `default.replication.factor` - Default replication factor
- `zookeeper.connect` - ZooKeeper connection string
- `log.retention.hours` - Log retention time
- `compression.type` - Message compression algorithm

**Topic Configuration Keys** (LogConfig):
- `cleanup.policy` - delete or compact
- `retention.ms` - Retention in milliseconds
- `retention.bytes` - Retention in bytes
- `segment.ms` - Log segment rollover time
- `min.insync.replicas` - Minimum ISR for acks=all
- `compression.type` - Compression algorithm

---

## 6. Adding a New Broker Config Parameter

If you need to add a new broker configuration parameter, follow these steps:

### Step 1: Define the Config in ConfigDef

**File**: `server/src/main/java/org/apache/kafka/server/config/ServerConfigs.java` (or appropriate config class)

```java
public class ServerConfigs {
    public static final String MY_NEW_CONFIG = "my.new.config";
    public static final String MY_NEW_CONFIG_DOC = "Description of what this config does";

    public static final ConfigDef CONFIG_DEF = new ConfigDef()
        .define(
            MY_NEW_CONFIG,
            ConfigDef.Type.INT,  // Type: INT, STRING, BOOLEAN, LIST, DOUBLE, LONG, CLASS, PASSWORD
            100,                  // Default value
            ConfigDef.Range.atLeast(0),  // Validator (optional)
            ConfigDef.Importance.MEDIUM, // Importance level
            MY_NEW_CONFIG_DOC
        );
}
```

### Step 2: Add Getter to KafkaConfig

**File**: `core/src/main/scala/kafka/server/KafkaConfig.scala`

```scala
val myNewConfig = getInt(ServerConfigs.MY_NEW_CONFIG)
```

Or for more complex types:
```scala
val myNewConfig: String = getString(ServerConfigs.MY_NEW_CONFIG)
```

### Step 3: Mark as Reconfigurable (if dynamic updates are needed)

If the config should support dynamic updates without broker restart:

**File**: `core/src/main/scala/kafka/server/DynamicBrokerConfig.scala`

```scala
object DynamicBrokerConfig {
  val DynamicMyConfigs = Set(ServerConfigs.MY_NEW_CONFIG)

  val AllDynamicConfigs = ... ++ DynamicMyConfigs
}
```

### Step 4: Implement Reconfigurable Component

Create or update a class that implements `Reconfigurable` interface:

```scala
class MyComponent extends Reconfigurable {
  override def reconfigure(configs: util.Map[String, _]): Unit = {
    val newValue = configs.get(ServerConfigs.MY_NEW_CONFIG)
    // Update internal state with new value
    updateInternalConfig(newValue)
  }

  override def validateReconfiguration(configs: util.Map[String, _]): Unit = {
    val value = configs.get(ServerConfigs.MY_NEW_CONFIG)
    if (value != null && !isValidValue(value)) {
      throw new ConfigException(s"Invalid value for ${ServerConfigs.MY_NEW_CONFIG}")
    }
  }

  override def reconfigurableConfigs(): util.Set[String] = {
    util.Collections.singleton(ServerConfigs.MY_NEW_CONFIG)
  }
}
```

### Step 5: Register Reconfigurable Component

In `KafkaServer.startup()` or appropriate initialization method:

```scala
private var myComponent: MyComponent = _

// In startup() method:
myComponent = new MyComponent(config)
// Register with DynamicBrokerConfig for dynamic updates
config.dynamicConfig.addReconfigurable(myComponent)
```

### Step 6: Add Validation (if needed)

For topic-level configs, update `LogConfig`:

**File**: `storage/src/main/java/org/apache/kafka/storage/internals/log/LogConfig.java`

### Step 7: Add Tests

#### Unit Test - Config Definition

**File**: `core/src/test/scala/unit/kafka/server/KafkaConfigTest.scala`

```scala
@Test
def testMyNewConfig(): Unit = {
  val props = createDefaultBrokerConfig()
  props.put(ServerConfigs.MY_NEW_CONFIG, "42")
  val config = KafkaConfig.fromProps(props)
  assertEquals(42, config.myNewConfig)
}

@Test
def testMyNewConfigInvalid(): Unit = {
  val props = createDefaultBrokerConfig()
  props.put(ServerConfigs.MY_NEW_CONFIG, "-1")
  assertThrows(classOf[ConfigException], () => KafkaConfig.fromProps(props))
}
```

#### Integration Test - Dynamic Update

**File**: `core/src/test/scala/unit/kafka/server/DynamicBrokerConfigTest.scala`

```scala
@Test
def testMyNewConfigDynamicUpdate(): Unit = {
  val config = createBrokerConfig()
  val dynamicConfig = new DynamicBrokerConfig(config)

  val newConfigs = Map(ServerConfigs.MY_NEW_CONFIG -> "99")
  dynamicConfig.updateDynamicConfig(newConfigs)

  assertEquals(99, dynamicConfig.currentKafkaConfig.myNewConfig)
}
```

### Step 8: Documentation

Update documentation files:
- **`docs/upgrade.html`** - If config changes behavior or is incompatible
- **`docs/configuration.html`** - Configuration reference
- **`README.md`** - If major feature

### Step 9: Update Build if Needed

If adding a new config class, ensure it's included in:
- **`build.gradle`** - Module dependencies
- **`settings.gradle`** - Module discovery

### Example: Complete Implementation

Let's say we're adding `broker.metadata.cache.size` to control metadata cache behavior:

1. **Define in ServerConfigs.java**:
```java
public static final String BROKER_METADATA_CACHE_SIZE = "broker.metadata.cache.size";
public static final String BROKER_METADATA_CACHE_SIZE_DOC = "Maximum size of broker metadata cache in MB";

CONFIG_DEF.define(
    BROKER_METADATA_CACHE_SIZE,
    ConfigDef.Type.INT,
    512,
    ConfigDef.Range.atLeast(100),
    ConfigDef.Importance.HIGH,
    BROKER_METADATA_CACHE_SIZE_DOC
);
```

2. **Add getter in KafkaConfig.scala**:
```scala
val brokerMetadataCacheSize = getInt(ServerConfigs.BROKER_METADATA_CACHE_SIZE)
```

3. **Mark as dynamic in DynamicBrokerConfig.scala**:
```scala
val DynamicMetadataConfigs = Set(ServerConfigs.BROKER_METADATA_CACHE_SIZE)
val AllDynamicConfigs = ... ++ DynamicMetadataConfigs
```

4. **Create Reconfigurable component** (if not already exists):
```scala
class MetadataCacheComponent extends Reconfigurable {
  override def reconfigure(configs: util.Map[String, _]): Unit = {
    val size = configs.get(ServerConfigs.BROKER_METADATA_CACHE_SIZE)
    metadataCache.setMaxSize(size)
  }
}
```

5. **Register in KafkaServer.startup()**:
```scala
metadataCacheComponent.reconfigure(config.originals)
config.dynamicConfig.addReconfigurable(metadataCacheComponent)
```

6. **Test**:
```scala
@Test
def testBrokerMetadataCacheSizeConfig(): Unit = {
  val props = createDefaultConfig()
  props.put(ServerConfigs.BROKER_METADATA_CACHE_SIZE, "1024")
  val config = KafkaConfig.fromProps(props)
  assertEquals(1024, config.brokerMetadataCacheSize)
}
```

### Key Principles for Config Implementation

1. **Type Safety** - Use appropriate ConfigDef.Type for validation
2. **Validation** - Implement validators for valid ranges/values
3. **Documentation** - Add DOC constants and update docs
4. **Backwards Compatibility** - Ensure old code still works
5. **Default Values** - Provide sensible defaults
6. **Dynamic vs Static** - Consider if update requires restart
7. **Testing** - Test both startup and dynamic update scenarios
8. **Reconfigurable** - Implement if config should support dynamic updates
9. **Error Handling** - Throw ConfigException on invalid values
10. **Performance** - Consider impact of config validation on startup time

