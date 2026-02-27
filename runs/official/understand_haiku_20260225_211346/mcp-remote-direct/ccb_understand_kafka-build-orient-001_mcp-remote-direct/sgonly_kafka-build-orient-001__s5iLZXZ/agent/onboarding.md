# Apache Kafka Codebase Orientation

## 1. Build System and Broker Startup

### Build System: Gradle

Apache Kafka uses **Gradle** as its build system. The main build files are located at:
- `build.gradle` - Root build configuration
- `settings.gradle` - Project structure definition
- `gradle/` - Gradle plugins and configuration

Key build plugins include:
- Java library plugin
- JaCoCo (code coverage)
- SpotBugs (static analysis)
- Swagger (API documentation)

### Main Entry Point: `kafka.Kafka` class

**File**: `core/src/main/scala/kafka/Kafka.scala`

The `main()` method (lines 87-128) is the entry point for starting a Kafka broker:

```scala
def main(args: Array[String]): Unit = {
  // 1. Parse command line arguments and load server.properties
  val serverProps = getPropsFromArgs(args)

  // 2. Determine mode (ZooKeeper or KRaft) and build appropriate server
  val server = buildServer(serverProps)

  // 3. Register signal handlers for graceful shutdown
  Exit.addShutdownHook("kafka-shutdown-hook", {
    server.shutdown()
  })

  // 4. Call startup() which initiates broker initialization
  server.startup()

  // 5. Block waiting for shutdown
  server.awaitShutdown()
}
```

### Key Initialization Classes

**KafkaServer** (`core/src/main/scala/kafka/server/KafkaServer.scala`)
- Main broker class for ZooKeeper mode brokers
- Extends `KafkaBroker` and `Server` traits
- Lifecycle: `NOT_RUNNING` → `STARTING` → `RECOVERY` → `RUNNING`

**KafkaRaftServer** (`core/src/main/scala/kafka/server/KafkaRaftServer.scala`)
- Main broker class for KRaft (KIP-500) mode brokers
- Contains both broker and controller components

**KafkaConfig** (`core/src/main/scala/kafka/server/KafkaConfig.scala`)
- Holds broker configuration loaded from server.properties
- Extends `AbstractKafkaConfig` from server module
- Manages both static and dynamic configurations

### Broker Initialization Flow (KafkaServer.startup())

The startup sequence (lines 216-600+) includes:

1. **ZooKeeper Initialization** (lines 230-235)
   - Initialize ZK client
   - Get or create cluster ID

2. **Metadata Loading** (lines 239-314)
   - Load metadata properties from log directories
   - Initialize meta.properties files for each log directory

3. **Background Services** (lines 270-286)
   - Start `KafkaScheduler` - background thread scheduler
   - Initialize metrics system
   - Create quota managers
   - Initialize log directory failure channel

4. **Log Manager** (lines 316-327)
   - Create and startup `LogManager` for managing log files
   - Sets broker state to `RECOVERY`
   - Loads existing topics from disk

5. **Metadata Cache** (lines 331-343)
   - Create `ZkMetadataCache` - in-memory metadata cache
   - Initialize feature change listener

6. **Security and Credentials** (lines 345-359)
   - Setup delegation token cache
   - Create credential provider
   - Initialize controller channel manager

7. **Network Layer** (lines 368-383)
   - Create `SocketServer` with acceptor threads
   - Setup request handlers

8. **Replica Manager** (lines 402-407)
   - Create and startup `ReplicaManager` for log replication
   - Register broker with ZooKeeper

9. **Controllers and Coordinators** (lines 413-570)
   - Startup `KafkaController` for cluster coordination
   - Startup `GroupCoordinator` for consumer groups
   - Startup `TransactionCoordinator` for transactions

10. **Request Processing** (lines 570-590)
    - Create `KafkaApis` for handling client requests
    - Create request handler pools
    - Startup socket server

### Key Classes in Broker Initialization

