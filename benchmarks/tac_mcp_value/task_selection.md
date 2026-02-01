# TAC Task Selection for MCP Value Evaluation

This document explains the selection criteria and rationale for each curated TAC task
in this benchmark suite.

---

## Selection Criteria

Tasks were selected based on:

### 1. Code-Focused (Primary)

- Must involve reading, navigating, or modifying code
- Excludes pure "office workflow" tasks (spreadsheets, meeting scheduling)
- Prioritizes SDE (Software Development Engineer) role tasks

### 2. Cross-File Reasoning Required

- Tasks where understanding relationships across files matters
- Benefit from semantic search and call graph understanding
- Local grep/find insufficient for optimal solution

### 3. Deterministic Grading

- Preferably test-based evaluation (unit tests, integration tests)
- Avoid tasks requiring LLM-based evaluation where possible
- Clear pass/fail criteria

### 4. Minimal External Dependencies

- Can run with just GitLab server (most common TAC dependency)
- Avoid tasks requiring RocketChat NPC interactions for core completion
- Standalone execution preferred

### 5. Reasonable Complexity

- Not trivial (where any approach works)
- Not extremely complex (where time limit dominates)
- Sweet spot: 15-45 minute expected completion time

---

## Selected Tasks

### 1. sde-implement-hyperloglog

**TAC ID**: `sde-implement-hyperloglog`
**Docker Image**: `ghcr.io/theagentcompany/sde-implement-hyperloglog-image:1.0.0`

**Task Summary**: Clone bustub repository and implement HyperLogLog algorithm in C++.
Agent must implement 4 files following existing codebase patterns.

**MCP Value Hypothesis**:

- Understanding bustub's architecture and coding conventions
- Finding similar implementations in the codebase
- Understanding how other primer exercises are implemented
- Test file gives API hints, but implementation requires codebase understanding

**Grading**: Deterministic - 10 unit tests, scored by test pass count

**Dependencies**: GitLab only

**Rationale**: Complex implementation task that benefits from understanding the existing
codebase structure. An agent with MCP can search for similar implementations and understand
the expected patterns, while baseline must rely on local exploration only.

---

### 2. sde-implement-buffer-pool-manager-bustub

**TAC ID**: `sde-implement-buffer-pool-manager-bustub`
**Docker Image**: `ghcr.io/theagentcompany/sde-implement-buffer-pool-manager-bustub-image:1.0.0`

**Task Summary**: Implement buffer pool manager in bustub database system.
Agent must understand the existing codebase, follow issue instructions, and
implement components that integrate with existing code.

**MCP Value Hypothesis**:

- Buffer pool manager interacts with multiple components (disk manager, page guard, LRU)
- Understanding the dependency graph is critical
- Finding how other managers are implemented provides patterns

**Grading**: Deterministic - unit tests for buffer pool components

**Dependencies**: GitLab only

**Rationale**: Systems programming task requiring deep understanding of existing
architecture. Cross-file dependencies are significant. MCP semantic search
can quickly identify relevant components, while baseline must manually explore.

---

### 3. sde-dependency-change-1

**TAC ID**: `sde-dependency-change-1`
**Docker Image**: `ghcr.io/theagentcompany/sde-dependency-change-1-image:1.0.0`

**Task Summary**: Navigate to wiki to find OpenHands repo, clone it, and update
specific dependency versions in pyproject.toml and poetry.lock.

**MCP Value Hypothesis**:

- Finding the repository from documentation
- Understanding dependency specifications in the codebase
- Verifying no breaking changes from version updates

**Grading**: Deterministic - file content checks and poetry environment validation

**Dependencies**: GitLab + Wiki

**Rationale**: Real-world dependency management task. While seemingly simple,
understanding the dependency structure and verification steps benefits from
broader codebase understanding.

---

### 4. sde-find-answer-in-codebase-1

**TAC ID**: `sde-find-answer-in-codebase-1`
**Docker Image**: `ghcr.io/theagentcompany/sde-find-answer-in-codebase-1-image:1.0.0`

**Task Summary**: Search llama.cpp repository to find which PR improved the context
window for llama3.1 models. Report the PR number.

**MCP Value Hypothesis**:

- **Perfect test case for code search value**
- Requires searching through PR history and code changes
- Semantic understanding of "context window improvements" needed
- Local grep for keywords may miss semantic matches

**Grading**: LLM-based (checks RocketChat message for PR number)

**Dependencies**: GitLab + RocketChat

**Rationale**: Explicitly tests code navigation and search capabilities.
The task is to FIND information in a codebase - exactly what Sourcegraph
Deep Search excels at. Strong MCP advantage expected.

---

### 5. sde-find-answer-in-codebase-2

