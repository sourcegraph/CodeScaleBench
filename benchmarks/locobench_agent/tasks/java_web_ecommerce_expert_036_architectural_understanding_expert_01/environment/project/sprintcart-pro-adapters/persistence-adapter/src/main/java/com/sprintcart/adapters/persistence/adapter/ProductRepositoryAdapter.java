```java
package com.sprintcart.adapters.persistence.adapter;

import com.sprintcart.adapters.persistence.mapper.ProductEntityMapper;
import com.sprintcart.adapters.persistence.repository.ProductJpaRepository;
import com.sprintcart.adapters.persistence.specification.ProductSpecifications;
import com.sprintcart.domain.catalog.Product;
import com.sprintcart.domain.catalog.ProductId;
import com.sprintcart.domain.catalog.port.ProductRepository;
import jakarta.persistence.EntityNotFoundException;
import jakarta.persistence.OptimisticLockException;
import jakarta.validation.constraints.NotNull;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Objects;
import java.util.Optional;

/**
 * ProductRepositoryAdapter is the concrete outbound adapter that bridges the domain’s
 * {@link ProductRepository} abstraction with the persistence layer (PostgreSQL via Spring-Data JPA).
 *
 * <p>The class is intentionally <b>transactional</b> and makes no assumptions about the caller’s
 * transaction boundary. Fine-grained read-only transactions are declared at method level to
 * leverage PostgreSQL MVCC performance optimisations.</p>
 *
 * <p>All mapping between the domain object {@link Product} and the JPA entity is delegated to
 * {@link ProductEntityMapper} (MapStruct implementation) to keep the adapter slim and testable.</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ProductRepositoryAdapter implements ProductRepository {

    private final ProductJpaRepository jpaRepository;
    private final ProductEntityMapper mapper;
    private final ApplicationEventPublisher eventPublisher;

    /* --------------------------------------------------------------------
     * Query methods
     * -------------------------------------------------------------------- */

    @Override
    @Transactional(readOnly = true)
    public Optional<Product> findById(@NotNull ProductId id) {
        Objects.requireNonNull(id, "product id must not be null");
        return jpaRepository.findById(id.value())
                            .map(mapper::toDomain);
    }

    @Override
    @Transactional(readOnly = true)
    public Optional<Product> findBySku(@NotNull String sku) {
        return jpaRepository.findBySku(sku)
                            .map(mapper::toDomain);
    }

    @Override
    @Transactional(readOnly = true)
    public Page<Product> search(String keyword, List<Long> categoryIds, Pageable pageable) {
        Specification<?> spec = Specification.where(
                ProductSpecifications.matchesKeyword(keyword)
                        .and(ProductSpecifications.belongsToCategories(categoryIds))
                        .and(ProductSpecifications.isNotArchived())
        );
        //noinspection unchecked – Dynamic Specification type resolution is safe here
        Page<?> entities = jpaRepository.findAll((Specification) spec, pageable);
        return entities.map(entity -> mapper.toDomain((com.sprintcart.adapters.persistence.entity.ProductEntity) entity));
    }

    /* --------------------------------------------------------------------
     * Command methods
     * -------------------------------------------------------------------- */

    @Override
    @Transactional
    public Product save(@NotNull Product product) {
        Objects.requireNonNull(product, "product must not be null");
        try {
            var savedEntity = jpaRepository.save(mapper.toEntity(product));
            log.debug("Persisted product [{}]", savedEntity.getId());

            // Publish a Spring event so that other bounded contexts (e.g., search indexing)
            // can react without tight coupling.
            eventPublisher.publishEvent(new ProductSavedEvent(product));

            return mapper.toDomain(savedEntity);
        } catch (DataIntegrityViolationException e) {
            log.error("Constraint violation while saving product [{}]", product.getId(), e);
            throw new ProductRepositoryException("Cannot save product – database constraint violated", e);
        }
    }

    @Override
    @Transactional
    public void deleteById(@NotNull ProductId id) {
        Objects.requireNonNull(id, "product id must not be null");
        try {
            if (!jpaRepository.existsById(id.value())) {
                throw new EntityNotFoundException("Product " + id + " not found");
            }
            jpaRepository.deleteById(id.value());
            eventPublisher.publishEvent(new ProductDeletedEvent(id));
            log.info("Deleted product [{}]", id);
        } catch (OptimisticLockException e) {
            log.warn("Concurrent modification detected while deleting product [{}]", id);
            throw e;
        }
    }

    @Override
    @Transactional
    public void updateStock(@NotNull ProductId id, int delta) {
        Objects.requireNonNull(id, "product id must not be null");
        int updated = jpaRepository.incrementStock(id.value(), delta);
        if (updated != 1) {
            throw new OptimisticLockException("Failed to update stock for product " + id);
        }
        eventPublisher.publishEvent(new ProductStockChangedEvent(id, delta));
        log.debug("Adjusted stock of product [{}] by delta {}", id, delta);
    }

    /* --------------------------------------------------------------------
     * Helper classes / events
     * -------------------------------------------------------------------- */

    public record ProductSavedEvent(Product product) {}
    public record ProductDeletedEvent(ProductId id) {}
    public record ProductStockChangedEvent(ProductId id, int delta) {}

    public static class ProductRepositoryException extends RuntimeException {
        public ProductRepositoryException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
```