- **LogManager**: Manages all log segments for topics/partitions
- **ReplicaManager**: Handles replication between brokers, manages leaders/followers
- **KafkaController**: Elects partition leaders, handles topic/partition metadata
- **GroupCoordinator**: Manages consumer group coordination
- **TransactionCoordinator**: Manages transactions and producer IDs
- **SocketServer**: Network server handling client connections
- **KafkaApis**: Request handler routing different API requests to appropriate handlers


## 2. Module Structure

### Core Modules and Their Responsibilities

```
kafka-3.9.0/
├── core/                        # Main broker and client code
│   ├── src/main/scala/kafka/
│   │   ├── server/             # Broker server implementation
│   │   ├── controller/         # Cluster controller
│   │   ├── coordinator/        # Consumer group & transaction coordinators
│   │   ├── log/                # Log storage and management
│   │   └── zk/                 # ZooKeeper interactions
│   └── src/test/               # Unit and integration tests
│
├── server/                      # Server-specific abstractions (being refactored)
│   └── src/main/java/org/apache/kafka/server/config/
│       │── AbstractKafkaConfig  # Future home of KafkaConfig
│       ├── ServerConfigs        # Broker config definitions
│       ├── ServerLogConfigs     # Log config definitions
│       └── ZkConfigs            # ZooKeeper config definitions
│
├── clients/                     # Producer, Consumer, Admin clients
│   ├── Producer API
│   ├── Consumer API
│   └── Admin API
│
├── server-common/               # Common server utilities
│   └── src/main/java/org/apache/kafka/server/config/
│       ├── QuotaConfigs
│       ├── ReplicationConfigs
│       ├── ShareGroupConfig
│       └── DelegationTokenManagerConfigs
│
├── metadata/                    # KRaft controller and metadata management
│   ├── Metadata log handling
│   ├── Quorum controller
│   └── Replication control
│
├── group-coordinator/           # Group coordination (being refactored)
│
├── transaction-coordinator/     # Transaction coordination (being refactored)
│
├── storage/                     # Storage layer abstractions
│   └── Remote log storage support
│
├── streams/                     # Kafka Streams processing library
│
├── connect/                     # Kafka Connect framework
│
├── raft/                        # KRaft implementation (KIP-500)
│
├── tools/                       # Admin and debugging tools
│   ├── kafka-console-producer
│   ├── kafka-console-consumer
│   └── Other admin tools
│
└── tests/                       # System integration tests
    └── kafkatest/              # Python test harness
```

### Key Module Responsibilities

| Module | Responsibility |
|--------|-----------------|
| `core` | Main broker, controller, coordinators, log management, ZK integration |
| `server` | Shared broker configuration classes |
| `clients` | Producer, Consumer, Admin client implementations |
| `metadata` | KRaft metadata management and controller |
| `storage` | Storage layer abstractions including remote log storage |
| `raft` | KRaft consensus algorithm implementation |
| `streams` | Stream processing topology and topology processor |
| `connect` | Connectors framework for data integration |
| `tools` | Command-line tools for administration |

### Configuration Organization

**Static Configuration** (server.properties):
- Defined in `KafkaConfig.configDef` (ConfigDef object)
- Loaded on startup
- Cannot be changed without broker restart

**Dynamic Configuration**:
- Stored in ZooKeeper at `/configs/brokers/{brokerId}`
- Can be altered via AdminClient
- Applied immediately via `DynamicBrokerConfig` (`core/src/main/scala/kafka/server/DynamicBrokerConfig.scala`)
- Precedence: Per-broker > Cluster-wide defaults > Static > Default values


## 3. Topic Creation Flow

### End-to-End Topic Creation Path

```
Client (AdminClient)
    ↓
CreateTopicsRequest (proto: CreateTopicsRequest.json)
    ↓
KafkaApis.handleCreateTopicsRequest()
    ↓
[Authorization checks]
    ↓
AdminManager.createTopics()
    ↓
KafkaController.createTopic()
    ↓
[ZooKeeper writes]
    ↓
ReplicaManager.makeLeaders()
    ↓
Leader election and replication begins
    ↓
CreateTopicsResponse
```

### Request Entry Point

**File**: `core/src/main/scala/kafka/server/KafkaApis.scala` (lines 2001-2098)

