package com.sprintcart.domain.ports.in.order;

import com.sprintcart.domain.model.order.OrderId;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/**
 * Inbound port that exposes all commands required to drive the {@code Fulfillment} workflow
 * for an {@code Order}. <p/>
 *
 * The interface is intentionally coarse-grained: each method represents a complete user intent
 * that can be executed via REST, GraphQL, CLI, or any other adapter without leaking
 * infrastructure details into the domain. <p/>
 *
 * Implementations MUST be:
 * <ul>
 *     <li>Transactional – a command is either fully applied or rolled back.</li>
 *     <li>Idempotent   – repeated invocations with the same {@code correlationId}
 *                        must yield the same {@link FulfillmentTicket}.</li>
 *     <li>Side-effect-free – outside of domain state changes and domain events.</li>
 * </ul>
 *
 * All methods return the current {@link FulfillmentTicket} so that callers receive
 * a full projection of the state after the command has been applied.
 */
public interface ManageFulfillmentUseCase {

    /**
     * Kicks off the fulfillment workflow for a given order.
     *
     * @throws UnknownOrderException               if the order does not exist.
     * @throws FulfillmentAlreadyStartedException  if the order is already in fulfillment.
     * @throws InventoryUnavailableException       if one or more lines cannot be allocated.
     */
    FulfillmentTicket startFulfillment(StartFulfillmentCommand command)
            throws UnknownOrderException,
                   FulfillmentAlreadyStartedException,
                   InventoryUnavailableException;

    /**
     * Marks the given order lines as picked by the warehouse operator.
     */
    FulfillmentTicket markPicked(MarkPickedCommand command)
            throws UnknownOrderException, InvalidFulfillmentStateException;

    /**
     * Confirms that all items have been packed and (optionally) associates package-level meta-data.
     */
    FulfillmentTicket markPacked(MarkPackedCommand command)
            throws UnknownOrderException, InvalidFulfillmentStateException;

    /**
     * Completes the fulfillment by registering shipment details and switching state to {@code SHIPPED}.
     */
    FulfillmentTicket markShipped(MarkShippedCommand command)
            throws UnknownOrderException, InvalidFulfillmentStateException;

    /**
     * Cancels an ongoing fulfillment, rolling back inventory allocations.
     */
    FulfillmentTicket cancelFulfillment(CancelFulfillmentCommand command)
            throws UnknownOrderException, InvalidFulfillmentStateException;

    /* --------------------------------------------------------------------- */
    /* --------------------- COMMAND & RESULT RECORDS ---------------------- */
    /* --------------------------------------------------------------------- */

    /**
     * Base type for all fulfillment commands. Carries common metadata such as
     * {@code correlationId} for idempotency and {@code requestedAt} for auditing.
     */
    record FulfillmentCommand(
            OrderId orderId,
            UUID correlationId,
            Instant requestedAt
    ) {
        public FulfillmentCommand {
            Objects.requireNonNull(orderId,      "orderId must not be null");
            Objects.requireNonNull(correlationId,"correlationId must not be null");
            Objects.requireNonNull(requestedAt,  "requestedAt must not be null");
        }
    }

    /**
     * Command used to start fulfillment.
     */
    record StartFulfillmentCommand(
            OrderId orderId,
            UUID correlationId,
            Instant requestedAt
    ) implements ManageFulfillmentUseCase.FulfillmentCommand {
        public StartFulfillmentCommand {
            Objects.requireNonNull(orderId,      "orderId must not be null");
            Objects.requireNonNull(correlationId,"correlationId must not be null");
            Objects.requireNonNull(requestedAt,  "requestedAt must not be null");
        }
    }

    /**
     * Command used to mark specific order lines as picked.
     */
    record MarkPickedCommand(
            OrderId orderId,
            UUID correlationId,
            Instant requestedAt,
            List<String> pickedLineIds
    ) implements ManageFulfillmentUseCase.FulfillmentCommand {
        public MarkPickedCommand {
            Objects.requireNonNull(orderId,       "orderId must not be null");
            Objects.requireNonNull(correlationId, "correlationId must not be null");
            Objects.requireNonNull(requestedAt,   "requestedAt must not be null");
            Objects.requireNonNull(pickedLineIds, "pickedLineIds must not be null");
        }
    }

