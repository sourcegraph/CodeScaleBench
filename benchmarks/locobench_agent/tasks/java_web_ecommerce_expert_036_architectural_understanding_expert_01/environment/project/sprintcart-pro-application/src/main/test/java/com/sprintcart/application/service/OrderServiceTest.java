package com.sprintcart.application.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

import com.sprintcart.domain.checkout.PaymentGateway;
import com.sprintcart.domain.checkout.PaymentStatus;
import com.sprintcart.domain.inventory.InventoryService;
import com.sprintcart.domain.notification.NotificationService;
import com.sprintcart.domain.order.*;
import com.sprintcart.domain.shared.Money;
import com.sprintcart.infrastructure.persistence.OrderRepository;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/**
 * Unit tests for {@link OrderService}. <br>
 * <p>
 * Because the application follows Hexagonal Architecture, {@code OrderService}
 * orchestrates multiple domain services / ports. The goal of these tests is to make
 * sure the orchestration logic behaves correctly under success and failure scenarios.
 * </p>
 */
@ExtendWith(MockitoExtension.class)
class OrderServiceTest {

    @Mock
    private OrderRepository orderRepository;

    @Mock
    private InventoryService inventoryService;

    @Mock
    private PaymentGateway paymentGateway;

    @Mock
    private NotificationService notificationService;

    @InjectMocks
    private OrderService orderService;

    private static final UUID CUSTOMER_ID = UUID.randomUUID();
    private static final UUID ORDER_ID = UUID.randomUUID();
    private static final String SKU = "SKU-42";
    private static final int QUANTITY = 2;

    private Order draftOrder() {
        OrderLine line = new OrderLine(SKU, QUANTITY, Money.of("USD", 25.00));
        Order order = Order.builder()
                .id(ORDER_ID)
                .customerId(CUSTOMER_ID)
                .status(OrderStatus.DRAFT)
                .placedAt(Instant.now())
                .lines(List.of(line))
                .build();
        return order;
    }

    @Nested
    class PlaceOrder {

        @Test
        @Timeout(2)
        void should_place_order_when_stock_is_available_and_payment_succeeds() {
            // Arrange
            Order draft = draftOrder();

            when(inventoryService.reserve(eq(SKU), eq(QUANTITY))).thenReturn(true);
            when(paymentGateway.capture(eq(ORDER_ID), eq(Money.of("USD", 50.00))))
                    .thenReturn(PaymentStatus.CAPTURED);
            when(orderRepository.save(any(Order.class))).thenAnswer(inv -> inv.getArgument(0));

            // Act
            Order placed = orderService.placeOrder(draft);

            // Assert
            assertThat(placed).isNotNull();
            assertThat(placed.status()).isEqualTo(OrderStatus.PLACED);

            verify(inventoryService).reserve(SKU, QUANTITY);
            verify(paymentGateway).capture(ORDER_ID, Money.of("USD", 50.00));
            verify(notificationService).sendOrderConfirmation(eq(CUSTOMER_ID), eq(ORDER_ID));
            verify(orderRepository, times(2)).save(any(Order.class)); // draft -> placed
        }

        @Test
        void should_fail_and_release_stock_when_payment_fails() {
            // Arrange
            Order draft = draftOrder();

            when(inventoryService.reserve(eq(SKU), eq(QUANTITY))).thenReturn(true);
            when(paymentGateway.capture(eq(ORDER_ID), any(Money.class)))
                    .thenReturn(PaymentStatus.DECLINED);

            // Act + Assert
            assertThatThrownBy(() -> orderService.placeOrder(draft))
                    .isInstanceOf(PaymentDeclinedException.class);

            verify(inventoryService).release(SKU, QUANTITY);
            verify(orderRepository, never()).save(argThat(o -> o.status() == OrderStatus.PLACED));
            verify(notificationService).sendPaymentFailed(eq(CUSTOMER_ID), eq(ORDER_ID));
        }
    }

    @Nested
    class CancelOrder {

        @Test
        void should_cancel_order_and_release_inventory_if_not_shipped() {
            // Arrange
            Order placed = draftOrder().copyWithStatus(OrderStatus.PLACED);

            when(orderRepository.findById(ORDER_ID)).thenReturn(java.util.Optional.of(placed));
            when(orderRepository.save(any(Order.class))).thenAnswer(inv -> inv.getArgument(0));

            // Act
            orderService.cancelOrder(ORDER_ID, "Customer changed mind");

            // Assert
            verify(inventoryService).release(SKU, QUANTITY);
            verify(orderRepository).save(argThat(o -> o.status() == OrderStatus.CANCELLED));
            verify(notificationService).sendOrderCancelled(CUSTOMER_ID, ORDER_ID);
        }

        @Test
        void should_throw_if_order_already_shipped() {
            // Arrange
            Order shipped = draftOrder().copyWithStatus(OrderStatus.SHIPPED);
            when(orderRepository.findById(ORDER_ID)).thenReturn(java.util.Optional.of(shipped));

            // Act + Assert
            assertThatThrownBy(() -> orderService.cancelOrder(ORDER_ID, "late request"))
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessageContaining("cannot be cancelled");

            verify(inventoryService, never()).release(anyString(), anyInt());
            verify(notificationService, never()).sendOrderCancelled(any(), any());
        }
    }
}