```scala
def handleCreateTopicsRequest(request: RequestChannel.Request): Unit = {
  // 1. Get ZooKeeper support and enforce broker is controller
  val zkSupport = metadataSupport.requireZkOrThrow(...)

  // 2. Check if broker is the active controller
  if (!zkSupport.controller.isActive) {
    // Return NOT_CONTROLLER error
  }

  // 3. Authorization checks
  val hasClusterAuthorization = authHelper.authorize(request.context, CREATE, CLUSTER, ...)
  val authorizedTopics = authHelper.filterByAuthorized(request.context, CREATE, TOPIC, ...)

  // 4. Validation checks
  - Check for system topics (prohibited)
  - Check for duplicate topic names
  - Validate authorization

  // 5. Delegate to AdminManager
  zkSupport.adminManager.createTopics(
    createTopicsRequest.data.timeoutMs,
    createTopicsRequest.data.validateOnly,
    toCreate,  // Map[String, CreatableTopic]
    authorizedForDescribeConfigs,
    controllerMutationQuota,
    handleCreateTopicsResults)
}
```

### Topic Creation Request Data Structure

**File**: `clients/src/main/resources/common/message/CreateTopicsRequest.json`

```json
{
  "name": "CreateTopicsRequest",
  "topics": [
    {
      "name": "topic_name",
      "numPartitions": 3,
      "replicationFactor": 2,
      "assignments": [
        {
          "partitionIndex": 0,
          "brokerIds": [0, 1]
        }
      ],
      "configs": [
        {
          "name": "retention.ms",
          "value": "86400000"
        }
      ]
    }
  ],
  "timeoutMs": 30000,
  "validateOnly": false
}
```

### Topic Creation via AdminManager

**File**: `core/src/main/scala/kafka/server/ZkAdminManager.scala`

The `ZkAdminManager.createTopics()` method:

1. **Partition Assignment** - Determines broker assignments for each partition
2. **Topic Configuration** - Creates LogConfig from provided configs
3. **Topic Creation** - Writes topics to ZooKeeper
4. **Partition Leaders** - Triggers leader election via controller
5. **Result Handling** - Calls the callback with success/error results

### Controller Processing

**File**: `core/src/main/scala/kafka/controller/KafkaController.scala`

When topics are created:
1. Controller watches ZK `/config/topics` path for new topic entries
2. Triggers `TopicChangeHandler` for topic changes
3. Creates `TopicChange` event
4. Processes event and assigns partition leaders
5. Publishes leader info to brokers

### Key Classes and Methods

| Class | Method | Purpose |
|-------|--------|---------|
| `CreateTopicsRequest` | (data class) | Holds the request data |
| `KafkaApis` | `handleCreateTopicsRequest()` | Entry point for request handling |
| `AdminManager` | `createTopics()` | Orchestrates topic creation |
| `KafkaController` | `onTopicCreation()` | Handles topic creation events |
| `ReplicaManager` | `makeLeaders()` | Initializes partition leaders |
| `LogManager` | `createLog()` | Creates log segment files |


## 4. Testing Framework

### Testing Frameworks Used

Kafka uses multiple testing frameworks:

**Unit Testing:**
- **JUnit 5 (Jupiter)** - Primary test framework
  - Annotations: `@Test`, `@BeforeEach`, `@AfterEach`, `@Tag`
  - File: Tests in `*/src/test/java/` and `*/src/test/scala/`

- **ScalaTest** - For Scala code
  - Used for higher-level Scala unit tests
  - Supports property-based testing

**Integration Testing:**
- **Custom Test Harnesses** - For multi-broker cluster tests
  - `QuorumTestHarness` - Base class for ZK/KRaft tests
  - `IntegrationTestHarness` - For producer/consumer/broker integration
  - `KafkaServerTestHarness` - Multi-broker cluster fixture

- **JUnit 5 Extensions**
  - `ClusterTestExtensions` - Supports both ZK and KRaft modes
  - `ClusterTest` annotations for parameterized cluster testing

### Test Organization

