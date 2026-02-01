# LoCoBench-Agent Task

## Overview

**Task ID**: cpp_data_analytics_expert_010_architectural_understanding_expert_01
**Category**: architectural_understanding
**Difficulty**: expert
**Language**: cpp
**Context Length**: 938016 tokens
**Files**: 82

## Task Title

Diagnose and Resolve Alerting Latency Under Concurrent Workloads

## Description

The CardioInsight360 system is experiencing a critical performance degradation issue in production. The system is designed to handle two primary, concurrent workloads: (1) Real-time ingestion and processing of HL7 data streams for critical patient event alerting, and (2) Large-scale, scheduled batch ETL jobs for populating the analytics data lake. Operators have reported that when a large batch job is running, the latency for real-time alerts increases by 300-500%, violating service-level agreements (SLAs). This delay poses a risk to patient safety. The issue is suspected to be architectural, stemming from resource contention between the two workloads.

## Your Task

As the lead architect, your task is to analyze the CardioInsight360 architecture to diagnose the root cause of the real-time alerting latency and propose a robust, minimally invasive solution. You must provide a detailed technical plan that a senior developer could implement.

Your analysis and proposal must include:
1.  **Architectural Trace:** Identify and describe the complete component paths for both the real-time alerting workload (from HL7 ingestion to alert dispatch) and the batch processing workload. Reference specific components, classes, and architectural documents.
2.  **Root Cause Hypothesis:** Based on your trace and analysis of the code, formulate a precise hypothesis explaining the resource contention. Pinpoint the specific shared resources (e.g., CPU, I/O, thread pools, event bus capacity) and the components responsible for the contention.
3.  **Solution Proposal:** Propose a specific, targeted architectural modification to mitigate the issue. Your proposal must detail:
    a. The conceptual change (e.g., workload prioritization, resource partitioning).
    b. A list of the primary files and classes that will need to be modified.
    c. A high-level description of the changes required in each file.
    d. An explanation of how your solution will resolve the contention while minimizing impact on the existing system.

## Expected Approach

An expert developer would approach this task systematically:
1.  **Information Gathering:** The first step is to build a mental model of the system's data flow. They would start by reviewing the architecture documentation: `docs/architecture/data_flow_diagram.md`, `docs/architecture/sequence_diagrams.md`, and `docs/architecture/README.md` to get a high-level overview.
2.  **Trace the Real-Time Path:** They would trace the code from `ingestion/connectors/hl7_mllp_connector.cpp`, through the `ingestion/ingestion_service.cpp`, to the `event_bus/event_bus_facade.cpp`. They would then follow the event to the consumer, `processing/stream_processor.cpp`, which processes the data and may generate a new event for the `services/alerting_service.cpp`.
3.  **Trace the Batch Path:** They would start at the `services/scheduling_service.cpp`, which triggers the `processing/batch_processor.cpp`. The core of this path is the `processing/etl_pipeline.cpp`, which involves multiple heavy transformation strategies (`transformation_strategy.cpp`, `quality_check_strategy.cpp`) and finally writes to the `storage/data_lake_facade.cpp`.
4.  **Identify Contention Points:** By comparing the two paths, the expert would identify potential areas of conflict:
    - **CPU Contention:** Both `StreamProcessor` and `ETLPipeline` are CPU-intensive. The `ServiceManager` (`services/service_manager.cpp`) appears to start all services without explicit resource partitioning, meaning they likely compete for the same system-wide CPU resources and threads.
    - **I/O Contention:** The `ETLPipeline` writing large Parquet files via `DataLakeFacade` could create I/O pressure that slows down other parts of the system, including the event bus if it's disk-backed (like Kafka).
    - **Event Bus Contention:** While less likely to be the primary cause, a flood of events from the batch process could theoretically impact the real-time event delivery if topics are not properly isolated.
5.  **Formulate Hypothesis:** The most likely hypothesis is that the compute-heavy `ETLPipeline`, when running, starves the time-sensitive `StreamProcessor` of CPU cycles because there is no mechanism for workload prioritization in the current architecture. The `ServiceManager` treats all services as equal.
6.  **Develop Solution:** The expert would propose introducing dedicated, prioritized resource pools. They would avoid a naive 'add more servers' solution. The plan would involve:
    - Modifying `main_config.json.template` to define named thread pools with different sizes and priorities (e.g., `realtime_pool`, `batch_pool`).
    - Updating `ConfigManager` to parse this new configuration.
    - Refactoring `ServiceManager` to create and manage these named thread pools.
    - Modifying the constructors or initializers of `StreamProcessor` and `BatchProcessor` to accept a reference to a specific thread pool from the `ServiceManager`.
    - Ensuring the real-time path components are assigned to the high-priority, low-latency pool and the batch components are assigned to the lower-priority, high-throughput pool. This isolates the critical path from resource-hungry but less time-sensitive tasks.

## Evaluation Criteria

- **Correct Component Identification:** Accurately identifies the key classes and components in both the real-time and batch processing data flows (e.g., `HL7MLLPConnector`, `StreamProcessor`, `AlertingService` vs. `SchedulingService`, `BatchProcessor`, `ETLPipeline`).
- **Accurate Hypothesis:** Correctly diagnoses resource contention (primarily CPU) as the root cause, citing the lack of workload prioritization in the `ServiceManager` as the specific architectural flaw.
- **Architectural Soundness of Solution:** Proposes a robust solution like dedicated thread pools rather than naive fixes (e.g., 'increase server CPU' or 'add random delays'). The solution should be extensible and maintainable.
- **Feasibility and Specificity:** The proposal must be concrete, listing the specific files (`service_manager.cpp`, `main_config.json.template`, etc.) and the nature of the changes required for each.
- **Synthesis of Information:** Demonstrates the ability to connect information from multiple sources, such as correlating the flow in `data_flow_diagram.md` with the implementation in `service_manager.cpp` and `etl_pipeline.cpp`.
- **Minimal Invasiveness:** The proposed solution should respect the existing architecture and patterns, modifying them gracefully rather than suggesting a complete redesign.

## Instructions

1. Explore the codebase in `/app/project/` to understand the existing implementation
2. Use MCP tools for efficient code navigation and understanding
3. **IMPORTANT**: Write your solution to `/logs/agent/solution.md` (this path is required for verification)

Your response should:
- Be comprehensive and address all aspects of the task
- Reference specific files and code sections where relevant
- Provide concrete recommendations or implementations as requested
- Consider the architectural implications of your solution

## MCP Search Instructions (if using Sourcegraph/Deep Search)

When using MCP tools to search the codebase, you MUST specify the correct repository:

**Repository**: `sg-benchmarks/locobench-cpp_data_analytics_expert_010`

Example MCP queries:
- "In sg-benchmarks/locobench-cpp_data_analytics_expert_010, where is the main entry point?"
- "Search sg-benchmarks/locobench-cpp_data_analytics_expert_010 for error handling code"
- "In sg-benchmarks/locobench-cpp_data_analytics_expert_010, how does the authentication flow work?"

**IMPORTANT**: Always include the full repository path `sg-benchmarks/locobench-cpp_data_analytics_expert_010` in your MCP search queries to ensure you're searching the correct codebase.

## Output Format

**CRITICAL**: Write your complete solution to `/logs/agent/solution.md` (NOT `/app/solution.md`). Include:
- Your analysis and reasoning
- Specific file paths and code references
- Any code changes or implementations (as applicable)
- Your final answer or recommendations
