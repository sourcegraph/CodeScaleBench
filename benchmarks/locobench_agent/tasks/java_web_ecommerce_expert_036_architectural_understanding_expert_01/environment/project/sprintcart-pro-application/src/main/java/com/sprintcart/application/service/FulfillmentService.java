package com.sprintcart.application.service;

import com.sprintcart.domain.common.Address;
import com.sprintcart.domain.event.DomainEventPublisher;
import com.sprintcart.domain.exception.BusinessRuleViolationException;
import com.sprintcart.domain.fulfillment.*;
import com.sprintcart.domain.order.Order;
import com.sprintcart.domain.order.OrderLine;
import com.sprintcart.domain.order.OrderRepository;
import com.sprintcart.domain.order.OrderStatus;
import com.sprintcart.domain.product.InventoryGateway;
import com.sprintcart.domain.product.StockReservationResult;
import com.sprintcart.domain.shared.OperatorId;
import com.sprintcart.domain.shipping.ShippingGateway;
import com.sprintcart.domain.time.TimeProvider;
import com.sprintcart.domain.user.NotificationGateway;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Application-layer service responsible for orchestrating the fulfillment work-flow.
 *
 * The class purposely does not leak any framework-specific constructs (such as
 * DTOs or entities) to the outside world; it only speaks domain objects.
 * <p>
 * Steps performed:
 *  1. Retrieve & validate the Order in a transaction-safe manner.
 *  2. Reserve inventory and record shortages.
 *  3. Generate a picking list and corresponding shipment label.
 *  4. Persist Order state transitions (Fulfilling -> Fulfilled).
 *  5. Emit domain events and user notifications.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class FulfillmentService {

    // ————————————————————————————————————————————————————————— Ports & Dependencies
    private final OrderRepository orderRepository;
    private final InventoryGateway inventoryGateway;
    private final ShippingGateway shippingGateway;
    private final NotificationGateway notificationGateway;
    private final DomainEventPublisher eventPublisher;
    private final TimeProvider timeProvider;

    private static final int MAX_RETRIES_ON_CONTENTION = 3;

    /**
     * Triggers the full fulfillment workflow for a single order.
     *
     * @param orderId    Business identifier of the order.
     * @param operatorId User who initiated the action (auditing / productivity KPI).
     * @return An immutable value object describing the outcome.
     */
    public FulfillmentResult fulfill(UUID orderId, OperatorId operatorId) {
        Instant startedAt = timeProvider.now();
        AtomicInteger attemptCounter = new AtomicInteger(0);

        while (attemptCounter.incrementAndGet() <= MAX_RETRIES_ON_CONTENTION) {
            try {
                return fulfillInternal(orderId, operatorId, startedAt);
            } catch (OptimisticLockingFailureException e) {
                log.warn("Contention detected while trying to fulfill order {} (attempt {}/{})",
                        orderId, attemptCounter.get(), MAX_RETRIES_ON_CONTENTION);
                sleepBackOff(attemptCounter.get());
            }
        }
        throw new FulfillmentException("Could not fulfill order " + orderId + " due to repeated concurrent modifications");
    }

    // ——————————————————————————————————————————————————————————————— Internal

    @Transactional
    protected FulfillmentResult fulfillInternal(UUID orderId,
                                                OperatorId operatorId,
                                                Instant startedAt) {

        Order order = orderRepository.findById(orderId)
                .orElseThrow(() -> new FulfillmentException("Order " + orderId + " not found"));

        if (order.getStatus() != OrderStatus.PAID) {
            throw new BusinessRuleViolationException("Only orders in PAID state can be fulfilled");
        }

        // 1. Reserve inventory
        InventoryReservationSummary reservationSummary = reserveInventory(order);

        // 2. Create picking list (domain object for warehouse employees)
        PickingList pickingList = generatePickingList(order, reservationSummary);

        // 3. Ship (interacts with external carrier API)
        ShipmentLabel shipmentLabel = generateShipmentLabel(order, pickingList);

        // 4. Transition order state
        order.markAsFulfilled(shipmentLabel.trackingNumber(), timeProvider.now());
        orderRepository.save(order);

        // 5. Emit domain events & notifications
        eventPublisher.publish(new OrderFulfilledEvent(order.getId(), operatorId, shipmentLabel.trackingNumber()));
        notificationGateway.notifyCustomerFulfilled(order.getCustomerId(), order.getId(), shipmentLabel);

        Duration totalDuration = Duration.between(startedAt, timeProvider.now());
        log.info("Order {} fulfilled in {} ms", orderId, totalDuration.toMillis());

        return new FulfillmentResult(orderId,
                                     shipmentLabel.trackingNumber(),
                                     reservationSummary,
                                     totalDuration);
    }

    // —————————————————————————————————————————————————————————— Sub-Steps

    private InventoryReservationSummary reserveInventory(Order order) {
        InventoryReservationSummary summary = new InventoryReservationSummary();

        for (OrderLine line : order.getOrderLines()) {
            StockReservationResult result =
                    inventoryGateway.reserveStock(line.getSku(), line.getQuantity());

            summary.add(result);

            if (!result.isSuccessful()) {
                log.warn("Partial stock reservation for order {} – SKU {} only {} reserved out of {}",
                        order.getId(), line.getSku(), result.reserved(), line.getQuantity());
            }
        }

        if (!summary.isFullyReserved()) {
            throw new InsufficientStockException(order.getId(), summary);
        }
        return summary;
    }

    private PickingList generatePickingList(Order order, InventoryReservationSummary summary) {
        List<PickingItem> items = order.getOrderLines().stream()
                .map(ol -> new PickingItem(ol.getSku(), ol.getQuantity(), summary.getLocatorFor(ol.getSku())))
                .toList();

        return new PickingList(order.getId(), items, order.getShippingAddress());
    }

    private ShipmentLabel generateShipmentLabel(Order order, PickingList pickingList) {
        Address shipTo = order.getShippingAddress();
        return shippingGateway.createShipment(order.getId(), shipTo, pickingList.totalWeight());
    }

    // —————————————————————————————————————————————————————————— Utilities

    private void sleepBackOff(int attempt) {
        try {
            Thread.sleep(200L * attempt); // simple linear back-off
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
        }
    }

    // ——————————————————————————————————————————————————————————— Types

    /**
     * DTO representing the outcome of the fulfillment process.
     * Could later be extended with analytics metadata.
     */
    public record FulfillmentResult(UUID orderId,
                                    String trackingNumber,
                                    InventoryReservationSummary reservationSummary,
                                    Duration processingTime) {
    }
}