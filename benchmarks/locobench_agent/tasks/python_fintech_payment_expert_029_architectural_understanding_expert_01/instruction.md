# LoCoBench-Agent Task

## Overview

**Task ID**: python_fintech_payment_expert_029_architectural_understanding_expert_01
**Category**: architectural_understanding
**Difficulty**: expert
**Language**: python
**Context Length**: 907679 tokens
**Files**: 81

## Task Title

Architectural Refactoring for Instant Payment Settlements

## Description

CrowdPay Connect's business team wants to introduce a new premium feature: "Instant Settlements". This feature will allow select users to have their transactions settled in near real-time by integrating with a new third-party provider, 'InstaPay'. This contrasts with the platform's current settlement process, which is an asynchronous, multi-step workflow designed for resilience and standard settlement timelines (T+2 days). This new requirement challenges the existing architectural patterns, particularly the distributed transaction management handled by the payment Saga.

## Your Task

As a lead architect, you are tasked with designing the integration of the 'Instant Settlement' feature. Your analysis must result in a clear architectural proposal. You are not required to write production code, but you must provide a detailed plan that demonstrates a deep understanding of the existing system.

Your proposal, delivered as a single markdown file named `INSTANT_SETTLEMENT_PROPOSAL.md`, must include:

1.  **Analysis of the Current Architecture:** Briefly explain how the standard payment settlement process works, identifying the key services (`transaction_service`, `wallet_service`, `risk_compliance_service`) and the architectural patterns used (e.g., Saga). Reference specific files that inform your analysis.

2.  **Proposed Solution:** Describe your proposed architecture for the 'Instant Settlement' flow. This must detail:
    a.  How the `transaction_service` will decide whether to trigger a standard or an instant settlement.
    b.  The proposed interaction with the external 'InstaPay' API. Will this be synchronous or asynchronous? How does this fit into the existing event-driven system?
    c.  The necessary modifications or additions to the `transaction_service`, specifically addressing its interaction with the `payment_saga`. Should the existing Saga be modified, or should a new pattern be used for the instant path?
    d.  The impact on the `wallet_service`'s ledger. How will the ledger be updated upon a successful instant settlement while maintaining data integrity and consistency, especially considering its likely event-sourced nature?
    e.  The required changes for the `risk_compliance_service` to support potentially different risk rules for high-speed transactions.

3.  **Failure Handling:** Describe the compensation/rollback strategy if the 'InstaPay' API call fails after the funds have been reserved in the user's wallet.

4.  **Sequence Diagram:** Provide a sequence diagram (using Mermaid syntax) illustrating the complete end-to-end flow for a successful 'Instant Settlement' transaction.

## Expected Approach

An expert developer would approach this task by first performing a thorough discovery phase to understand the existing system before proposing any changes.

1.  **Discovery & Analysis:**
    *   Start by reading the high-level architecture documents: `docs/architecture/overview.md`, `docs/architecture/saga_pattern.md`, and `docs/architecture/cqrs_event_sourcing.md`.
    *   Trace the standard payment flow by examining the `transaction_service`. Key files are `app/sagas/payment_saga.py` and `app/events/saga_coordinator.py`. This will reveal the steps: Reserve Funds, Assess Risk, Process Payment, etc.
    *   Analyze the consumers in other services to see how they participate in the saga, e.g., `wallet_service/app/events/consumer.py` (to handle fund reservation) and the `risk_compliance_service`.
    *   Examine the `wallet_service/app/core/ledger.py` to understand its immutable, append-only design, confirming the importance of event-driven updates rather than direct state mutation.
    *   Recognize that the current system is built for asynchronicity and resilience, and a simple synchronous, blocking API call inside the existing Saga is a major anti-pattern that would compromise the system's design principles.

2.  **Solution Design:**
    *   Propose a **Strategy Pattern** within the `transaction_service`. A factory or conditional logic at the start of the transaction creation process will instantiate either a `StandardSettlementStrategy` (which uses the existing Saga) or an `InstantSettlementStrategy` based on the transaction's parameters.
    *   The `InstantSettlementStrategy` would orchestrate a series of synchronous, blocking calls: (1) Pre-authorization risk check, (2) Wallet fund reservation, (3) Call to external InstaPay API.
    *   Crucially, the developer would decide *against* modifying the existing `payment_saga` to include the synchronous call. The new path would be a separate, self-contained flow.
    *   For the `wallet_service`, the proposal would not involve direct API calls to update the ledger. Instead, after a successful synchronous response from InstaPay, the `InstantSettlementStrategy` would publish a new, highly-trusted event, like `InstantSettlementSucceeded`. The `wallet_service` would have a new consumer for this event to apply the final state change to its ledger, thus preserving the event-sourcing pattern.
    *   For failure handling, the proposal would detail a compensating transaction. If the InstaPay API call fails, the `InstantSettlementStrategy` would be responsible for publishing a `ReleaseReservedFunds` event to revert the change in the `wallet_service`.
    *   The sequence diagram would be constructed to clearly show the synchronous nature of the calls within the `InstantSettlementStrategy` and the final event publication that decouples it from the `wallet_service`'s internal state update.

## Evaluation Criteria

- **Architectural Pattern Comprehension:** Did the agent correctly identify the Saga pattern and explain why a synchronous call within it is an anti-pattern?
- **Solution Soundness:** Is the proposed solution (e.g., using a Strategy pattern) architecturally sound and does it effectively segregate the synchronous and asynchronous flows?
- **Data Integrity:** Does the proposal protect the integrity of the `wallet_service` ledger by using an event-driven update mechanism instead of a direct, cross-service call?
- **Impact Analysis:** Did the agent correctly identify the necessary changes and impacts on all relevant services (`transaction_service`, `wallet_service`, `risk_compliance_service`)?
- **Failure & Compensation:** Is the proposed failure handling for the new synchronous path clear, correct, and robust?
- **Clarity and Completeness:** Is the final proposal well-structured, clear, and does it include all requested components, including a valid Mermaid sequence diagram?
- **File Reference:** Did the agent correctly reference key files (`payment_saga.py`, `saga_pattern.md`, etc.) to support its analysis of the current system?

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

**Repository**: `sg-benchmarks/locobench-python_fintech_payment_expert_029`

Example MCP queries:
- "In sg-benchmarks/locobench-python_fintech_payment_expert_029, where is the main entry point?"
- "Search sg-benchmarks/locobench-python_fintech_payment_expert_029 for error handling code"
- "In sg-benchmarks/locobench-python_fintech_payment_expert_029, how does the authentication flow work?"

**IMPORTANT**: Always include the full repository path `sg-benchmarks/locobench-python_fintech_payment_expert_029` in your MCP search queries to ensure you're searching the correct codebase.

## Output Format

**CRITICAL**: Write your complete solution to `/logs/agent/solution.md` (NOT `/app/solution.md`). Include:
- Your analysis and reasoning
- Specific file paths and code references
- Any code changes or implementations (as applicable)
- Your final answer or recommendations
