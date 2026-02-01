package com.sprintcart.application.dto.mappers;

import com.sprintcart.application.dto.ProductDto;
import com.sprintcart.domain.model.product.Money;
import com.sprintcart.domain.model.product.Product;
import com.sprintcart.domain.model.product.ProductStatus;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.ZoneOffset;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * ProductMapper converts between domain {@link Product} entities and {@link ProductDto} data-transfer objects.
 *
 * <p>Because DTOs are used by the presentation layer (REST/GraphQL controllers) and the Product entity
 * belongs to the domain core, mapping logic lives inside the application layer to preserve
 * the direction of dependencies defined by Hexagonal Architecture.</p>
 *
 * <p>The mapper is intentionally implemented manually instead of relying on code-generation frameworks
 * (e.g. MapStruct) so that we can embed custom conversion logic and guardrails which are important
 * for a high-traffic, multi-tenant system such as SprintCart Pro.</p>
 */
@Component
public class ProductMapper {

    /**
     * Converts a {@link Product} into an immutable {@link ProductDto}. Returns {@code null} if the
     * supplied entity is {@code null}.
     */
    public ProductDto toDto(Product entity) {
        if (entity == null) {
            return null;
        }

        return ProductDto.builder()
                .id(entity.getId())
                .sku(entity.getSku())
                .name(entity.getName())
                .description(entity.getDescription())
                .price(entity.getPrice().getAmount())
                .currency(entity.getPrice().getCurrencyCode())
                .status(entity.getStatus().name())
                .stockQuantity(entity.getStockQuantity())
                .localizedNames(
                        Optional.ofNullable(entity.getLocalizedNames())
                                .orElse(Collections.emptyMap())
                                .entrySet()
                                .stream()
                                .collect(Collectors.toMap(
                                        entry -> entry.getKey().toLanguageTag(),
                                        entry -> entry.getValue())))
                .createdAt(entity.getCreatedAt().toInstant(ZoneOffset.UTC))
                .updatedAt(entity.getUpdatedAt().toInstant(ZoneOffset.UTC))
                .version(entity.getVersion())
                .build();
    }

    /**
     * Creates a new {@link Product} based on the incoming {@link ProductDto}.
     * <p>
     *     This method is used primarily when creating products via the public API.
     *     For updates, {@link #copyNonNullFields(ProductDto, Product)} should be used instead.
     * </p>
     *
     * @throws IllegalArgumentException if mandatory fields (name, price, sku, currency) are missing.
     */
    public Product fromDto(@NonNull ProductDto dto) {
        validateForCreation(dto);

        Money money = new Money(dto.getPrice(), dto.getCurrency());

        return Product.builder()
                .id(Optional.ofNullable(dto.getId()).orElseGet(UUID::randomUUID))
                .sku(dto.getSku().trim())
                .name(dto.getName().trim())
                .description(Objects.toString(dto.getDescription(), "").trim())
                .price(money)
                .status(ProductStatus.valueOf(dto.getStatus() != null
                        ? dto.getStatus()
                        : ProductStatus.DRAFT.name()))
                .stockQuantity(Math.max(0, dto.getStockQuantity()))
                .localizedNames(parseLocalizedNames(dto))
                .build();
    }

    /**
     * Copies only the non-null fields from {@code dto} into the existing product entity.
     * Useful for PATCH semantics where the client can partially update an entity.
     */
    public void copyNonNullFields(@NonNull ProductDto dto, @NonNull Product target) {
        if (dto.getSku() != null)       target.setSku(dto.getSku().trim());
        if (dto.getName() != null)      target.setName(dto.getName().trim());
        if (dto.getDescription() != null) target.setDescription(dto.getDescription().trim());

        if (dto.getPrice() != null || dto.getCurrency() != null) {
            BigDecimal amount   = Optional.ofNullable(dto.getPrice()).orElse(target.getPrice().getAmount());
            String currencyCode = Optional.ofNullable(dto.getCurrency()).orElse(target.getPrice().getCurrencyCode());
            target.setPrice(new Money(amount, currencyCode));
        }

        if (dto.getStatus() != null) {
            target.setStatus(ProductStatus.valueOf(dto.getStatus()));
        }

        if (dto.getStockQuantity() != null) {
            target.setStockQuantity(Math.max(0, dto.getStockQuantity()));
        }

        if (dto.getLocalizedNames() != null && !dto.getLocalizedNames().isEmpty()) {
            target.getLocalizedNames().putAll(parseLocalizedNames(dto));
        }
    }

    /**
     * Converts a list of entities into DTOs preserving order.
     */
    public List<ProductDto> toDtos(List<Product> products) {
        if (products == null || products.isEmpty()) {
            return Collections.emptyList();
        }
        return products.stream()
                .map(this::toDto)
                .collect(Collectors.toList());
    }

    // ------------------------------------------------------------------------
    // Internal helpers
    // ------------------------------------------------------------------------

    private void validateForCreation(ProductDto dto) {
        String missing = null;
        if (dto.getSku() == null)       missing = "sku";
        else if (dto.getName() == null) missing = "name";
        else if (dto.getPrice() == null)    missing = "price";
        else if (dto.getCurrency() == null) missing = "currency";

        if (missing != null) {
            throw new IllegalArgumentException("Cannot create Product – mandatory field '" + missing + "' is null");
        }
    }

    private static java.util.Map<Locale, String> parseLocalizedNames(ProductDto dto) {
        if (dto.getLocalizedNames() == null) {
            return Collections.emptyMap();
        }
        return dto.getLocalizedNames()
                .entrySet()
                .stream()
                .collect(Collectors.toMap(
                        entry -> Locale.forLanguageTag(entry.getKey()),
                        java.util.Map.Entry::getValue));
    }
}