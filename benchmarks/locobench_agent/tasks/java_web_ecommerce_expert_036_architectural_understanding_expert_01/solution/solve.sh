#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
### WMS Integration Technical Plan

#### 1. Module and Dependency Strategy

A new Maven module `sprintcart-pro-adapters/wms-adapter` will be created. 
-   **Dependencies:** `wms-adapter` will depend on `sprintcart-pro-application` and `sprintcart-pro-domain` to access the port interfaces and application services it needs to call.
-   **Configuration:** The main `sprintcart-pro-app` module will need to add `wms-adapter` as a dependency in its `pom.xml` so that the Spring Boot application can discover and wire the new beans (Controller, Adapter implementation).

#### 2. Ports (Interfaces) Definition

Two new ports will be created in the `sprintcart-pro-domain` module:

-   **Outbound Port:** For sending data to the WMS.
    -   **File:** `sprintcart-pro-domain/src/main/java/com/sprintcart/domain/ports/out/wms/WmsPort.java`
    -   **Interface:** 
        ```java
        package com.sprintcart.domain.ports.out.wms;

        import com.sprintcart.domain.model.order.Order;

        public interface WmsPort {
            /**
             * Submits a fulfillment request to the external WMS.
             * @param order The confirmed order to be fulfilled.
             */
            void requestFulfillment(Order order);
        }
        ```
-   **Inbound Port (Use Case):** For updating stock from an external system.
    -   **File:** `sprintcart-pro-domain/src/main/java/com/sprintcart/domain/ports/in/inventory/UpdateStockUseCase.java`
    -   **Interface:**
        ```java
        package com.sprintcart.domain.ports.in.inventory;

        public interface UpdateStockUseCase {
            /**
             * Updates the stock level for a given product SKU.
             * @param sku The product SKU to update.
             * @param quantityChange The change in quantity (can be positive or negative).
             */
            void updateStockLevel(String sku, int quantityChange);
        }
        ```

#### 3. Adapter Implementation Plan

The `wms-adapter` module will contain:

1.  **`WmsAdapter.java`:** Implements `WmsPort`. It will use a `WebClient` or `RestTemplate` to make an outbound POST request to the WMS API's fulfillment endpoint. It will map the domain `Order` model to a WMS-specific DTO before sending.
2.  **`WmsController.java`:** A new `@RestController` that exposes a secure endpoint (e.g., `POST /api/internal/wms/stock-update`). It will accept a WMS-specific DTO, validate it, and then call the `UpdateStockUseCase` port.
3.  **`WmsDto.java`:** A record or class representing the stock update payload from the WMS.

#### 4. Application Layer Orchestration

-   **Outbound (Fulfillment):** The `FulfillmentService` in the `application` module will be injected with `WmsPort`. A new method, `processFulfillment(Order order)`, will be added. This method will be called (e.g., by the `DomainEventProcessor` listening for `OrderPlacedEvent`) and will invoke `wmsPort.requestFulfillment(order)`.
-   **Inbound (Stock Update):** The `CatalogService` in the `application` module will implement the `UpdateStockUseCase` interface. The `updateStockLevel` method will use the existing `ProductRepositoryPort` to find the product by SKU, update its stock quantity, and save it back to the database.

#### 5. Data Flow Diagram (Inbound Stock Update)

`External WMS` -> `[Network]` -> `1. WmsController` (in `wms-adapter`) -> `2. UpdateStockUseCase` (port in `domain`) -> `3. CatalogService` (implementation in `application`) -> `4. ProductRepositoryPort` (port in `domain`) -> `5. ProductRepositoryAdapter` (implementation in `persistence-adapter`) -> `6. Database`

#### 6. Architectural Justification

This plan strictly adheres to the principles outlined in **`docs/architecture/adr/001-hexagonal-architecture.md`**. 

1.  **Dependency Inversion:** The `domain` core defines the `WmsPort` and `UpdateStockUseCase` interfaces but has no knowledge of the WMS itself. The `wms-adapter`, an infrastructure detail, depends on the domain, not the other way around. This follows the Dependency Rule.
2.  **Separation of Concerns:** The new `wms-adapter` encapsulates all details of the WMS communication (endpoints, DTOs, client logic), isolating it from the core business logic. This is consistent with the visual separation shown in the **`docs/architecture/c4-model/03_component_diagram.puml`**, where adapters (like Persistence, Payment) are on the periphery of the system.

GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