```
core/src/test/
├── java/
│   ├── kafka/test/           # Test utilities
│   │   ├── junit/            # JUnit extensions and annotations
│   │   └── ClusterConfig     # Cluster configuration for tests
│   └── org/apache/kafka/...  # Java-based tests
│
└── scala/
    ├── unit/kafka/           # Unit tests
    ├── integration/kafka/     # Integration tests
    └── utils/                # Test utilities
```

### Running Tests

From `README.md` (lines 35-62):

```bash
# Run all unit and integration tests
./gradlew test

# Run only unit tests
./gradlew unitTest

# Run only integration tests
./gradlew integrationTest

# Run a specific test
./gradlew core:test --tests kafka.server.KafkaServerTest

# Run a specific test method
./gradlew core:test --tests kafka.server.KafkaServerTest.testBrokerStartup

# Run with verbose output
./gradlew test --info
```

### Writing Unit Tests

**File**: `core/src/test/scala/unit/kafka/server/KafkaServerTest.scala`

Example unit test pattern:

```scala
class KafkaServerTest extends QuorumTestHarness {

  @Test
  def testBrokerStartup(): Unit = {
    val props = TestUtils.createBrokerConfig(0, zkConnect)
    val config = KafkaConfig.fromProps(props)
    val server = new KafkaServer(config)

    try {
      server.startup()
      assertTrue(server.isStarted)
    } finally {
      server.shutdown()
    }
  }
}
```

### Writing Integration Tests

**File**: `core/src/test/scala/integration/kafka/api/IntegrationTestHarness.scala`

Example integration test pattern:

```scala
abstract class IntegrationTestHarness extends KafkaServerTestHarness {
  protected def brokerCount: Int

  @BeforeEach
  override def setUp(testInfo: TestInfo): Unit = {
    doSetup(testInfo, createOffsetsTopic = true)
  }

  @Test
  def testProduceAndConsume(): Unit = {
    // Create topic
    createTopic("test-topic", numPartitions = 3)

    // Produce messages
    val producer = createProducer()
    producer.send(new ProducerRecord("test-topic", "key", "value"))

    // Consume messages
    val consumer = createConsumer()
    consumer.subscribe(List("test-topic").asJava)
    val records = consumer.poll(Duration.ofSeconds(10))

    assertEquals(1, records.count())
  }
}
```

### Test Harness Features

**QuorumTestHarness** (`core/src/test/scala/integration/kafka/server/QuorumTestHarness.scala`):
- Sets up embedded ZooKeeper or KRaft cluster
- Provides methods to create topics and brokers
- Supports both ZK and KRaft modes
- Handles cleanup in `@AfterEach`

**ClusterTest Annotation** (`core/src/test/java/kafka/test/annotation/ClusterTest.java`):
- Parameterized cluster testing
- Supports both ZK and KRaft modes
- Custom cluster configurations
- Automatic test instantiation for each configuration

### System Integration Tests

**File**: `tests/README.md`

System tests are Python-based and located in `tests/`:
```bash
cd tests/
python3 setup.py test
```

These test full cluster scenarios including upgrades, performance, and edge cases.


## 5. Configuration System

### Configuration Definition

**Primary Config Location**: `server-common/src/main/java/org/apache/kafka/server/config/` and `core/src/main/scala/kafka/server/KafkaConfig.scala`

**Configuration Registry** is defined as a `ConfigDef` object in `KafkaConfig`:

```scala
val configDef = AbstractKafkaConfig.CONFIG_DEF
```

This is an instance of `org.apache.kafka.common.config.ConfigDef` which holds all broker configuration specifications.

### Configuration Definition Mechanism

Configs are defined using `ConfigDef.define()`:

```scala
configDef.define(
  name = "log.retention.ms",
  type = ConfigDef.Type.LONG,
  defaultValue = 604800000,  // 7 days in ms
  validator = ConfigDef.Range.atLeast(0),
  importance = ConfigDef.Importance.HIGH,
  documentation = "The maximum time in milliseconds before a log is eligible for deletion..."
)
```

### Configuration Levels and Precedence

**File**: `core/src/main/scala/kafka/server/DynamicBrokerConfig.scala` (lines 53-84)

Configuration precedence (highest to lowest):

