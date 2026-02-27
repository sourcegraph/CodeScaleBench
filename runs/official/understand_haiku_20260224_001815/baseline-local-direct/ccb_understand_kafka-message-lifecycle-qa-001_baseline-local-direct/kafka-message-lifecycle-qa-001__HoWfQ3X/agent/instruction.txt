# Data Flow Q&A: Kafka Message Lifecycle

**Repository:** apache/kafka
**Task Type:** Data Flow Q&A (investigation only — no code changes)

## Background

Apache Kafka is a distributed event streaming platform where messages flow from producers through brokers to consumers. Understanding this end-to-end message lifecycle — including every transformation, buffering, and persistence step — is essential for working with Kafka's architecture.

## Task

Trace the complete path of a single message from the moment a producer calls `send()` through broker persistence and replication, to final delivery to a consumer via `poll()`. Identify every key transformation point, component boundary crossing, and state change.

## Questions

Answer ALL of the following questions about Kafka's message lifecycle:

### Q1: Producer-Side Batching and Transmission

When a producer calls `KafkaProducer.send(record)`, how does the message travel from application code to the network?

- What is the role of `RecordAccumulator` in batching messages?
- How does the `Sender` thread determine when a batch is ready to transmit?
- What triggers the actual network request to the broker?
- At what point are messages serialized and assigned to partitions?

### Q2: Broker-Side Append and Replication

When a produce request arrives at the broker, how is the message written to disk and replicated?

- Which component receives the produce request and routes it to the correct partition leader?
- How does `ReplicaManager` coordinate the append operation?
- What is the sequence of operations that writes the message to the local log?
- How does the broker replicate the message to follower replicas before acknowledging the producer?

### Q3: Consumer-Side Fetch and Delivery

When a consumer calls `poll()`, how does it retrieve messages from the broker?

- How does the `Fetcher` component build and send fetch requests?
- What happens when fetch responses arrive from the broker?
- How are messages deserialized and delivered to application code?
- At what point do offset commits occur relative to message delivery?

### Q4: End-to-End Transformation Points

Identify all transformation points in the message lifecycle where data format or representation changes:

- Where does serialization occur (producer-side)?
- Where does the message get wrapped in protocol-level framing (RecordBatch)?
- Where is the message persisted to disk on the broker?
- Where does deserialization occur (consumer-side)?

List these transformation points in order and explain what changes at each step.

## Output Requirements

Write your answer to `/logs/agent/investigation.md` with the following structure:

```
# Kafka Message Lifecycle

## Q1: Producer-Side Batching and Transmission
<answer with specific file paths, class names, and method references>

## Q2: Broker-Side Append and Replication
<answer with specific file paths, class names, and method references>

## Q3: Consumer-Side Fetch and Delivery
<answer with specific file paths, class names, and method references>

## Q4: End-to-End Transformation Points
<ordered list of transformation points with file/method references>

## Evidence
<consolidated list of supporting file paths and line references>
```

## Constraints

- Do NOT modify any source files
- Cite specific files, classes, and methods — avoid vague or speculative answers
- Focus on the core message path, not error handling or edge cases
- Trace a single non-transactional message with acks=all (full replication)
