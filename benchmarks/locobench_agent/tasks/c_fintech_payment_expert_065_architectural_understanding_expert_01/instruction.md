# LoCoBench-Agent Task

## Overview

**Task ID**: c_fintech_payment_expert_065_architectural_understanding_expert_01
**Category**: architectural_understanding
**Difficulty**: expert
**Language**: c
**Context Length**: 886345 tokens
**Files**: 75

## Task Title

Architectural Design for Cross-Service Tuition Auto-Payment

## Description

EduPay Ledger Academy is a sophisticated FinTech platform designed to manage all financial operations for a university. The system is built in C and employs a microservices architecture, with key services for the Bursar's Office (`bursar_service`) and the Financial Aid Office (`financial_aid_service`). The architecture heavily relies on advanced patterns including Clean Architecture, CQRS with Event Sourcing, and the Saga pattern for managing distributed transactions across services. A new feature is requested: 'Tuition Auto-Payment'. This feature should automatically apply a student's newly disbursed financial aid stipend towards their outstanding tuition balance, but only if the student has explicitly opted in. The challenge is to design a solution that seamlessly integrates this cross-service functionality while upholding the system's strict architectural principles of consistency, reliability, and regulatory compliance.

## Your Task

As a senior software architect for the EduPay Ledger Academy project, you are tasked with creating a detailed architectural proposal for the new 'Tuition Auto-Payment' feature. Your proposal should be a technical markdown document that outlines how to implement this feature without violating the existing architectural patterns.

Your proposal must address the following points:

1.  **Interaction Diagram/Sequence:** Describe the step-by-step flow of communication between the `financial_aid_service`, the `bursar_service`, and any other relevant components. Detail the sequence of commands, events, and queries.
2.  **Saga Pattern Integration:** Explain how the Saga pattern will be used to manage the distributed transaction. Will you extend an existing saga (like the one in `disburse_stipend_saga.c`) or create a new one? Justify your choice and describe the saga's steps, including any necessary compensating actions.
3.  **New Domain Events:** Define the new domain events required for this feature (e.g., for successful application, failure, etc.). Specify which service would publish these events and which services would consume them.
4.  **CQRS/Event Sourcing Impact:** Detail how this new workflow will be recorded in the event store. Explain which aggregates in the `bursar_service` (e.g., `Account`, `Ledger`) would be affected. Also, describe how the `projections_service` would need to be updated to reflect these auto-payments in its read models (e.g., for student dashboards).
5.  **Compliance and Consent:** Referencing the principles in `docs/architecture/05_security_and_compliance.md` and `docs/lessons/L03_Regulatory_Compliance_in_Code.md`, explain how your design handles the student's opt-in consent. Where would this consent flag be stored and how would it be checked in the workflow?
6.  **Affected Components:** List the key files and components (e.g., specific use cases, handlers, domain models, infrastructure) that would require modification to implement your design.

## Expected Approach

An expert developer would begin by thoroughly reviewing the existing architecture documentation, especially `02_microservices_and_bounded_contexts.md`, `03_cqrs_and_event_sourcing.md`, and `04_saga_pattern.md`. They would recognize that this is a classic distributed transaction problem perfectly suited for the existing Saga pattern.

The developer would inspect `financial_aid_service/application/use_cases/disburse_stipend_saga.c` to understand how stipends are currently processed. They would identify that the `StipendDisbursed` event, published via RabbitMQ (`rabbitmq_publisher.c`), is the logical trigger for the new functionality.

Their proposed design would likely extend the existing `DisburseStipendSaga` rather than creating a new one, arguing that applying funds to tuition is part of the overall stipend disbursement process. This keeps the transaction context unified.

The proposal would outline a new step in the saga that occurs after the stipend is successfully disbursed. This step would issue a command, like `ApplyStipendToTuition`, to the `bursar_service`. Before issuing the command, the saga coordinator would first need to query a read model to check for two conditions: (1) the student's opt-in status and (2) an outstanding balance. This query would target a projection maintained by the `projections_service` or a query endpoint on the `bursar_service`.

The design would define new events like `StipendAppliedToTuition` and `StipendApplicationToTuitionFailed`. It would also define a compensating action, `ReverseTuitionApplication`, for the saga in case a subsequent step fails.

Finally, the developer would trace the impact through the system: the `bursar_service` command handler would update the `Account` and `Ledger` aggregates, persisting the new events to the `postgres_event_store`. The `projections_service` would need a new event handler in a file like `dashboard_projector.c` to consume the `StipendAppliedToTuition` event and update the student's account balance projection.

## Evaluation Criteria

- **Pattern Adherence:** Correctly identifies and proposes extending the existing Saga pattern, respecting the CQRS/ES flow.
- **Component Identification:** Accurately identifies the roles of `financial_aid_service`, `bursar_service`, `projections_service`, and the Saga Coordinator.
- **Data Flow Correctness:** Proposes a logical and correct sequence of events, commands, and queries, including the crucial pre-condition check.
- **Event Design:** Defines specific and meaningful new domain events appropriate for the feature.
- **Compliance Integration:** Explicitly addresses the student consent requirement and correctly places the check in the workflow, referencing the compliance documentation.
- **Codebase Awareness:** Demonstrates understanding of the codebase by correctly identifying key files/modules that would need modification (e.g., `disburse_stipend_saga.c`, `dashboard_projector.c`).
- **Justification Quality:** Provides clear reasoning for architectural decisions, such as choosing to extend the existing saga versus creating a new one.

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

**Repository**: `sg-benchmarks/locobench-c_fintech_payment_expert_065`

Example MCP queries:
- "In sg-benchmarks/locobench-c_fintech_payment_expert_065, where is the main entry point?"
- "Search sg-benchmarks/locobench-c_fintech_payment_expert_065 for error handling code"
- "In sg-benchmarks/locobench-c_fintech_payment_expert_065, how does the authentication flow work?"

**IMPORTANT**: Always include the full repository path `sg-benchmarks/locobench-c_fintech_payment_expert_065` in your MCP search queries to ensure you're searching the correct codebase.

## Output Format

**CRITICAL**: Write your complete solution to `/logs/agent/solution.md` (NOT `/app/solution.md`). Include:
- Your analysis and reasoning
- Specific file paths and code references
- Any code changes or implementations (as applicable)
- Your final answer or recommendations