1. **DYNAMIC_BROKER_CONFIG** - Per-broker dynamic config in ZK: `/configs/brokers/{brokerId}`
2. **DYNAMIC_DEFAULT_BROKER_CONFIG** - Cluster-wide defaults in ZK: `/configs/brokers/<default>`
3. **STATIC_BROKER_CONFIG** - Broker startup config (server.properties)
4. **DEFAULT_CONFIG** - Default values defined in ConfigDef

### Configuration Categories

**ServerConfigs** (`server-common/src/main/java/org/apache/kafka/server/config/ServerConfigs.java`):
- `broker.id` - Unique broker identifier
- `listeners` - Network endpoints
- `advertised.listeners` - Client-facing endpoints

**ServerLogConfigs** (`server-common/src/main/java/org/apache/kafka/server/config/ServerLogConfigs.java`):
- `log.dirs` - Directories for log segments
- `log.retention.ms` - Retention time
- `log.segment.bytes` - Segment size
- `log.cleanup.policy` - Retention policy (delete/compact)

**ReplicationConfigs**:
- `default.replication.factor` - Default replication factor
- `min.insync.replicas` - Minimum replicas in sync
- `unclean.leader.election.enable` - Allow out-of-sync leader election

**ZkConfigs** (for ZooKeeper mode):
- `zookeeper.connect` - ZooKeeper connection string
- `zk.session.timeout.ms` - ZK session timeout

**DynamicSecurityConfigs** (modifiable at runtime):
- SSL/TLS certificates
- SASL authentication settings
- ACL configurations

### Configuration Validation

Validation occurs in multiple places:

1. **ConfigDef Validators** - Built-in validators during config parsing
2. **KafkaConfig Constructor** - Custom validation logic
3. **Reconfigurable Implementations** - Components implement `Reconfigurable` interface

Example validator:
```scala
ConfigDef.Range.atLeast(0)      // Must be >= 0
ConfigDef.Range.between(1, 32)  // Must be between 1-32
ConfigDef.ValidString.in(...)   // Must be one of specified values
```

### Dynamic Configuration Updates

**File**: `core/src/main/scala/kafka/server/DynamicBrokerConfig.scala`

Dynamic configs are managed by `DynamicBrokerConfig`:

1. **Listener Registration** - Components implement `Reconfigurable` interface
2. **ZK Watch** - Watches `/configs/brokers/{brokerId}` and `/configs/brokers/<default>`
3. **Configuration Application** - Calls `reconfigure()` on registered listeners:
   ```scala
   trait Reconfigurable {
     def reconfigure(configs: util.Map[String, _]): Unit
     def validateReconfiguration(configs: util.Map[String, _]): Unit
   }
   ```
4. **Per-Component Updates** - Components like LogCleaner, SocketServer apply changes
5. **Metrics** - Configuration changes are tracked in metrics

### Configuration Sources

1. **server.properties file** - Static broker configuration at startup
2. **AdminClient API** - Dynamic configuration updates
   ```bash
   kafka-configs.sh --bootstrap-server localhost:9092 \
     --entity-type brokers --entity-name 0 \
     --alter --add-config "log.retention.ms=86400000"
   ```
3. **Command-line overrides** - `--override` option when starting broker
   ```bash
   kafka-server-start.sh server.properties \
     --override broker.id=1 \
     --override log.dirs=/data
   ```


## 6. Adding a New Broker Config

### Step-by-Step Process for Adding a New Config

Let's use an example: Adding a new config `custom.feature.timeout.ms` to control timeout for a custom feature.

#### Step 1: Define the Configuration in ConfigDef

**File**: `server-common/src/main/java/org/apache/kafka/server/config/ServerConfigs.java` (for new server configs)
**OR** `core/src/main/scala/kafka/server/KafkaConfig.scala` (for core-specific configs)

