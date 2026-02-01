package com.sprintcart.adapters.persistence.adapter;

import com.sprintcart.adapters.persistence.entity.OrderEntity;
import com.sprintcart.adapters.persistence.jpa.OrderJpaRepository;
import com.sprintcart.adapters.persistence.mapper.OrderEntityMapper;
import com.sprintcart.domain.order.Order;
import com.sprintcart.domain.order.OrderId;
import com.sprintcart.domain.order.OrderStatus;
import com.sprintcart.domain.order.PaymentStatus;
import com.sprintcart.domain.order.repository.OrderRepository;
import com.sprintcart.domain.shared.exception.DomainEntityNotFoundException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * OrderRepositoryAdapter bridges the domain OrderRepository port with the Spring Data JPA
 * implementation. It converts between rich domain models and lightweight JPA entities and
 * makes sure the domain layer never leaks out persistence concerns.
 *
 * Hexagonal side: Outbound Adapter (Persistence)
 */
@Component
@RequiredArgsConstructor
@Slf4j
public class OrderRepositoryAdapter implements OrderRepository {

    private final OrderJpaRepository orderJpaRepository;
    private final OrderEntityMapper mapper;

    /**
     * Persists a new Order or updates an existing one. Domain models are converted
     * into JPA entities before persistence. Concurrency is handled via the
     * optimistic locking field {@code version} on {@link OrderEntity}.
     */
    @Override
    @Transactional
    public Order save(Order order) {
        try {
            OrderEntity saved = orderJpaRepository.save(mapper.toEntity(order));
            return mapper.toDomain(saved);
        } catch (DataAccessException ex) {
            log.error("Failed to persist order [{}]", order.getId(), ex);
            throw ex; // Let upper layers translate it to a domain exception / HTTP status
        }
    }

    /**
     * Retrieves an Order by its identity. If not found, an empty Optional is returned.
     */
    @Override
    @Transactional(readOnly = true)
    public Optional<Order> findById(OrderId orderId) {
        return orderJpaRepository.findById(orderId.getValue())
                                 .map(mapper::toDomain);
    }

    /**
     * Fetches a paginated list of Orders belonging to a merchant, ordered by creation date.
     * This is used intensively in the back-office grid, so the method is optimized for
     * seek-pagination to avoid deep offsets.
     */
    @Override
    @Transactional(readOnly = true)
    public List<Order> findLatestForMerchant(UUID merchantId, int page, int size) {
        Page<OrderEntity> slice = orderJpaRepository
                .findByMerchantId(
                        merchantId,
                        PageRequest.of(page, size, Sort.by(Sort.Direction.DESC, "createdAt"))
                );

        return slice.stream()
                    .map(mapper::toDomain)
                    .collect(Collectors.toList());
    }

    /**
     * Updates the PaymentStatus of an Order. Throws {@link DomainEntityNotFoundException}
     * if the order does not exist. Uses optimistic locking to prevent concurrent updates.
     */
    @Override
    @Transactional
    public void updatePaymentStatus(OrderId orderId, PaymentStatus newStatus) {
        OrderEntity entity = orderJpaRepository.findById(orderId.getValue())
                .orElseThrow(() -> new DomainEntityNotFoundException(
                        "Order with id %s not found".formatted(orderId)));

        entity.setPaymentStatus(newStatus);
        // JPA will dirty-check and flush changes at transaction commit.
        log.info("Payment status for order {} updated to {}", orderId, newStatus);
    }

    /**
     * Bulk update allowing an automation rule to transition multiple Orders
     * into a new state in a single, transactional operation.
     */
    @Override
    @Transactional
    public int bulkUpdateStatus(List<OrderId> orderIds, OrderStatus targetStatus) {
        if (orderIds.isEmpty()) {
            return 0;
        }
        List<UUID> uuids = orderIds.stream()
                                   .map(OrderId::getValue)
                                   .toList();
        int affected = orderJpaRepository.updateStatus(uuids, targetStatus);
        log.debug("Bulk status update affected {} orders", affected);
        return affected;
    }

    /**
     * Removes an Order from persistence. Usually used only in GDPR delete-me requests or
     * cleanup jobs, never in standard business flows.
     */
    @Override
    @Transactional
    public void delete(OrderId orderId) {
        if (!orderJpaRepository.existsById(orderId.getValue())) {
            throw new DomainEntityNotFoundException("Order with id %s not found".formatted(orderId));
        }
        orderJpaRepository.deleteById(orderId.getValue());
        log.info("Order [{}] deleted", orderId);
    }

    /**
     * Counts the number of orders for a merchant using a particular status. Utilised in
     * the KPI widgets displayed on the operator dashboard.
     */
    @Override
    @Transactional(readOnly = true)
    public long countByStatus(UUID merchantId, OrderStatus status) {
        return orderJpaRepository.countByMerchantIdAndStatus(merchantId, status);
    }
}