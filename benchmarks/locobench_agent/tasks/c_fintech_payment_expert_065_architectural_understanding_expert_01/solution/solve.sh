#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
### Architectural Proposal: Tuition Auto-Payment

#### 1. Interaction Sequence

1.  **Saga Start**: The process begins when a `DisburseStipendCommand` is handled by the `financial_aid_service`.
2.  **Stipend Disbursement**: The `DisburseStipendSaga` executes its primary step, disbursing the funds. Upon success, the `financial_aid_service` publishes a `StipendDisbursed` event via RabbitMQ.
3.  **Saga Continuation & Pre-condition Check**: The Saga Coordinator, listening for `StipendDisbursed`, proceeds to the next step. It issues a query to the `bursar_service`'s read side (or a dedicated projection) to fetch the student's auto-pay consent status and outstanding balance.
4.  **Conditional Command**: If the student has opted-in and has a balance, the Saga Coordinator sends a `ProcessTuitionAutoPay` command to the `bursar_service`.
5.  **Bursar Processing**: The `bursar_service`'s command handler processes the payment, debiting the student's internal funds account and crediting the tuition ledger. Upon success, it persists and publishes a `TuitionPaymentAppliedFromStipend` event.
6.  **Projection Update**: The `projections_service`'s `DashboardProjector` consumes the `TuitionPaymentAppliedFromStipend` event and updates the student's account balance read model.
7.  **Saga Completion**: The Saga Coordinator receives confirmation (e.g., by consuming the success event) and marks the saga step as complete.

#### 2. Saga Pattern Integration

The existing `DisburseStipendSaga` (defined in `disburse_stipend_saga.c/h`) will be extended. This is preferable to a new saga because auto-payment is a direct consequence of disbursement, not an independent business process.

-   **New Saga Step**: A step named `ApplyPaymentToTuition` will be added after the `DisburseStipend` step.
-   **Compensating Action**: A corresponding compensating action, `ReverseTuitionApplication`, must be implemented. This action would issue a command to the `bursar_service` to reverse the transaction if a later step in the saga were to fail.

#### 3. New Domain Events

-   `TuitionPaymentAppliedFromStipend`: Published by `bursar_service` on successful auto-payment. Contains `student_id`, `amount`, `original_stipend_transaction_id`.
-   `TuitionAutoPaySkipped`: (Optional but good practice) Published by the Saga Coordinator if the student is not opted-in or has no balance.
-   `TuitionAutoPayFailed`: Published by `bursar_service` if the internal transfer fails for any reason (e.g., insufficient funds after a race condition).

#### 4. CQRS/Event Sourcing Impact

-   **Aggregates**: In `bursar_service`, the `Account` aggregate will be modified. The `ProcessTuitionAutoPay` command handler will invoke methods on the `Account` instance, which will generate two events: `FundsDebited` (for the stipend holding account) and `FundsCredited` (for the tuition ledger account). These are then stored in the `postgres_event_store`.
-   **Projections**: The `projections_service/event_handlers/dashboard_projector.c` must be modified. It needs a new handler function to subscribe to the `TuitionPaymentAppliedFromStipend` event. When received, it will update the denormalized SQL table that stores student account balances, ensuring the UI reflects the payment instantly.

#### 5. Compliance and Consent

-   **Consent Storage**: The student's opt-in consent flag for auto-payment should be stored as an attribute on the student's `Account` aggregate within the `bursar_service`'s bounded context. This ensures the data lives within the service that acts upon it.
-   **Consent Check**: As per `05_security_and_compliance.md`, explicit consent is required. The Saga Coordinator will perform this check (Step 1.3) by querying the `bursar_service`'s read model *before* issuing the `ProcessTuitionAutoPay` command. This prevents unauthorized movement of funds.

#### 6. Affected Components

-   `docs/architecture/04_saga_pattern.md`: Update with the new saga flow.
-   `src/services/financial_aid_service/application/use_cases/disburse_stipend_saga.c/h`: Add new step definition and logic to the saga coordinator.
-   `src/services/bursar_service/domain/account.c/h`: Add logic to store and manage the `autoPayConsent` flag.
-   `src/services/bursar_service/application/commands/`: New `process_tuition_auto_pay_command.h`.
-   `src/services/bursar_service/application/use_cases/`: New `process_tuition_auto_pay.c/h` use case handler.
-   `src/projections_service/event_handlers/dashboard_projector.c`: Add new handler for `TuitionPaymentAppliedFromStipend`.
-   `src/shared_kernel/domain/events/`: Define new event structs in a new header file.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