```scala
// In ServerConfigs.java or KafkaConfig.scala
val CUSTOM_FEATURE_TIMEOUT_MS_CONFIG = "custom.feature.timeout.ms"
val CUSTOM_FEATURE_TIMEOUT_MS_DEFAULT = 30000L
val CUSTOM_FEATURE_TIMEOUT_MS_DOC = """
  The timeout in milliseconds for the custom feature to complete operations.
  If the timeout is exceeded, the feature will abort the operation.
"""

configDef.define(
  CUSTOM_FEATURE_TIMEOUT_MS_CONFIG,
  ConfigDef.Type.LONG,
  CUSTOM_FEATURE_TIMEOUT_MS_DEFAULT,
  ConfigDef.Range.atLeast(1000),  // Minimum 1 second
  ConfigDef.Importance.MEDIUM,
  CUSTOM_FEATURE_TIMEOUT_MS_DOC
)
```

#### Step 2: Add Property Accessor in KafkaConfig Class

**File**: `core/src/main/scala/kafka/server/KafkaConfig.scala`

```scala
class KafkaConfig(...) extends AbstractKafkaConfig(...) {
  // Add getter method
  def customFeatureTimeoutMs: Long = {
    getLong(ServerConfigs.CUSTOM_FEATURE_TIMEOUT_MS_CONFIG)
  }

  // Or for SimpleConfigs
  val customFeatureTimeoutMs = getLong(CUSTOM_FEATURE_TIMEOUT_MS_CONFIG)
}
```

#### Step 3: Handle Dynamic Updates (if applicable)

If the config should be updatable at runtime, implement `Reconfigurable`:

**File**: Create or modify component file (e.g., `core/src/main/scala/kafka/server/CustomFeatureManager.scala`)

```scala
class CustomFeatureManager(config: KafkaConfig) extends Reconfigurable {

  @volatile private var timeoutMs = config.customFeatureTimeoutMs

  override def reconfigure(configs: util.Map[String, _]): Unit = {
    val newTimeoutMs = configs.get(CUSTOM_FEATURE_TIMEOUT_MS_CONFIG)
    if (newTimeoutMs != null) {
      this.timeoutMs = newTimeoutMs.asInstanceOf[Long]
      info(s"Updated customFeatureTimeoutMs to $timeoutMs")
    }
  }

  override def validateReconfiguration(configs: util.Map[String, _]): Unit = {
    val newTimeout = configs.get(CUSTOM_FEATURE_TIMEOUT_MS_CONFIG)
    if (newTimeout != null) {
      val timeout = newTimeout.asInstanceOf[Long]
      if (timeout < 1000) {
        throw new ConfigException(s"customFeatureTimeoutMs must be >= 1000")
      }
    }
  }

  def configNames: util.Collection[String] =
    Collections.singleton(CUSTOM_FEATURE_TIMEOUT_MS_CONFIG)
}
```

#### Step 4: Register for Dynamic Updates (if dynamic)

In `KafkaServer.startup()` (after component creation):

```scala
// File: core/src/main/scala/kafka/server/KafkaServer.scala
customFeatureManager = new CustomFeatureManager(config)

// Register for dynamic updates
if (config.dynamicConfig != null) {
  config.dynamicConfig.addBrokerReconfigurable(customFeatureManager)
}
```

#### Step 5: Inject Into Components

In the component that uses the config:

```scala
class MyComponent(kafkaConfig: KafkaConfig, scheduler: KafkaScheduler) {
  private val timeoutMs = kafkaConfig.customFeatureTimeoutMs

  def doOperation(): Unit = {
    scheduler.schedule(
      "my-operation",
      () => {
        // Use timeoutMs
        val deadline = System.currentTimeMillis() + timeoutMs
        // ... implementation
      },
      initialDelay = 0,
      period = timeoutMs
    )
  }
}
```

#### Step 6: Add Configuration to server.properties Example

**File**: `config/server.properties`

```properties
#############################
# Custom Feature Configuration
#############################

# The timeout in milliseconds for the custom feature.
# Default: 30000 (30 seconds)
#custom.feature.timeout.ms=30000
```

#### Step 7: Write Unit Tests

**File**: `core/src/test/scala/unit/kafka/server/CustomFeatureConfigTest.scala`

