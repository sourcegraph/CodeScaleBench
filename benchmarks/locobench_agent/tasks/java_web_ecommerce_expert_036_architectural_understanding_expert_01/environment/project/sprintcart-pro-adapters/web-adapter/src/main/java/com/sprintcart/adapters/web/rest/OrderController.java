```java
package com.sprintcart.adapters.web.rest;

import com.sprintcart.application.port.in.OrderCommandUseCase;
import com.sprintcart.application.port.in.OrderQueryUseCase;
import com.sprintcart.application.port.in.command.CancelOrderCommand;
import com.sprintcart.application.port.in.command.CreateOrderCommand;
import com.sprintcart.application.port.in.command.UpdateOrderStatusCommand;
import com.sprintcart.domain.order.Order;
import com.sprintcart.domain.order.OrderId;
import com.sprintcart.domain.order.OrderStatus;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import lombok.AccessLevel;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.experimental.FieldDefaults;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

/**
 * OrderController is the entry point for all Order-related HTTP traffic.
 * <p>
 * This class is intentionally thin.  It validates request/response contracts
 * and delegates business logic to hexagonal ports.
 * </p>
 */
@RestController
@RequestMapping("/api/v1/orders")
@RequiredArgsConstructor
@Validated
public class OrderController {

    private static final Logger log = LoggerFactory.getLogger(OrderController.class);

    private final OrderCommandUseCase orderCommandUseCase;
    private final OrderQueryUseCase   orderQueryUseCase;

    // ----------------------------------------------------------------------
    // Create Order
    // ----------------------------------------------------------------------

    @PostMapping
    public ResponseEntity<OrderResponse> createOrder(
            @RequestHeader(value = "X-Correlation-Id", required = false) String correlationId,
            @Valid @RequestBody CreateOrderRequest request) {

        CreateOrderCommand command = toCommand(request);

        Order created = orderCommandUseCase.createOrder(command);

        log.info("[{}] Order {} created for customer {}", correlationId, created.id(), created.customerId());

        return ResponseEntity
                .status(HttpStatus.CREATED)
                .headers(correlationIdHeader(correlationId))
                .body(OrderResponse.from(created));
    }

    // ----------------------------------------------------------------------
    // Get Order By Id
    // ----------------------------------------------------------------------

    @GetMapping("/{orderId}")
    public ResponseEntity<OrderResponse> getOrder(
            @RequestHeader(value = "X-Correlation-Id", required = false) String correlationId,
            @PathVariable("orderId") String orderId) {

        OrderId id   = OrderId.of(orderId);
        Order   view = orderQueryUseCase.getOrderById(id);

        return ResponseEntity
                .ok()
                .headers(correlationIdHeader(correlationId))
                .body(OrderResponse.from(view));
    }

    // ----------------------------------------------------------------------
    // Paginated list
    // ----------------------------------------------------------------------

    @GetMapping
    public ResponseEntity<Page<OrderResponse>> listOrders(
            @RequestHeader(value = "X-Correlation-Id", required = false) String correlationId,
            @RequestParam(defaultValue = "0") @Min(0) int page,
            @RequestParam(defaultValue = "20") @Min(1) int size,
            @RequestParam(defaultValue = "createdAt,desc") String sort) {

        String[] sortParts = sort.split(",");
        Sort      sorting   = Sort.by(Sort.Direction.fromString(sortParts[1]), sortParts[0]);
        PageRequest pageReq = PageRequest.of(page, size, sorting);

        Page<OrderResponse> orders = orderQueryUseCase.findOrders(pageReq)
                                                      .map(OrderResponse::from);

        return ResponseEntity.ok()
                             .headers(correlationIdHeader(correlationId))
                             .body(orders);
    }

    // ----------------------------------------------------------------------
    // Cancel Order
    // ----------------------------------------------------------------------

    @PostMapping("/{orderId}/cancel")
    public ResponseEntity<Void> cancelOrder(
            @RequestHeader(value = "X-Correlation-Id", required = false) String correlationId,
            @PathVariable("orderId") String orderId,
            @RequestParam(value = "reason", required = false) String reason) {

        orderCommandUseCase.cancelOrder(
                CancelOrderCommand.builder()
                        .orderId(OrderId.of(orderId))
                        .reason(reason)
                        .build());

        log.info("[{}] Order {} cancelled. Reason={}", correlationId, orderId, reason);

        return ResponseEntity.noContent()
                             .headers(correlationIdHeader(correlationId))
                             .build();
    }

    // ----------------------------------------------------------------------
    // Update Status (e.g. mark as shipped, delivered, etc.)
    // ----------------------------------------------------------------------

    @PatchMapping("/{orderId}/status")
    public ResponseEntity<Void> updateStatus(
            @RequestHeader(value = "X-Correlation-Id", required = false) String correlationId,
            @PathVariable("orderId") String orderId,
            @Valid @RequestBody UpdateStatusRequest request) {

        orderCommandUseCase.updateOrderStatus(
                UpdateOrderStatusCommand.builder()
                        .orderId(OrderId.of(orderId))
                        .status(request.getStatus())
                        .note(request.getNote())
                        .build());

        log.info("[{}] Order {} status updated to {}", correlationId, orderId, request.status);

        return ResponseEntity.noContent()
                             .headers(correlationIdHeader(correlationId))
                             .build();
    }

    // ----------------------------------------------------------------------
    // Helpers
    // ----------------------------------------------------------------------

    /**
     * Convert incoming DTO to the domain-level CreateOrderCommand.
     */
    private CreateOrderCommand toCommand(CreateOrderRequest req) {
        return CreateOrderCommand.builder()
                .customerId(req.getCustomerId())
                .shippingAddress(req.getShippingAddress())
                .paymentMethodId(req.getPaymentMethodId())
                .items(req.toLineItemCommands())
                .build();
    }

    private HttpHeaders correlationIdHeader(String correlationId) {
        HttpHeaders headers = new HttpHeaders();
        if (correlationId != null && !correlationId.isBlank()) {
            headers.add("X-Correlation-Id", correlationId);
        }
        return headers;
    }

    // ----------------------------------------------------------------------
    // DTOs
    // ----------------------------------------------------------------------

    @Data
    @Builder
    @FieldDefaults(level = AccessLevel.PRIVATE)
    static class CreateOrderRequest {

        @NotBlank String customerId;
        @NotBlank String shippingAddress;
        @NotBlank String paymentMethodId;

        @NotEmpty
        @Valid
        java.util.List<LineItemDTO> items;

        java.util.List<CreateOrderCommand.LineItemCommand> toLineItemCommands() {
            return items.stream()
                        .map(i -> new CreateOrderCommand.LineItemCommand(i.productId, i.quantity, i.unitPrice))
                        .toList();
        }
    }

    @Data
    @Builder
    @FieldDefaults(level = AccessLevel.PRIVATE)
    static class LineItemDTO {
        @NotBlank String productId;
        @Min(1)    int    quantity;
        @Min(0)    long   unitPrice; // in minor units (e.g. cents)
    }

    @Data
    @Builder
    @AllArgsConstructor
    @FieldDefaults(level = AccessLevel.PRIVATE)
    static class UpdateStatusRequest {
        @NotNull OrderStatus status;
        String  note;
    }

    /**
     * Public-facing Order projection.
     * Any internal fields (costs, internal notes, etc.) are excluded.
     */
    @Data
    @Builder
    @FieldDefaults(level = AccessLevel.PRIVATE)
    static class OrderResponse {
        String            id;
        String            customerId;
        OrderStatus       status;
        long              totalAmount;
        java.time.Instant createdAt;
        java.util.List<LineItemDTO> items;

        static OrderResponse from(Order order) {
            return OrderResponse.builder()
                    .id(order.id().value())
                    .customerId(order.customerId())
                    .status(order.status())
                    .totalAmount(order.totalAmount())
                    .createdAt(order.createdAt())
                    .items(order.lineItems().stream()
                                 .map(li -> LineItemDTO.builder()
                                         .productId(li.productId())
                                         .quantity(li.quantity())
                                         .unitPrice(li.unitPrice())
                                         .build())
                                 .toList())
                    .build();
        }
    }

    // ----------------------------------------------------------------------
    // Exception Handling (kept local for controller-specific mapping)
    // ----------------------------------------------------------------------

    @ExceptionHandler(com.sprintcart.domain.exception.OrderNotFoundException.class)
    public ResponseEntity<ErrorResponse> handleNotFound(
            com.sprintcart.domain.exception.OrderNotFoundException ex) {

        ErrorResponse body = new ErrorResponse("ORDER_NOT_FOUND", ex.getMessage());
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(body);
    }

    @ExceptionHandler({IllegalArgumentException.class, org.springframework.web.bind.MethodArgumentNotValidException.class})
    public ResponseEntity<ErrorResponse> handleBadRequest(Exception ex) {
        ErrorResponse body = new ErrorResponse("BAD_REQUEST", ex.getMessage());
        return ResponseEntity.badRequest().body(body);
    }

    // Basic error payload
    @Data
    @AllArgsConstructor
    static class ErrorResponse {
        String code;
        String message;
    }
}
```