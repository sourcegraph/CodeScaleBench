```java
package com.sprintcart.adapters.persistence.mapper;

import com.sprintcart.adapters.persistence.entity.MoneyEmbeddable;
import com.sprintcart.adapters.persistence.entity.OrderEntity;
import com.sprintcart.adapters.persistence.entity.OrderLineEntity;
import com.sprintcart.adapters.persistence.entity.ProductEntity;
import com.sprintcart.domain.model.order.Order;
import com.sprintcart.domain.model.order.OrderLine;
import com.sprintcart.domain.model.order.OrderStatus;
import com.sprintcart.domain.model.product.Money;
import com.sprintcart.domain.model.product.Product;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.stream.Collectors;

/**
 * PersistenceMapper converts domain objects to persistence (JPA) entities and back.
 * <p>
 * This class is intentionally kept free of any ORM-specific annotations so that
 * mapping logic remains decoupled from a particular persistence technology.
 * </p>
 */
@Component
public class PersistenceMapper {

    /**
     * Converts a domain {@link Product} into its JPA representation.
     *
     * @param product domain product
     * @return JPA entity
     * @throws MappingException if a required field is missing
     */
    public ProductEntity toProductEntity(final Product product) {
        Objects.requireNonNull(product, "product is required");

        if (product.getId() == null) {
            throw new MappingException("Product must have an id before it can be persisted.");
        }

        final ProductEntity entity = new ProductEntity();
        entity.setId(product.getId());
        entity.setSku(product.getSku());
        entity.setName(product.getName());
        entity.setDescription(product.getDescription());
        entity.setPrice(toMoneyEmbeddable(product.getPrice()));
        entity.setCreatedAt(product.getCreatedAt());
        entity.setUpdatedAt(OffsetDateTime.now());

        return entity;
    }

    /**
     * Converts a JPA {@link ProductEntity} into its domain representation.
     *
     * @param entity JPA entity
     * @return domain product
     */
    public Product toProduct(final ProductEntity entity) {
        if (entity == null) return null;

        return Product.builder()
                      .id(entity.getId())
                      .sku(entity.getSku())
                      .name(entity.getName())
                      .description(entity.getDescription())
                      .price(toMoney(entity.getPrice()))
                      .createdAt(entity.getCreatedAt())
                      .updatedAt(entity.getUpdatedAt())
                      .build();
    }

    // -----------------------------------------------------------------------
    // Order
    // -----------------------------------------------------------------------

    /**
     * Converts a domain {@link Order} into a JPA {@link OrderEntity}.
     *
     * @param order domain order
     * @return JPA order
     */
    public OrderEntity toOrderEntity(final Order order) {
        Objects.requireNonNull(order, "order is required");

        final OrderEntity entity = new OrderEntity();
        entity.setId(order.getId());
        entity.setCustomerId(order.getCustomerId());
        entity.setStatus(order.getStatus().name());
        entity.setCreatedAt(order.getCreatedAt());
        entity.setUpdatedAt(OffsetDateTime.now());
        entity.setLines(toOrderLineEntities(order.getLines(), entity));
        entity.setTotal(toMoneyEmbeddable(order.getTotal()));

        return entity;
    }

    /**
     * Converts a JPA {@link OrderEntity} to a domain {@link Order}.
     *
     * @param entity JPA entity
     * @return domain order
     */
    public Order toOrder(final OrderEntity entity) {
        if (entity == null) return null;

        return Order.builder()
                    .id(entity.getId())
                    .customerId(entity.getCustomerId())
                    .status(OrderStatus.valueOf(entity.getStatus()))
                    .createdAt(entity.getCreatedAt())
                    .updatedAt(entity.getUpdatedAt())
                    .total(toMoney(entity.getTotal()))
                    .lines(toOrderLines(entity.getLines()))
                    .build();
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private MoneyEmbeddable toMoneyEmbeddable(final Money money) {
        if (money == null) return null;

        return new MoneyEmbeddable(money.getAmount(), money.getCurrency().getCurrencyCode());
    }

    private Money toMoney(final MoneyEmbeddable embeddable) {
        if (embeddable == null) return null;

        return new Money(new BigDecimal(embeddable.getAmount()), embeddable.getCurrency());
    }

    private List<OrderLineEntity> toOrderLineEntities(final List<OrderLine> lines, OrderEntity parent) {
        if (lines == null) {
            return Collections.emptyList();
        }

        return lines.stream()
                    .map(l -> {
                        OrderLineEntity e = new OrderLineEntity();
                        e.setOrder(parent);                 // bidirectional mapping
                        e.setProductId(l.getProductId());
                        e.setQuantity(l.getQuantity());
                        e.setUnitPrice(toMoneyEmbeddable(l.getUnitPrice()));
                        return e;
                    })
                    .collect(Collectors.toList());
    }

    private List<OrderLine> toOrderLines(final List<OrderLineEntity> entities) {
        if (entities == null) {
            return Collections.emptyList();
        }

        return entities.stream()
                       .map(e -> OrderLine.builder()
                                          .productId(e.getProductId())
                                          .quantity(e.getQuantity())
                                          .unitPrice(toMoney(e.getUnitPrice()))
                                          .build())
                       .collect(Collectors.toList());
    }

    // -----------------------------------------------------------------------
    // Custom exception
    // -----------------------------------------------------------------------

    /**
     * Thrown when a domain object cannot be mapped to a persistence entity.
     */
    public static class MappingException extends RuntimeException {
        public MappingException(final String message) {
            super(message);
        }

        public MappingException(final String message, final Throwable cause) {
            super(message, cause);
        }
    }
}
```