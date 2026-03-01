# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/kafka--0753c489`
- Use `repo:^github.com/sg-evals/kafka--0753c489$` filter in keyword_search
- Use `github.com/sg-evals/kafka--0753c489` as the `repo` parameter for go_to_definition/find_references/read_file


## Required Workflow

1. **Search first** — Use MCP tools to find relevant files and understand existing patterns
2. **Read remotely** — Use `sg_read_file` to read full file contents from Sourcegraph
3. **Edit locally** — Use Edit, Write, and Bash to create or modify files in your working directory
4. **Verify locally** — Run tests with Bash to check your changes

## Tool Selection

| Goal | Tool |
|------|------|
| Exact symbol/string | `sg_keyword_search` |
| Concepts/semantic search | `sg_nls_search` |
| Trace usage/callers | `sg_find_references` |
| See implementation | `sg_go_to_definition` |
| Read full file | `sg_read_file` |
| Browse structure | `sg_list_files` |
| Find repos | `sg_list_repos` |
| Search commits | `sg_commit_search` |
| Track changes | `sg_diff_search` |
| Compare versions | `sg_compare_revisions` |

**Decision logic:**
1. Know the exact symbol? → `sg_keyword_search`
2. Know the concept, not the name? → `sg_nls_search`
3. Need definition of a symbol? → `sg_go_to_definition`
4. Need all callers/references? → `sg_find_references`
5. Need full file content? → `sg_read_file`

## Scoping (Always Do This)

```
repo:^github.com/ORG/REPO$           # Exact repo (preferred)
repo:github.com/ORG/                 # All repos in org
file:.*\.ts$                         # TypeScript only
file:src/api/                        # Specific directory
```

Start narrow. Expand only if results are empty.

## Efficiency Rules

- Chain searches logically: search → read → references → definition
- Don't re-search for the same pattern; use results from prior calls
- Prefer `sg_keyword_search` over `sg_nls_search` when you have exact terms
- Read 2-3 related files before synthesising, rather than one at a time
- Don't read 20+ remote files without writing code — once you understand the pattern, start implementing

## If Stuck

If MCP search returns no results:
1. Broaden the search query (synonyms, partial identifiers)
2. Try `sg_nls_search` for semantic matching
3. Use `sg_list_files` to browse the directory structure
4. Use `sg_list_repos` to verify the repository name

---

# Data Flow Q&A: Kafka Message Lifecycle

**Repository:** github.com/sg-evals/kafka--0753c489 (mirror of apache/kafka)
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
