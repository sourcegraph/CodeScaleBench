package com.sprintcart.application.service;

import com.sprintcart.domain.model.order.Order;
import com.sprintcart.domain.model.order.OrderId;
import com.sprintcart.domain.model.order.OrderItem;
import com.sprintcart.domain.model.order.OrderStatus;
import com.sprintcart.domain.model.user.UserId;
import com.sprintcart.domain.port.order.OrderCommandPort;
import com.sprintcart.domain.port.order.OrderQueryPort;
import com.sprintcart.domain.port.payment.PaymentGatewayPort;
import com.sprintcart.domain.port.inventory.InventoryPort;
import com.sprintcart.domain.port.notification.NotificationPort;
import com.sprintcart.domain.port.metrics.DomainMetricsPort;
import com.sprintcart.domain.model.checkout.CheckoutCommand;
import com.sprintcart.domain.shared.exception.BusinessViolation;
import com.sprintcart.domain.shared.exception.ResourceNotFound;
import com.sprintcart.domain.shared.exception.UpstreamFailure;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/**
 * Application-level service that orchestrates the {@link Order} life-cycle by delegating
 * pure domain logic to the domain model and interacting with external systems through
 * hexagonal Ports.
 *
 * This class purposefully contains no business rules.  Instead, it coordinates
 * domain entities and side-effects so that each concern stays isolated and testable.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OrderService {

    private final OrderCommandPort orderCommandPort;
    private final OrderQueryPort orderQueryPort;
    private final PaymentGatewayPort paymentGatewayPort;
    private final InventoryPort inventoryPort;
    private final NotificationPort notificationPort;
    private final DomainMetricsPort metricsPort;
    private final Clock clock;

    /**
     * Places a new order, performs stock reservation and attempts immediate payment capture.
     *
     * @param command checkout information supplied by the client
     * @param customerId ID of the user placing the order
     * @return the newly created Order aggregate, reflecting the persisted state
     * @throws BusinessViolation   if stock is unavailable or payment is declined
     * @throws UpstreamFailure     if the payment gateway is unreachable
     */
    @Transactional
    public Order placeOrder(final CheckoutCommand command, final UserId customerId) {
        Instant startedAt = Instant.now(clock);

        // 1.  Validate & reserve stock in a best-effort manner
        List<OrderItem> requestedItems = command.toOrderItems();
        if (!inventoryPort.reserveStock(requestedItems)) {
            log.warn("Stock reservation failed for customer={}", customerId);
            throw new BusinessViolation("One or more items are out of stock");
        }

        // 2.  Build domain aggregate
        Order order = Order.placeNew(OrderId.random(), customerId, requestedItems, clock);
        orderCommandPort.save(order);

        try {
            // 3.  Capture payment
            paymentGatewayPort.charge(order.getId(), command.getPaymentMethod(), order.getGrandTotal());

            // 4.  Domain state transition
            order.markAsPaid(clock);
            orderCommandPort.save(order);

            // 5.  Notify customer & update metrics
            notificationPort.orderConfirmation(order);
            metricsPort.incrementCounter("order.placed.ok");

            return order;
        } catch (PaymentGatewayPort.CardDeclined e) {
            // business failure, rollback transaction
            log.info("Payment declined for order={}, reason={}", order.getId(), e.getMessage());
            throw new BusinessViolation("Payment was declined: " + e.getMessage());
        } catch (PaymentGatewayPort.CommunicationFailure e) {
            // upstream system down; let the job-queue reconcile later
            log.error("Payment gateway unreachable, scheduling retry for order={}", order.getId(), e);
            metricsPort.incrementCounter("order.placed.pending-payment");
            throw new UpstreamFailure("Could not reach payment provider");
        }
        //  Transactional boundary will roll back upon exceptions
    }

    /**
     * Cancels an existing order.  Refunds the payment and releases reserved stock.
     *
     * @param orderId   the order to cancel
     * @param requestedBy operator performing the action
     */
    @Transactional
    public void cancelOrder(final UUID orderId, final UserId requestedBy) {
        Order order = orderQueryPort.findById(OrderId.of(orderId))
                .orElseThrow(() -> new ResourceNotFound("Order not found: " + orderId));

        if (!order.canBeCancelled()) {
            throw new BusinessViolation("Order " + orderId + " cannot be cancelled in state " + order.getStatus());
        }

        if (order.getStatus() == OrderStatus.PAID) {
            paymentGatewayPort.refund(order.getId(), order.getGrandTotal());
        }

        inventoryPort.releaseStock(order.getItems());
        order.cancel(requestedBy, clock);

        orderCommandPort.save(order);

        notificationPort.orderCancelled(order);
        metricsPort.incrementCounter("order.cancelled");
        log.info("Order {} cancelled by user {}", orderId, requestedBy);
    }

    /**
     * Web-hook entry-point used by the payment provider to acknowledge that an
     * asynchronous payment has settled.
     */
    @Transactional
    public void markOrderAsPaid(final UUID orderId, final String externalTransactionId) {
        Order order = orderQueryPort.findById(OrderId.of(orderId))
                .orElseThrow(() -> new ResourceNotFound("Order not found: " + orderId));

        if (order.getStatus() == OrderStatus.PAID) {
            log.debug("Ignoring duplicate payment event for order={}", orderId);
            return;
        }

        order.markAsPaid(clock, externalTransactionId);
        orderCommandPort.save(order);

        inventoryPort.commitReservedStock(order.getItems());
        notificationPort.orderConfirmation(order);
        metricsPort.incrementCounter("order.paid");
        log.info("Order {} marked as PAID via transaction {}", orderId, externalTransactionId);
    }

    /**
     * Returns an immutable snapshot DTO of the order.  This keeps domain aggregates
     * from "leaking" into remote layers.
     */
    @Transactional(readOnly = true)
    public OrderDto getOrderDetails(final UUID orderId, final UserId requester) {
        return orderQueryPort.findById(OrderId.of(orderId))
                .filter(o -> o.isOwnedBy(requester))
                .map(OrderDto::fromAggregate)
                .orElseThrow(() -> new ResourceNotFound("Order not found"));
    }

    /* -----------------------------------------------------------------
     * Immutable adapter-layer DTO.  In real code this would likely live
     * in a dedicated mapping module but is inlined here for brevity.
     * ----------------------------------------------------------------- */
    public record OrderDto(
            UUID id,
            String status,
            Instant placedAt,
            List<Line> lines,
            String currency,
            String grandTotal
    ) {

        public static OrderDto fromAggregate(Order order) {
            return new OrderDto(
                    order.getId().value(),
                    order.getStatus().name(),
                    order.getPlacedAt(),
                    order.getItems().stream().map(Line::of).toList(),
                    order.getGrandTotal().currency().getCurrencyCode(),
                    order.getGrandTotal().formatted()
            );
        }

        public record Line(
                UUID productId,
                String name,
                int quantity,
                String unitPrice,
                String lineTotal
        ) {
            static Line of(OrderItem item) {
                return new Line(
                        item.getProductId().value(),
                        item.getName(),
                        item.getQuantity(),
                        item.getUnitPrice().formatted(),
                        item.getLineTotal().formatted()
                );
            }
        }
    }
}