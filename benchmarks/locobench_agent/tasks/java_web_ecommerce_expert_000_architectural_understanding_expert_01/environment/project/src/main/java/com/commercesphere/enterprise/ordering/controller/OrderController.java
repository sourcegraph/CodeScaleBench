package com.commercesphere.enterprise.ordering.controller;

import com.commercesphere.enterprise.ordering.dto.CancelOrderResponse;
import com.commercesphere.enterprise.ordering.dto.OrderCreateRequest;
import com.commercesphere.enterprise.ordering.dto.OrderResponse;
import com.commercesphere.enterprise.ordering.dto.OrderSearchCriteria;
import com.commercesphere.enterprise.ordering.dto.PaymentRequest;
import com.commercesphere.enterprise.ordering.exception.OrderNotFoundException;
import com.commercesphere.enterprise.ordering.service.OrderService;
import com.commercesphere.enterprise.ordering.service.PaymentService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import java.net.URI;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springdoc.core.annotations.ParameterObject;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

/**
 * REST controller responsible for managing order–related endpoints.
 *
 * <p>All routes are prefixed with {@code /api/v1/orders}. Authentication and authorization are
 * applied using Spring Security. The controller delegates business logic to service–layer
 * components, keeping HTTP concerns separated from core domain logic.</p>
 */
@Slf4j
@Validated
@RestController
@RequestMapping(path = "/api/v1/orders", produces = MediaType.APPLICATION_JSON_VALUE)
@RequiredArgsConstructor
public class OrderController {

    private final OrderService orderService;
    private final PaymentService paymentService;

    /**
     * Returns paginated list of orders filtered by optional search criteria.
     *
     * @param page            page index (0-based)
     * @param size            page size
     * @param searchCriteria  dynamic search criteria wrapper
     * @return paginated list of orders
     */
    @GetMapping
    @PreAuthorize("hasAuthority('ORDER_READ')")
    public ResponseEntity<Page<OrderResponse>> listOrders(
            @RequestParam(defaultValue = "0") @Min(0) int page,
            @RequestParam(defaultValue = "25") @Positive int size,
            @ParameterObject OrderSearchCriteria searchCriteria
    ) {

        Pageable pageable = PageRequest.of(page, size);
        Page<OrderResponse> orders = orderService.searchOrders(searchCriteria, pageable);

        return ResponseEntity.ok(orders);
    }

    /**
     * Fetches full order details by id.
     *
     * @param orderId order UUID
     * @return OrderResponse
     */
    @GetMapping("/{orderId}")
    @PreAuthorize("hasAuthority('ORDER_READ')")
    public ResponseEntity<OrderResponse> getOrderById(@PathVariable UUID orderId) {
        return orderService.findById(orderId)
                .map(ResponseEntity::ok)
                .orElseThrow(() -> new OrderNotFoundException(orderId));
    }

    /**
     * Creates a new order from client-side request.
     *
     * @param request create request payload
     * @return Location header pointing to created resource
     */
    @PostMapping(consumes = MediaType.APPLICATION_JSON_VALUE)
    @PreAuthorize("hasAuthority('ORDER_WRITE')")
    public ResponseEntity<OrderResponse> createOrder(@Valid @RequestBody OrderCreateRequest request) {

        OrderResponse created = orderService.createOrder(request);

        URI location = URI.create(String.format("/api/v1/orders/%s", created.orderId()));
        return ResponseEntity
                .created(location)
                .body(created);
    }

    /**
     * Cancels an existing order. Orders can be cancelled only if they have not been shipped or
     * invoiced. Business rules are enforced within the service layer.
     *
     * @param orderId order UUID
     * @param reason  optional cancellation reason
     * @return cancellation response
     */
    @PutMapping("/{orderId}/cancel")
    @PreAuthorize("hasAuthority('ORDER_CANCEL')")
    public ResponseEntity<CancelOrderResponse> cancelOrder(
            @PathVariable UUID orderId,
            @RequestParam(required = false) String reason
    ) {

        CancelOrderResponse cancelled = orderService.cancel(orderId, reason);
        return ResponseEntity.ok(cancelled);
    }

    /**
     * Processes a payment for the supplied order.
     *
     * @param orderId order UUID
     * @param paymentRequest validated payment payload
     * @return no-content response if accepted
     */
    @PostMapping(
            path = "/{orderId}/payment",
            consumes = MediaType.APPLICATION_JSON_VALUE
    )
    @PreAuthorize("hasAuthority('PAYMENT_EXECUTE')")
    public ResponseEntity<Void> payOrder(
            @PathVariable UUID orderId,
            @Valid @RequestBody PaymentRequest paymentRequest
    ) {

        paymentService.executePayment(orderId, paymentRequest);

        HttpHeaders headers = new HttpHeaders();
        headers.set(HttpHeaders.LOCATION, String.format("/api/v1/orders/%s", orderId));

        return new ResponseEntity<>(headers, HttpStatus.ACCEPTED);
    }

    /* ------------------------------------------------------------------------
     * Exception Handling
     * --------------------------------------------------------------------- */

    /**
     * Handles domain-level not-found exceptions and converts them into HTTP 404.
     *
     * @param ex   unresolved order exception
     * @return standardized error payload
     */
    @ExceptionHandler(OrderNotFoundException.class)
    public ResponseEntity<ApiError> handleOrderNotFound(OrderNotFoundException ex) {
        log.warn("Order not found: {}", ex.getMessage());
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(new ApiError(HttpStatus.NOT_FOUND.value(), ex.getMessage()));
    }

    /**
     * Handles any other unanticipated exceptions with generic 500 response. In a real-world
     * scenario, this could be replaced by @ControllerAdvice for cross-cutting error handling.
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiError> handleGenericError(Exception ex) {
        log.error("Unexpected error processing order endpoint", ex);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(new ApiError(HttpStatus.INTERNAL_SERVER_ERROR.value(), "Unexpected error"));
    }

    /* ------------------------------------------------------------------------
     * DTOs for lightweight API responses
     * --------------------------------------------------------------------- */

    /**
     * Generic API error payload used by local exception handlers. A dedicated
     * {@code ErrorHandlingControllerAdvice} is recommended for large codebases.
     *
     * @param status  numerical HTTP status
     * @param message error description
     */
    public record ApiError(int status, String message) { }
}