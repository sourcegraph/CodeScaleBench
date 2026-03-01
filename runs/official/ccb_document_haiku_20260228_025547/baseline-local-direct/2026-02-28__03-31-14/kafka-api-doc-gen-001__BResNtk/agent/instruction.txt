# Task: Generate API Reference Documentation for Kafka KafkaConsumer

## Objective

Generate comprehensive API reference documentation for the Apache Kafka `KafkaConsumer` Java API. The documentation should cover the complete API surface with emphasis on behavioral semantics, offset management strategies, rebalancing mechanics, and error handling patterns.

## Scope

Your documentation should cover the **KafkaConsumer API** from the `org.apache.kafka.clients.consumer` package, including:

1. **Core Consumer Lifecycle**
   - Constructor variants and configuration
   - Subscription methods (dynamic and manual assignment)
   - Polling and data fetching semantics
   - Resource cleanup and closing

2. **Offset Management**
   - Synchronous and asynchronous commit strategies
   - Offset queries and position control
   - Seek operations and offset discovery
   - Committed offset semantics

3. **Consumer Group Mechanics**
   - ConsumerRebalanceListener interface and callbacks
   - Rebalance triggers and timing
   - Group membership and heartbeat behavior
   - Partition assignment vs subscription models

4. **Flow Control and Position Management**
   - Pause and resume functionality
   - Position queries and manipulation
   - Offset-to-timestamp lookups
   - Beginning and end offset discovery

5. **Error Handling**
   - Exception types and recovery strategies
   - CommitFailedException and group fencing
   - WakeupException and thread interruption
   - Timeout and authentication errors

## Requirements

### API Methods Documentation (40%)

Document all public methods of the `KafkaConsumer` class with:
- Method signatures including all overloads
- Parameter semantics and validation rules
- Return types and their meanings
- Exception types thrown and conditions

### Behavioral Notes (30%)

Explain critical behavioral semantics:
- **poll() blocking behavior**: when it returns immediately vs when it blocks, timeout handling, rebalance callback execution during poll
- **Offset commit semantics**: difference between sync/async commits, retry behavior, commit failure handling
- **Rebalance coordination**: when rebalances occur (only during poll), callback ordering (revoked then assigned), partition ownership guarantees
- **Thread safety**: which methods are thread-safe, wakeup() special case, event loop model
- **Group membership**: max.poll.interval.ms enforcement, proactive leave behavior, session timeout vs poll timeout
- **Manual vs dynamic assignment**: mutually exclusive nature, use cases for each model
- **Position vs committed offset**: the off-by-one relationship ("committed should be next offset to read")
- **Transactional semantics**: read_committed isolation level, LSO boundary, filtered messages

### Usage Examples (20%)

Provide concrete code examples demonstrating:
- **Basic subscription and polling loop**: subscribe to topics, poll for records, process messages
- **Manual offset commit**: disable auto-commit, explicit commitSync/commitAsync after processing
- **Rebalance listener**: implement ConsumerRebalanceListener, commit offsets on revoke, initialize positions on assign
- **Seek operations**: seekToBeginning, seekToEnd, seek to specific offset, timestamp-based seeking
- **Multi-threaded processing pattern**: single consumer thread with pause/resume coordination and worker pool

### Documentation Structure (10%)

Organize documentation with clear sections:
- Overview and threading model
- Core types (KafkaConsumer, ConsumerRebalanceListener, ConsumerRecords, etc.)
- Subscription and assignment methods
- Polling and data fetching
- Offset management methods
- Flow control and position queries
- Metadata and monitoring
- Lifecycle and resource management
- Exception handling guide
- Configuration-driven behaviors
- Common patterns and best practices

## Deliverable

Write your documentation to `/workspace/documentation.md` in Markdown format.

## Notes

- Focus on **behavioral semantics** that aren't obvious from method signatures alone
- Include edge cases and gotchas (e.g., poll may block longer than timeout during rebalance callbacks)
- Explain the relationship between different offset concepts (position, committed, beginning, end, LSO)
- Cover both group-managed and standalone consumer patterns
- Document configuration properties that significantly affect API behavior
- Use the codebase to find real usage patterns in tests and internal components

## Evaluation

Your documentation will be evaluated on:
1. **Completeness**: All key API methods and types documented
2. **Accuracy**: Behavioral descriptions match actual implementation
3. **Clarity**: Complex semantics explained clearly with examples
4. **Practical value**: Real-world usage patterns and error handling strategies included
