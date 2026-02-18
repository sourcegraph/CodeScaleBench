# Onboarding Task: Apache Kafka Codebase Orientation

You are a new engineer joining the Apache Kafka project. Your first task is to explore the codebase and answer the following orientation questions. This will help you understand the project structure, architecture, and development practices.

## Task

Explore the Apache Kafka repository and answer the following questions. Write your findings to `/logs/agent/onboarding.md` with numbered answers corresponding to each question.

## Questions

1. **Build System and Broker Startup**: What build system does Kafka use, and what is the main entry point for starting a Kafka broker? Describe the key classes involved in broker initialization.

2. **Module Structure**: Kafka is organized into multiple modules/directories. What are the core modules and what are their primary responsibilities? Explain how the codebase is structured.

3. **Topic Creation Flow**: How does topic creation work end-to-end in Kafka? Trace the path from when a client creates a topic through the broker's request handling to the actual topic creation. What are the key classes and methods involved?

4. **Testing Framework**: What testing frameworks and patterns does Kafka use? How would you write tests for Kafka components (both unit tests and integration tests)?

5. **Configuration System**: How are broker configuration parameters defined and managed in Kafka? Where is the configuration registry located and how are config values validated?

6. **Adding a New Broker Config**: If you needed to add a new broker configuration parameter, what files would you modify and what steps would you follow? Include details about validation, dynamic updates, and testing.

## Deliverable

Write your answers to `/logs/agent/onboarding.md` in the following format:

```
# Apache Kafka Codebase Orientation

## 1. Build System and Broker Startup
[Your detailed answer with specific file paths and class names]

## 2. Module Structure
[Your detailed answer describing modules and their responsibilities]

## 3. Topic Creation Flow
[Your detailed answer tracing the request flow]

## 4. Testing Framework
[Your detailed answer about testing patterns]

## 5. Configuration System
[Your detailed answer about config management]

## 6. Adding a New Broker Config
[Your detailed answer with step-by-step process]
```

Be specific in your answers - include file paths, class names, method names, and explain the architectural patterns you discover.
