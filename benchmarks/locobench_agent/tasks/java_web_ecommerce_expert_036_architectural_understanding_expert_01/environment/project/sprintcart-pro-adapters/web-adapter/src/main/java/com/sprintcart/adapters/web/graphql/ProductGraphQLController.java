```java
package com.sprintcart.adapters.web.graphql;

import com.sprintcart.application.port.in.catalog.CatalogMaintenanceUseCase;
import com.sprintcart.application.port.in.catalog.command.CreateProductCommand;
import com.sprintcart.application.port.in.catalog.command.DeleteProductCommand;
import com.sprintcart.application.port.in.catalog.command.UpdateProductCommand;
import com.sprintcart.application.port.in.catalog.query.FindProductQuery;
import com.sprintcart.application.port.in.catalog.query.SearchProductsQuery;
import com.sprintcart.domain.catalog.Product;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.graphql.data.method.annotation.Argument;
import org.springframework.graphql.data.method.annotation.MutationMapping;
import org.springframework.graphql.data.method.annotation.QueryMapping;
import org.springframework.stereotype.Controller;

import javax.validation.Valid;
import javax.validation.constraints.Min;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * GraphQL Controller that exposes Product-related queries & mutations.
 * <p>
 * This class is a thin adapter that translates between GraphQL-specific
 * representations and domain-level commands/queries.  It purposefully contains
 * no business logic so that the core domain remains technology-agnostic.
 */
@Slf4j
@Controller
@RequiredArgsConstructor
public class ProductGraphQLController {

    private final CatalogMaintenanceUseCase catalogMaintenance;

    /* ───────────────────────────────────────────────────
     *                     Queries
     * ─────────────────────────────────────────────────── */

    @QueryMapping(name = "product")
    public ProductDTO findProductById(@Argument @NotNull UUID id) {
        log.debug("GraphQL query 'product' called with id={}", id);
        Product product =
                catalogMaintenance.findProduct(new FindProductQuery(id))
                        .orElseThrow(() -> new ProductNotFoundGraphQLException(id));
        return mapToDto(product);
    }

    @QueryMapping(name = "products")
    public ProductPageDTO searchProducts(@Argument int page,
                                         @Argument int size,
                                         @Argument Optional<String> search,
                                         @Argument Optional<List<String>> tags) {
        Page<Product> productPage = catalogMaintenance.searchProducts(
                new SearchProductsQuery(search.orElse(null), tags.orElse(null)),
                PageRequest.of(page, size));

        List<ProductDTO> items = productPage.stream()
                                            .map(this::mapToDto)
                                            .collect(Collectors.toList());

        return new ProductPageDTO(
                items,
                productPage.getNumber(),
                productPage.getSize(),
                productPage.getTotalElements(),
                productPage.getTotalPages());
    }

    /* ───────────────────────────────────────────────────
     *                    Mutations
     * ─────────────────────────────────────────────────── */

    @MutationMapping(name = "createProduct")
    public ProductDTO createProduct(@Argument @Valid CreateProductInput input) {
        Product product = catalogMaintenance.createProduct(
                new CreateProductCommand(
                        input.sku(),
                        input.name(),
                        input.description(),
                        input.price(),
                        input.stock(),
                        input.tags())
        );
        return mapToDto(product);
    }

    @MutationMapping(name = "updateProduct")
    public ProductDTO updateProduct(@Argument @NotNull UUID id,
                                    @Argument @Valid UpdateProductInput input) {

        Product product = catalogMaintenance.updateProduct(
                new UpdateProductCommand(
                        id,
                        input.name().orElse(null),
                        input.description().orElse(null),
                        input.price().orElse(null),
                        input.stock().orElse(null),
                        input.tags().orElse(null))
        );
        return mapToDto(product);
    }

    @MutationMapping(name = "deleteProduct")
    public boolean deleteProduct(@Argument @NotNull UUID id) {
        catalogMaintenance.deleteProduct(new DeleteProductCommand(id));
        return true;
    }

    /* ───────────────────────────────────────────────────
     *                   Mapping logic
     * ─────────────────────────────────────────────────── */

    private ProductDTO mapToDto(Product product) {
        return new ProductDTO(
                product.getId(),
                product.getSku(),
                product.getName(),
                product.getDescription(),
                product.getPrice(),
                product.getStock(),
                product.getTags(),
                product.getCreatedAt(),
                product.getUpdatedAt());
    }

    /* ───────────────────────────────────────────────────
     *                    DTO / Records
     * ─────────────────────────────────────────────────── */

    /**
     * GraphQL output type representing a single Product.
     */
    public record ProductDTO(
            UUID id,
            String sku,
            String name,
            String description,
            BigDecimal price,
            int stock,
            List<String> tags,
            Instant createdAt,
            Instant updatedAt
    ) {
    }

    /**
     * GraphQL wrapper object used for offset-based pagination.
     */
    public record ProductPageDTO(
            List<ProductDTO> items,
            int page,
            int size,
            long totalElements,
            int totalPages
    ) {
    }

    /**
     * GraphQL input type for creating a new product.
     */
    public record CreateProductInput(
            @NotBlank String sku,
            @NotBlank String name,
            String description,
            @NotNull BigDecimal price,
            @Min(0) int stock,
            List<String> tags
    ) {
    }

    /**
     * GraphQL input type for updating an existing product.
     * Optional values that are absent will be ignored by the domain command.
     */
    public record UpdateProductInput(
            Optional<String> name,
            Optional<String> description,
            Optional<BigDecimal> price,
            Optional<Integer> stock,
            Optional<List<String>> tags
    ) {
    }

    /* ───────────────────────────────────────────────────
     *                 Exception handling
     * ─────────────────────────────────────────────────── */

    /**
     * Exception translated to a GraphQL error when a product cannot be found.
     */
    public static class ProductNotFoundGraphQLException extends RuntimeException {
        public ProductNotFoundGraphQLException(UUID id) {
            super("Product with id '" + id + "' does not exist");
        }
    }
}
```