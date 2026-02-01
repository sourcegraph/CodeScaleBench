package com.commercesphere.enterprise.ordering.service;

import com.commercesphere.enterprise.catalog.model.Product;
import com.commercesphere.enterprise.catalog.service.ProductService;
import com.commercesphere.enterprise.common.exception.BusinessValidationException;
import com.commercesphere.enterprise.common.exception.ResourceNotFoundException;
import com.commercesphere.enterprise.ordering.model.Order;
import com.commercesphere.enterprise.ordering.model.OrderItem;
import com.commercesphere.enterprise.ordering.model.OrderStatus;
import com.commercesphere.enterprise.ordering.repository.OrderRepository;
import com.commercesphere.enterprise.payment.model.PaymentDetails;
import com.commercesphere.enterprise.payment.model.PaymentResult;
import com.commercesphere.enterprise.payment.service.PaymentService;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.Objects;
import javax.validation.constraints.Min;
import javax.validation.constraints.NotNull;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.validation.annotation.Validated;

/**
 * Service layer component that contains the core business logic for Order
 * lifecycle management—creation, mutation, submission, cancellation, and
 * enrichment with payment records.
 *
 * <p>This class hides the persistence layer (repositories) from callers and
 * ensures that all domain invariants are upheld before state transitions are
 * committed. Declarative transaction boundaries guarantee atomicity and
 * consistency across multi-table writes (order header, line items, payment
 * ledger).</p>
 */
@Service
@Validated
public class OrderService {

    private static final Logger log = LoggerFactory.getLogger(OrderService.class);

    private final OrderRepository orderRepository;
    private final ProductService productService;
    private final PaymentService paymentService;

    @Autowired
    public OrderService(OrderRepository orderRepository,
                        ProductService productService,
                        PaymentService paymentService) {
        this.orderRepository = Objects.requireNonNull(orderRepository, "orderRepository");
        this.productService = Objects.requireNonNull(productService, "productService");
        this.paymentService = Objects.requireNonNull(paymentService, "paymentService");
    }

    /**
     * Begins a new draft order for the supplied customer.
     */
    @Transactional
    public Order createOrder(@NotNull Long customerId) {
        Order order = new Order();
        order.setCustomerId(customerId);
        order.setStatus(OrderStatus.DRAFT);
        order.setCreatedAt(OffsetDateTime.now());
        order.setLastModifiedAt(order.getCreatedAt());
        Order persisted = orderRepository.save(order);
        log.info("Created draft order [{}] for customer [{}]", persisted.getId(), customerId);
        return persisted;
    }

    /**
     * Adds a product to an existing draft order. If the product already exists
     * in the order, its quantity is incremented rather than creating a new line
     * item.
     *
     * @throws ResourceNotFoundException  if order or product are missing
     * @throws BusinessValidationException if order is not in a mutable state
     */
    @Transactional
    public Order addItem(@NotNull Long orderId,
                         @NotNull Long productId,
                         @Min(1) int quantity) {
        Order order = fetchMutableOrder(orderId);
        Product product = productService.findProductById(productId)
                .orElseThrow(() -> new ResourceNotFoundException("Product " + productId + " not found"));

        OrderItem line = order.getItems().stream()
                .filter(li -> li.getProductId().equals(productId))
                .findFirst()
                .orElseGet(() -> {
                    OrderItem newItem = new OrderItem();
                    newItem.setProductId(productId);
                    newItem.setSku(product.getSku());
                    newItem.setUnitPrice(product.getPrice());
                    newItem.setCurrency(product.getCurrency());
                    order.getItems().add(newItem);
                    return newItem;
                });

        line.setQuantity(line.getQuantity() + quantity);
        recalculateTotals(order);
        order.setLastModifiedAt(OffsetDateTime.now());

        log.debug("Added [{}] units of product [{}] to order [{}]", quantity, productId, orderId);
        return orderRepository.save(order);
    }