    /**
     * Command used to confirm that items have been packed.
     */
    record MarkPackedCommand(
            OrderId orderId,
            UUID correlationId,
            Instant requestedAt,
            List<PackageInfo> packages
    ) implements ManageFulfillmentUseCase.FulfillmentCommand {
        public MarkPackedCommand {
            Objects.requireNonNull(orderId,       "orderId must not be null");
            Objects.requireNonNull(correlationId, "correlationId must not be null");
            Objects.requireNonNull(requestedAt,   "requestedAt must not be null");
            Objects.requireNonNull(packages,      "packages must not be null");
        }
    }

    /**
     * Command used to ship the order.
     */
    record MarkShippedCommand(
            OrderId orderId,
            UUID correlationId,
            Instant requestedAt,
            String carrier,
            String trackingNumber,
            Instant promisedDeliveryDate
    ) implements ManageFulfillmentUseCase.FulfillmentCommand {
        public MarkShippedCommand {
            Objects.requireNonNull(orderId,              "orderId must not be null");
            Objects.requireNonNull(correlationId,        "correlationId must not be null");
            Objects.requireNonNull(requestedAt,          "requestedAt must not be null");
            Objects.requireNonNull(carrier,              "carrier must not be null");
            Objects.requireNonNull(trackingNumber,       "trackingNumber must not be null");
            Objects.requireNonNull(promisedDeliveryDate, "promisedDeliveryDate must not be null");
        }
    }

    /**
     * Command used to cancel fulfillment.
     */
    record CancelFulfillmentCommand(
            OrderId orderId,
            UUID correlationId,
            Instant requestedAt,
            String reason
    ) implements ManageFulfillmentUseCase.FulfillmentCommand {
        public CancelFulfillmentCommand {
            Objects.requireNonNull(orderId,       "orderId must not be null");
            Objects.requireNonNull(correlationId, "correlationId must not be null");
            Objects.requireNonNull(requestedAt,   "requestedAt must not be null");
            Objects.requireNonNull(reason,        "reason must not be null");
        }
    }

    /**
     * Immutable projection of the fulfillment after a command has been processed.
     */
    record FulfillmentTicket(
            UUID fulfillmentId,
            OrderId orderId,
            FulfillmentStatus status,
            Instant updatedAt,
            List<PackageInfo> packages,
            Map<String, String> metadata
    ) {
        public FulfillmentTicket {
            Objects.requireNonNull(fulfillmentId, "fulfillmentId must not be null");
            Objects.requireNonNull(orderId,       "orderId must not be null");
            Objects.requireNonNull(status,        "status must not be null");
            Objects.requireNonNull(updatedAt,     "updatedAt must not be null");
            Objects.requireNonNull(packages,      "packages must not be null");
            Objects.requireNonNull(metadata,      "metadata must not be null");
        }
    }

    /**
     * Package-level information generated at packing time.
     */
    record PackageInfo(
            String packageId,
            Double weightInKg,
            String dimensions,
            String labelUrl
    ) {
        public PackageInfo {
            Objects.requireNonNull(packageId,  "packageId must not be null");
            Objects.requireNonNull(weightInKg, "weightInKg must not be null");
            Objects.requireNonNull(dimensions, "dimensions must not be null");
            Objects.requireNonNull(labelUrl,   "labelUrl must not be null");
        }
    }

    /**
     * Finite list of possible fulfillment statuses.
     */
    enum FulfillmentStatus { REQUESTED, ALLOCATED, PICKED, PACKED, SHIPPED, CANCELED }

    /* --------------------------------------------------------------------- */
    /* --------------------------- EXCEPTIONS ------------------------------ */
    /* --------------------------------------------------------------------- */

    /**
     * Thrown when the referenced order cannot be found.
     */
    class UnknownOrderException extends RuntimeException {
        public UnknownOrderException(OrderId orderId) {
            super("Order not found: " + orderId);
        }
    }

    /**
     * Thrown when inventory cannot be reserved.
     */
    class InventoryUnavailableException extends RuntimeException {
        public InventoryUnavailableException(OrderId orderId) {
            super("Inventory unavailable for order: " + orderId);
        }
    }

    /**
     * Thrown when the fulfillment has already been started.
     */
    class FulfillmentAlreadyStartedException extends RuntimeException {
        public FulfillmentAlreadyStartedException(OrderId orderId) {
            super("Fulfillment already started for order: " + orderId);
        }
    }

    /**
     * Thrown when a command is issued in an invalid state (e.g., shipping a canceled fulfillment).
     */
    class InvalidFulfillmentStateException extends RuntimeException {
        public InvalidFulfillmentStateException(OrderId orderId, FulfillmentStatus status) {
            super("Invalid fulfillment state [" + status + "] for order: " + orderId);
        }
    }
}