**TAC ID**: `sde-find-answer-in-codebase-2`
**Docker Image**: `ghcr.io/theagentcompany/sde-find-answer-in-codebase-2-image:1.0.0`

**Task Summary**: Another codebase navigation task requiring finding specific
information in a large repository.

**MCP Value Hypothesis**:

- Similar to task 1, tests semantic code search
- Different codebase, different query type

**Grading**: Similar to sde-find-answer-in-codebase-1

**Dependencies**: GitLab + RocketChat

**Rationale**: Second data point for code search tasks. Validates that
MCP advantage is consistent across different search queries.

---

### 6. sde-copilot-arena-server-new-endpoint

**TAC ID**: `sde-copilot-arena-server-new-endpoint`
**Docker Image**: `ghcr.io/theagentcompany/sde-copilot-arena-server-new-endpoint-image:1.0.0`

**Task Summary**: Clone copilot-arena-server, understand the existing API structure,
and add a new POST endpoint that mirrors an existing endpoint's response format.

**MCP Value Hypothesis**:

- Understanding existing endpoint implementation patterns
- Finding how create_pair endpoint works
- Understanding the API structure and return formats

**Grading**: Deterministic - server running check + API response validation

**Dependencies**: GitLab only

**Rationale**: API development task requiring understanding of existing patterns.
MCP can help quickly understand the create_pair implementation to mirror it.

---

### 7. sde-write-a-unit-test-for-search_file-function

**TAC ID**: `sde-write-a-unit-test-for-search_file-function`
**Docker Image**: `ghcr.io/theagentcompany/sde-write-a-unit-test-for-search_file-function-image:1.0.0`

**Task Summary**: Navigate to openhands repo, find the search_file function,
understand its behavior, and write a comprehensive unit test.

**MCP Value Hypothesis**:

- Finding the function implementation
- Understanding function behavior for test design
- Finding existing test patterns in the codebase

**Grading**: Deterministic - test execution and coverage validation

**Dependencies**: GitLab only

**Rationale**: Test writing requires deep understanding of function behavior.
MCP can help understand usage patterns and existing tests as examples.

---

### 8. sde-troubleshoot-dev-setup

**TAC ID**: `sde-troubleshoot-dev-setup`
**Docker Image**: `ghcr.io/theagentcompany/sde-troubleshoot-dev-setup-image:1.0.0`

**Task Summary**: Debug a broken development environment by finding requirements
in a GitLab repository and fixing version mismatches in myenv.txt.

**MCP Value Hypothesis**:

- Finding requirements documentation in repository
- Understanding version constraints
- Cross-referencing installed vs required versions

**Grading**: Mixed - file content check + RocketChat message

**Dependencies**: GitLab + RocketChat

**Rationale**: Debugging task requiring navigation of documentation and code.
Understanding the full requirements picture benefits from semantic search.

---

## Task Coverage Summary

| Task                                           | Primary Skill Tested | MCP Advantage | Grading       |
| ---------------------------------------------- | -------------------- | ------------- | ------------- |
| sde-implement-hyperloglog                      | Implementation       | High          | Deterministic |
| sde-implement-buffer-pool-manager-bustub       | Architecture         | High          | Deterministic |
| sde-dependency-change-1                        | Dependency mgmt      | Medium        | Deterministic |
| sde-find-answer-in-codebase-1                  | Code search          | **Very High** | LLM-based     |
| sde-find-answer-in-codebase-2                  | Code search          | **Very High** | LLM-based     |
| sde-copilot-arena-server-new-endpoint          | API development      | Medium-High   | Deterministic |
| sde-write-a-unit-test-for-search_file-function | Test writing         | High          | Deterministic |
| sde-troubleshoot-dev-setup                     | Debugging            | Medium        | Mixed         |

---

## Excluded Tasks (with Reasons)

### admin-\* tasks

- Focus on spreadsheet/document workflows
- Not code-focused
- MCP provides minimal value

### hr-_, finance-_, pm-\* tasks

- Role-specific non-coding tasks
- Heavy RocketChat/Plane dependencies
- Not suitable for code intelligence evaluation

### sde-run-\* tasks

- Execution-focused, not search/understanding focused
- Value comes from environment setup, not code understanding

### sde-close-_, sde-delete-_ tasks

- Administrative operations
- Deterministic but not code-understanding focused

### Heavy infrastructure tasks (janusgraph, etc.)

- Extremely long setup times
- Resource-intensive
- Complex dependencies

---

## Adding More Tasks

To add a new TAC task:

1. Identify the task in TAC workspaces/README.md
2. Verify the Docker image exists: `docker pull ghcr.io/theagentcompany/<task>-image:1.0.0`
3. Review task.md and evaluator.py in TAC source
4. Evaluate against selection criteria above
5. Add task wrapper using `scripts/import_tac_tasks.py`
6. Update this document with rationale