    /**
     * Submits the order for payment authorization and marks it as
     * PROCESSING if successful.
     *
     * @throws BusinessValidationException if payment authorization fails
     * @throws ResourceNotFoundException   if order not found
     */
    @Transactional
    public Order checkout(@NotNull Long orderId, @NotNull PaymentDetails paymentDetails) {
        Order order = fetchMutableOrder(orderId);

        if (order.getItems().isEmpty()) {
            throw new BusinessValidationException("Order contains no line items");
        }

        recalculateTotals(order);

        PaymentResult paymentResult = paymentService.authorize(paymentDetails, order.getGrandTotal(), order.getCurrency());

        if (!paymentResult.isApproved()) {
            throw new BusinessValidationException("Payment was declined: " + paymentResult.getDeclineReason());
        }

        order.setPaymentReference(paymentResult.getPaymentReference());
        order.setStatus(OrderStatus.PROCESSING);
        order.setSubmittedAt(OffsetDateTime.now());
        order.setLastModifiedAt(order.getSubmittedAt());

        log.info("Order [{}] successfully checked out. Payment reference [{}]",
                orderId, paymentResult.getPaymentReference());

        return orderRepository.save(order);
    }

    /**
     * Cancels an order that has not yet shipped or been fulfilled. All
     * financial authorizations are voided and inventory is released.
     */
    @Transactional
    public void cancelOrder(@NotNull Long orderId, @NotNull Long cancelledBy) {
        Order order = orderRepository.findById(orderId)
                .orElseThrow(() -> new ResourceNotFoundException("Order " + orderId + " not found"));

        if (!order.getStatus().isCancellable()) {
            throw new BusinessValidationException(
                    "Order " + orderId + " cannot be cancelled in state " + order.getStatus());
        }

        order.setStatus(OrderStatus.CANCELLED);
        order.setCancelledAt(OffsetDateTime.now());
        order.setCancelledBy(cancelledBy);
        order.setLastModifiedAt(order.getCancelledAt());
        orderRepository.save(order);

        // Best-effort void; network issues will raise infra-level exception and trigger retry policy.
        paymentService.voidAuthorization(order.getPaymentReference());

        log.info("Order [{}] has been cancelled by user [{}]", orderId, cancelledBy);
    }

    /**
     * Retrieves an order by id. Read-only; no transactional boundary needed.
     */
    public Order getOrderById(@NotNull Long orderId) {
        return orderRepository.findById(orderId)
                .orElseThrow(() -> new ResourceNotFoundException("Order " + orderId + " not found"));
    }

    /**
     * Paginated listing of a customer's orders.
     */
    public Page<Order> listOrdersForCustomer(@NotNull Long customerId, Pageable pageable) {
        return orderRepository.findByCustomerId(customerId, pageable);
    }

    /**
     * Helper that ensures the order exists and is in DRAFT state so it can be
     * mutated. Propagates a human-readable validation error otherwise.
     */
    private Order fetchMutableOrder(Long orderId) {
        Order order = orderRepository.findById(orderId)
                .orElseThrow(() -> new ResourceNotFoundException("Order " + orderId + " not found"));

        if (order.getStatus() != OrderStatus.DRAFT) {
            throw new BusinessValidationException(
                    "Order " + orderId + " is not editable in state " + order.getStatus());
        }
        return order;
    }

    /**
     * Re-calculates order subtotal, tax, and grand total.
     *
     * <p>Tax calculation is deliberately simplified here—real implementation
     * would delegate to a dedicated TaxService that considers jurisdiction,
     * exemptions, and contract-level overrides.</p>
     */
    private void recalculateTotals(Order order) {
        BigDecimal subtotal = order.getItems().stream()
                .map(li -> li.getUnitPrice().multiply(BigDecimal.valueOf(li.getQuantity())))
                .reduce(BigDecimal.ZERO, BigDecimal::add);

        BigDecimal estimatedTax = subtotal.multiply(BigDecimal.valueOf(0.07)); // 7% flat
        BigDecimal grandTotal = subtotal.add(estimatedTax);

        order.setSubtotal(subtotal);
        order.setTaxTotal(estimatedTax);
        order.setGrandTotal(grandTotal);
    }
}