```scala
class CustomFeatureConfigTest {

  @Test
  def testCustomFeatureTimeoutMsDefault(): Unit = {
    val props = TestUtils.createBrokerConfig(0, "")
    val config = new KafkaConfig(props)
    assertEquals(30000, config.customFeatureTimeoutMs)
  }

  @Test
  def testCustomFeatureTimeoutMsOverride(): Unit = {
    val props = TestUtils.createBrokerConfig(0, "")
    props.put("custom.feature.timeout.ms", "60000")
    val config = new KafkaConfig(props)
    assertEquals(60000, config.customFeatureTimeoutMs)
  }

  @Test
  def testCustomFeatureTimeoutMsValidation(): Unit = {
    val props = TestUtils.createBrokerConfig(0, "")
    props.put("custom.feature.timeout.ms", "500")  // Invalid: < 1000
    assertThrows(classOf[ConfigException], () => new KafkaConfig(props))
  }
}
```

#### Step 8: Write Integration Tests for Dynamic Updates

**File**: `core/src/test/scala/integration/kafka/server/CustomFeatureDynamicConfigTest.scala`

```scala
class CustomFeatureDynamicConfigTest extends IntegrationTestHarness {
  protected def brokerCount: Int = 1

  @Test
  def testDynamicConfigUpdate(): Unit = {
    val broker = servers(0)
    assertEquals(30000, broker.config.customFeatureTimeoutMs)

    // Update via AdminClient
    val adminClient = createAdminClient()
    val configResource = new ConfigResource(ConfigResource.Type.BROKER, "0")
    val configEntry = new ConfigEntry("custom.feature.timeout.ms", "60000")
    adminClient.alterConfigs(
      Map(configResource -> new Config(List(configEntry).asJava)).asJava
    ).all().get()

    // Verify update was applied
    TestUtils.waitUntilTrue(
      () => broker.config.customFeatureTimeoutMs == 60000,
      "Config was not updated",
      maxWaitMs = 5000
    )
  }
}
```

#### Step 9: Register in Dynamic Config Set (if dynamic)

**File**: `core/src/main/scala/kafka/server/DynamicBrokerConfig.scala`

If your config should be dynamically updatable, add it to the appropriate set:

```scala
object DynamicBrokerConfig {
  // Add to appropriate config group
  private[server] val DynamicCustomFeatureConfigs = Set(
    CUSTOM_FEATURE_TIMEOUT_MS_CONFIG
  )

  val AllDynamicConfigs = DynamicSecurityConfigs ++
    LogCleaner.ReconfigurableConfigs ++
    DynamicLogConfig.ReconfigurableConfigs ++
    // ... other configs
    DynamicCustomFeatureConfigs  // Add here
}
```

#### Step 10: Documentation and Migration Notes

Update relevant documentation files:
- `docs/configuration.html` - Add config to documentation
- `docs/upgrade.html` - Add migration notes if changing existing configs
- Release notes - Document the new feature

#### Key Considerations

1. **Type Safety**: Use appropriate ConfigDef.Type (LONG, INT, STRING, LIST, BOOLEAN, DOUBLE)
2. **Validation**: Add range validators or custom validators
3. **Default Values**: Choose sensible defaults that work for most users
4. **Documentation**: Write clear documentation about the config's purpose
5. **Backward Compatibility**: Don't remove configs, deprecate them instead
6. **Dynamic vs. Static**:
   - Static configs: Require broker restart to take effect
   - Dynamic configs: Take effect immediately via admin APIs
7. **Testing**: Include unit tests, integration tests, and dynamic update tests
8. **Synonyms**: Use aliases for configs with multiple names (log.roll.ms vs log.roll.hours)

#### Testing Configuration Changes

```bash
# Describe current broker config
kafka-configs.sh --bootstrap-server localhost:9092 \
  --describe --entity-type brokers --entity-name 0

# Alter broker config dynamically
kafka-configs.sh --bootstrap-server localhost:9092 \
  --entity-type brokers --entity-name 0 \
  --alter --add-config "custom.feature.timeout.ms=60000"

# Verify the change
kafka-configs.sh --bootstrap-server localhost:9092 \
  --describe --entity-type brokers --entity-name 0 \
  --entity-name 0
```
