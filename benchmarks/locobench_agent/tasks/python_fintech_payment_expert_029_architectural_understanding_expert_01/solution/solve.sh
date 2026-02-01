#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The core of a correct solution is the recognition that the new synchronous requirement cannot be naively shoehorned into the existing asynchronous Saga pattern. The proposal must introduce a parallel execution path.

**Key Insights for a Correct Solution:**

*   **Rejection of Saga Modification:** The solution explicitly states that modifying the `payment_saga` to include a long-running, synchronous, blocking API call is incorrect. It justifies this by explaining that it violates the Saga's principles of loose coupling and resilience.
*   **Introduction of a Strategy Pattern (or similar):** The `transaction_service` should use a design pattern (like Strategy or a simple factory) to select the appropriate workflow (`StandardSaga` vs. `InstantSyncFlow`) based on transaction properties.
*   **Decoupled Ledger Update:** The `wallet_service`'s ledger integrity is paramount. The solution must ensure that even in the synchronous flow, the final ledger update is triggered by consuming an immutable, internally-generated event (e.g., `InstantSettlementConfirmedEvent`) after the external API call succeeds. This respects the CQRS/Event Sourcing pattern.
*   **Dedicated Compensation Logic:** The synchronous flow must have its own robust compensation logic. If the external API call fails, the flow must explicitly trigger compensating actions (e.g., publishing a `RevertFundReservation` event).
*   **Example Mermaid Sequence Diagram:**
```mermaid
sequenceDiagram
    participant Client
    participant API Gateway
    participant TransactionService
    participant WalletService
    participant RiskComplianceService
    participant InstaPay API (External)

    Client->>API Gateway: POST /v1/transactions (type=instant)
    API Gateway->>TransactionService: create_transaction(data)
    TransactionService->>TransactionService: new InstantSettlementStrategy
    TransactionService->>RiskComplianceService: request_assessment(tx_id, type='instant')
    RiskComplianceService-->>TransactionService: assessment_ok
    TransactionService->>WalletService: reserve_funds(tx_id, amount)
    WalletService-->>TransactionService: funds_reserved_ok
    TransactionService->>InstaPay API (External): POST /settle (tx_data)
    alt Successful Settlement
        InstaPay API (External)-->>TransactionService: {status: 'SUCCESS', ref: 'xyz'}
        TransactionService->>Kafka: Publish(topic='instant_settlements', event='InstantSettlementSucceeded')
        Note over WalletService: Consumes event, commits ledger transaction
        TransactionService-->>Client: {status: 'COMPLETED'}
    else Settlement Fails
        InstaPay API (External)-->>TransactionService: {status: 'FAILED', reason: '...'}
        TransactionService->>Kafka: Publish(topic='wallet_commands', event='ReleaseReservedFunds')
        Note over WalletService: Consumes event, reverts reservation
        TransactionService-->>Client: {status: 'FAILED'}
    end
```
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
