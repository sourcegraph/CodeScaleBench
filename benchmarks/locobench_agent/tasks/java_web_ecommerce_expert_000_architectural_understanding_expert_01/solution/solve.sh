#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
### Architectural Flaw

The root cause of the issue is that the order creation API endpoint is not idempotent. The system lacks a mechanism to uniquely identify and de-duplicate requests for the same transaction. A client-side retry, triggered by a timeout, initiates a completely new and independent execution of the order creation logic. Since the payment processing and order record creation are not an atomic operation from the client's perspective, this retry leads to duplicate state (two orders in the DB) and duplicate side effects (two charges on the payment gateway).

### Proposed Solution

Implement the **Idempotency-Key** pattern to ensure that repeated requests for the same logical operation do not result in duplicate processing.

1.  **API Contract Change (DTO):**
    *   **File:** `CommerceSphereEnterpriseSuite/src/main/java/com/commercesphere/enterprise/ordering/dto/OrderDto.java` (or a more specific `CreateOrderRequestDto` if one were created).
    *   **Change:** Add a new field to the DTO to carry the idempotency key.
        ```java
        private String idempotencyKey;
        ```

2.  **Data Model Change:**
    *   **File:** `CommerceSphereEnterpriseSuite/src/main/java/com/commercesphere/enterprise/ordering/model/Order.java`
    *   **Change:** Add a field to the `Order` entity to store the key. It must be unique.
        ```java
        @Column(name = "idempotency_key", unique = true, nullable = false, updatable = false)
        private String idempotencyKey;
        ```

3.  **Database Schema Migration:**
    *   **File:** Create a new file `CommerceSphereEnterpriseSuite/src/main/resources/db/migration/V3__Add_Idempotency_Key_To_Orders.sql`.
    *   **Change:** Add the column to the `orders` table with a unique constraint.
        ```sql
        ALTER TABLE orders ADD COLUMN idempotency_key VARCHAR(255);
        UPDATE orders SET idempotency_key = gen_random_uuid() WHERE idempotency_key IS NULL;
        ALTER TABLE orders ALTER COLUMN idempotency_key SET NOT NULL;
        ALTER TABLE orders ADD CONSTRAINT uk_orders_idempotency_key UNIQUE (idempotency_key);
        ```

4.  **Service Layer Logic Modification:**
    *   **File:** `CommerceSphereEnterpriseSuite/src/main/java/com/commercesphere/enterprise/ordering/service/OrderService.java`
    *   **Change:** Modify the primary order creation method (e.g., `createOrderFromDto`).
        *   The method must be annotated with `@Transactional`.
        *   At the beginning of the method, query the `OrderRepository` to find an order by the provided `idempotencyKey`.
        *   **If an order is found:** Immediately return that existing order, preventing any further processing.
        *   **If no order is found:** Proceed with the existing logic of creating the order, calling the `PaymentOrchestrationService`, etc. Crucially, set the `idempotencyKey` on the new `Order` entity before saving it. The database's unique constraint will act as the ultimate guard against race conditions where two threads might pass the initial check simultaneously.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
