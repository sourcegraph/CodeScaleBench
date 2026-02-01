package com.sprintcart.domain.ports.out.erp;

import com.sprintcart.domain.model.catalog.SkuCode;
import com.sprintcart.domain.model.inventory.InventoryAdjustment;
import com.sprintcart.domain.model.inventory.StockSnapshot;
import com.sprintcart.domain.model.order.Order;
import com.sprintcart.domain.model.purchase.PurchaseOrder;
import com.sprintcart.domain.model.purchase.PurchaseOrderId;

import java.time.Duration;
import java.time.Instant;
import java.util.Collection;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.stream.Stream;

/**
 * Outbound port that abstracts all interactions with a third-party ERP (Enterprise Resource Planning) system.
 * <p>
 * Implementations live in the infrastructure layer and may speak various protocols (REST, SOAP, file drop, etc.).
 * The domain layer relies solely on this interface and is therefore completely decoupled from any particular ERP
 * product or transport mechanics.
 *
 * <h3>Concurrency &amp; Resilience</h3>
 * All potentially blocking operations return {@link CompletableFuture}s so that application services can execute
 * them asynchronously and compose multiple calls without hogging threads. Implementations are expected to employ
 * timeouts, retries, circuit breakers, and idempotency guarantees where appropriate. Nevertheless, failures must be
 * propagated as {@link ErpIntegrationException}s so that the domain layer can apply its own error-handling policies.
 *
 * <h3>Caching &amp; Polling</h3>
 * Methods that expose server-side streaming or polling (e.g., {@link #subscribeToOpenPurchaseOrders(Instant, Duration)})
 * should emit back-pressure aware {@link Stream}s. The domain layer will usually forward those streams to a reactive
 * pipeline that keeps local read models in sync with the ERP.
 */
public interface ErpSystemPort {

    /* ****************************************************************************************
     *  ERP Metadata & Diagnostics
     * ****************************************************************************************/

    /**
     * Returns implementation specific metadata such as vendor, edition, and version numbers.
     * This is mostly useful for telemetry and support dashboards.
     */
    ErpChannelMetadata metadata();

    /**
     * Performs a lightweight ping against the ERP endpoint.
     * Implementations should avoid expensive network round-trips whenever possible.
     */
    ErpHealth health();

    /**
     * Recommended back-off period that callers should observe after hitting rate limits or
     * temporary outages. Implementations can update this value dynamically.
     */
    default Duration recommendedBackoff() {
        return Duration.ofSeconds(30);
    }

    /* ****************************************************************************************
     *  Order Flows
     * ****************************************************************************************/

    /**
     * Creates a sales order in the ERP or updates the existing record if idempotency keys match.
     *
     * @param order Order in the SprintCart domain model.
     * @return A future containing the ERP-side reference once the operation succeeds.
     * @throws ErpIntegrationException if communication with the ERP fails irrecoverably.
     */
    CompletableFuture<ExternalReference> pushSalesOrder(Order order) throws ErpIntegrationException;

    /**
     * Returns a stream of sales orders whose status has changed since the given checkpoint.
     * <p>
     * The stream is expected to be cold and finite; callers may invoke it repeatedly using the
     * newest checkpoint obtained from {@link SalesOrderSyncResponse#lastProcessedAt()} to perform
     * incremental synchronizations.
     *
     * @param since Timestamp of the last processed change.
     * @return Stream of changed sales orders.
     */
    Stream<SalesOrderSyncResponse> pullSalesOrderChanges(Instant since) throws ErpIntegrationException;

    /* ****************************************************************************************
     *  Inventory Flows
     * ****************************************************************************************/

    /**
     * Propagates an inventory adjustment (goods receipt, shrinkage, manual count, etc.) to the ERP.
     */
    CompletableFuture<InventorySyncResponse> pushInventoryAdjustment(InventoryAdjustment adjustment)
            throws ErpIntegrationException;

    /**
     * Queries current stock levels for the requested SKUs.
     *
     * @param skus Set of SKU codes.
     * @return Map keyed by {@link SkuCode} with their latest {@link StockSnapshot}.
     */
    CompletableFuture<Map<SkuCode, StockSnapshot>> pullStockLevels(Set<SkuCode> skus)
            throws ErpIntegrationException;

    /* ****************************************************************************************
     *  Purchase Orders
     * ****************************************************************************************/

    /**
     * Retrieves a purchase order by its technical identifier.
     *
     * @return Empty if no matching purchase order exists.
     */
    CompletableFuture<Optional<PurchaseOrder>> fetchPurchaseOrder(PurchaseOrderId id)
            throws ErpIntegrationException;

    /**
     * Subscribes to purchase orders that remain in an <em>open</em> state.
     * The stream SHOULD be lazily evaluated and MUST close after {@code pollTimeout} elapses.
     *
     * @param since       Emit only purchase orders updated after this timestamp.
     * @param pollTimeout How long to keep polling before closing the stream.
     */
    Stream<PurchaseOrder> subscribeToOpenPurchaseOrders(Instant since, Duration pollTimeout)
            throws ErpIntegrationException;

    /* ****************************************************************************************
     *  Nested Types
     * ****************************************************************************************/

    /**
     * Lightweight value object that captures remote system metadata.
     */
    record ErpChannelMetadata(String vendor, String product, String version) { }

    /**
     * Health check information.
     */
    record ErpHealth(State state, String description, Instant checkedAt) {

        /**
         * Simple, pragmatic health states understood by monitoring dashboards.
         */
        public enum State {
            OK,          // All endpoints responsive with acceptable latency
            DEGRADED,    // Partial outage or latency above SLO
            DOWN         // Unavailable
        }
    }

    /**
     * The ERP's canonical reference for an entity created in a push operation.
     */
    record ExternalReference(String externalId) { }

    /**
     * Holds information about order synchronization results.
     */
    record SalesOrderSyncResponse(ExternalReference externalOrderId,
                                  Instant lastProcessedAt,
                                  SyncState state,
                                  String message) {
        public enum SyncState { SUCCESS, PARTIAL, FAILED }
    }

    /**
     * Describes the outcome of an inventory synchronization attempt.
     */
    record InventorySyncResponse(ExternalReference externalInventoryBatchId,
                                 int linesProcessed,
                                 int linesRejected,
                                 String summary) { }

    /**
     * Marker exception for all ERP-related faults.
     * <p>
     * The exception hierarchy is intentionally flat; differentiation should happen via the
     * {@link ErrorCategory}. This keeps transaction boundaries clear and avoids over-coupling
     * the domain to transport-level concerns.
     */
    class ErpIntegrationException extends RuntimeException {

        private final ErrorCategory category;

        public ErpIntegrationException(String message, ErrorCategory category) {
            super(message);
            this.category = category;
        }

        public ErpIntegrationException(String message, Throwable cause, ErrorCategory category) {
            super(message, cause);
            this.category = category;
        }

        public ErrorCategory category() {
            return category;
        }

        public enum ErrorCategory {
            NETWORK,          // HTTP/SOAP I/O, DNS, TLS, etc.
            AUTHENTICATION,   // OAuth token expired, invalid API key, etc.
            VALIDATION,       // Schema violations, missing mandatory attributes
            RATE_LIMIT,       // 429 or vendor specific throttling
            OTHER             // Catch-all for everything else
        }
    }
}