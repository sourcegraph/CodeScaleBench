```java
package com.sprintcart.application.dto.mappers;

import com.sprintcart.application.dto.AddressDto;
import com.sprintcart.application.dto.CreateOrderRequest;
import com.sprintcart.application.dto.MoneyDto;
import com.sprintcart.application.dto.OrderDto;
import com.sprintcart.application.dto.OrderLineItemDto;
import com.sprintcart.application.dto.UpdateOrderRequest;
import com.sprintcart.domain.common.Money;
import com.sprintcart.domain.order.Order;
import com.sprintcart.domain.order.OrderLineItem;
import com.sprintcart.domain.order.OrderStatus;
import com.sprintcart.domain.user.UserId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.stream.Collectors;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Component;

/**
 * Maps {@link Order} domain objects to and from their DTO representations.
 *
 * <p>The mapper intentionally contains only *pure* transformation logic—no persistence or
 * infrastructure concerns—so it can be used from anywhere, including unit tests.
 */
@Component
public class OrderMapper {

    /* ========================== TO DTO ========================== */

    /**
     * Transforms a domain {@link Order} into a serializable {@link OrderDto}.
     *
     * @param order domain order (must not be {@code null})
     * @return dto representation
     */
    public OrderDto toDto(@NonNull final Order order) {
        Objects.requireNonNull(order, "order must not be null");

        return OrderDto.builder()
                .orderId(order.getId().getValue())
                .customerId(order.getCustomerId().getValue())
                .status(order.getStatus().name())
                .lineItems(toLineItemDtos(order.getLineItems()))
                .shippingAddress(toAddressDto(order.getShippingAddress()))
                .billingAddress(toAddressDto(order.getBillingAddress()))
                .total(toMoneyDto(order.getGrandTotal()))
                .createdAt(order.getCreatedAt().atOffset(ZoneOffset.UTC))
                .updatedAt(order.getUpdatedAt().atOffset(ZoneOffset.UTC))
                .build();
    }

    /**
     * Batch variant of {@link #toDto(Order)} to avoid N+1 style loops in callers.
     */
    public List<OrderDto> toDto(final List<Order> orders) {
        if (orders == null || orders.isEmpty()) {
            return Collections.emptyList();
        }
        return orders.stream().map(this::toDto).collect(Collectors.toList());
    }

    /* ========================== FROM DTO (CREATE) ========================== */

    /**
     * Builds a new domain {@link Order} aggregate from a {@link CreateOrderRequest} DTO.
     *
     * <p>Only fields allowed on creation are mapped; for updates use {@link #applyPatch(UpdateOrderRequest, Order)}.
     */
    public Order fromCreateRequest(@NonNull final CreateOrderRequest request) {
        Objects.requireNonNull(request, "request must not be null");

        final List<OrderLineItem> lineItems = request.getLineItems().stream()
                .map(this::toLineItem)
                .toList();

        return Order.newDraft(
                UserId.of(request.getCustomerId()),
                lineItems,
                toAddress(request.getShippingAddress()),
                toAddress(request.getBillingAddress()));
    }

    /* ========================== FROM DTO (UPDATE/PATCH) ========================== */

    /**
     * Performs an in-place patch of a domain {@link Order} using the values provided
     * in a {@link UpdateOrderRequest}.
     *
     * <p>This method mutates the supplied aggregate (following rich domain model style)
     * which is later persisted by the repository.</p>
     *
     * @param patch  user provided patch (must not be {@code null})
     * @param target order aggregate to mutate (must not be {@code null})
     */
    public void applyPatch(
            @NonNull final UpdateOrderRequest patch,
            @NonNull final Order target) {

        Objects.requireNonNull(patch, "patch must not be null");
        Objects.requireNonNull(target, "target must not be null");

        if (patch.getStatus() != null) {
            target.transitionTo(OrderStatus.valueOf(patch.getStatus()));
        }

        if (patch.getShippingAddress() != null) {
            target.changeShippingAddress(toAddress(patch.getShippingAddress()));
        }

        if (patch.getBillingAddress() != null) {
            target.changeBillingAddress(toAddress(patch.getBillingAddress()));
        }

        if (patch.getLineItems() != null && !patch.getLineItems().isEmpty()) {
            // Replace the entire collection – for partial updates we would
            // implement a more granular diff algorithm.
            final List<OrderLineItem> items = patch.getLineItems().stream()
                    .map(this::toLineItem)
                    .collect(Collectors.toList());
            target.replaceLineItems(items);
        }
    }

    /* ========================== PRIVATE HELPERS ========================== */

    /* ---------- LineItem mapping ---------- */

    private List<OrderLineItemDto> toLineItemDtos(final List<OrderLineItem> items) {
        if (items == null) {
            return new ArrayList<>();
        }
        return items.stream()
                .map(li -> OrderLineItemDto.builder()
                        .sku(li.getSku().getValue())
                        .name(li.getName())
                        .quantity(li.getQuantity().getValue())
                        .unitPrice(toMoneyDto(li.getUnitPrice()))
                        .totalPrice(toMoneyDto(li.getTotalPrice()))
                        .build())
                .collect(Collectors.toList());
    }

    private OrderLineItem toLineItem(final OrderLineItemDto dto) {
        return OrderLineItem.of(
                dto.getSku(),
                dto.getName(),
                dto.getQuantity(),
                Money.of(dto.getUnitPrice().currency(), dto.getUnitPrice().amount()));
    }

    /* ---------- Address mapping ---------- */

    private AddressDto toAddressDto(final com.sprintcart.domain.common.Address source) {
        if (source == null) {
            return null;
        }
        return AddressDto.builder()
                .line1(source.getLine1())
                .line2(source.getLine2())
                .city(source.getCity())
                .state(source.getState())
                .postalCode(source.getPostalCode())
                .country(source.getCountry())
                .build();
    }

    private com.sprintcart.domain.common.Address toAddress(final AddressDto dto) {
        if (dto == null) {
            return null;
        }
        return com.sprintcart.domain.common.Address.builder()
                .line1(dto.getLine1())
                .line2(dto.getLine2())
                .city(dto.getCity())
                .state(dto.getState())
                .postalCode(dto.getPostalCode())
                .country(dto.getCountry())
                .build();
    }

    /* ---------- Money mapping ---------- */

    private MoneyDto toMoneyDto(final Money money) {
        return MoneyDto.of(money.getCurrency().getCurrencyCode(), money.getAmount());
    }
}
```