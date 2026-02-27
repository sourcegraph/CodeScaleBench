# Kafka Contributor Workflow Discovery

You are a new engineer who wants to contribute to the Apache Kafka project. Your goal is to understand the contributor workflow: how to build the codebase, run tests, understand the CI pipeline, and submit code for review.

Produce a **contributor guide** document at `/logs/agent/onboarding.md` that answers the following questions. Your document should be clear, specific, and actionable — focusing on the actual commands, tools, and processes used by Kafka contributors.

## Questions to Answer

### 1. Build Prerequisites
What tools and dependencies are required to build Kafka from source? Include specific version requirements if documented.

### 2. Gradle Build System
How does Kafka's Gradle build system work? What are the key Gradle commands for building the entire project, building specific modules, and understanding the module structure?

### 3. Running Tests
How do you run tests in Kafka? Cover:
- How to run all tests
- How to run tests for a specific module
- How to run a single test class or method
- What test frameworks are used (unit tests vs integration tests)

### 4. CI Pipeline
What CI system(s) does Kafka use? Where are the CI configuration files located, and what checks are run on pull requests?

### 5. Code Review Process
What is the process for submitting code changes to Kafka? Include:
- How to find and claim a JIRA ticket
- Branch naming conventions (if any)
- How to create a pull request
- Code review expectations (reviewers, approval process, formatting requirements)

### 6. Developer Workflow Example
Provide a step-by-step example workflow for a contributor who wants to fix a bug or add a small feature. Include the full sequence from finding an issue to getting it merged.

---

## Deliverable

Save your findings to `/logs/agent/onboarding.md`. Use any clear structure as long as all questions above are answered:

```
# Kafka Contributor Guide

## 1. Build Prerequisites

[Your answer here]

## 2. Gradle Build System

[Your answer here]

## 3. Running Tests

[Your answer here]

## 4. CI Pipeline

[Your answer here]

## 5. Code Review Process

[Your answer here]

## 6. Developer Workflow Example

[Your answer here]
```

Be specific about commands, file paths, and tools. Your guide should enable a new contributor to get started with confidence.
