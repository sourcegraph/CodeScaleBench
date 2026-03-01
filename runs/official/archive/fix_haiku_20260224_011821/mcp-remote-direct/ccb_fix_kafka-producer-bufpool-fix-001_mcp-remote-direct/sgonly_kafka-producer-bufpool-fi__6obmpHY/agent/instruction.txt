# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/kafka--be816b82`
- Use `repo:^github.com/sg-evals/kafka--be816b82$` filter in keyword_search
- Use `github.com/sg-evals/kafka--be816b82` as the `repo` parameter for go_to_definition/find_references/read_file


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

# big-code-kafka-bug-001: Kafka Producer Buffer Pool Reuse Race Condition

## Task

Investigate a bug in the Apache Kafka producer where a race condition in the `BufferPool` memory management causes messages to silently appear on the wrong topic. Trace the execution path from the producer's `send()` method through batch accumulation, buffer allocation, and network transmission to identify how buffer reuse can corrupt in-flight produce requests.

## Context

- **Repository**: github.com/sg-evals/kafka--be816b82 (mirror of apache/kafka) (Java, ~800K LOC)
- **Category**: Bug Investigation
- **Difficulty**: hard
- **Entry Point**: `clients/src/main/java/org/apache/kafka/clients/producer/internals/Sender.java` — `sendProducerData()` and `failBatch()` methods

## Symptom

Users of the Kafka producer with non-zero `linger.ms` observe that messages published to topic A occasionally appear on topic B instead. The corruption is rare but occurs in bursts, typically during broker restarts or network disruptions. The CRC checksum on the records passes because it covers only key/value/headers, not the topic name. The produce request header (containing topic/partition) is serialized separately from the message payload.

The bug is a race condition: when an in-flight `ProducerBatch` expires or its broker disconnects, the batch's pooled `ByteBuffer` is returned to the `BufferPool` and immediately reused by a new batch — while the original batch's request is still being written to the network by the `Sender` thread.

## Requirements

1. Starting from the entry point, trace the execution path to the root cause
2. Identify the specific file(s) and line(s) where the bug originates
3. Explain WHY the bug occurs (not just WHERE) — focus on the buffer lifecycle
4. Propose a fix with specific code changes

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```
## Files Examined
- path/to/file1.ext — examined for [reason]
- path/to/file2.ext — examined for [reason]
...

## Dependency Chain
1. Symptom observed in: path/to/symptom.ext
2. Called from: path/to/caller.ext (function name)
3. Bug triggered by: path/to/buggy.ext (function name, line ~N)
...

## Root Cause
- **File**: path/to/root_cause.ext
- **Function**: function_name()
- **Line**: ~N
- **Explanation**: [Why this code is buggy]

## Proposed Fix
```diff
- buggy code
+ fixed code
```

## Analysis
[Detailed trace from symptom to root cause, explaining each step]
```

## Evaluation Criteria

- Root cause identification: Did you find the correct file(s) where the bug originates?
- Call chain accuracy: Did you trace the correct path from symptom to root cause?
- Fix quality: Is the proposed fix correct and minimal?
