```java
package com.sprintcart.application.service;

import com.sprintcart.domain.catalog.Product;
import com.sprintcart.domain.catalog.ProductId;
import com.sprintcart.domain.catalog.event.StockLevelChangedEvent;
import com.sprintcart.domain.catalog.exception.ProductValidationException;
import com.sprintcart.domain.catalog.validation.ProductValidator;
import com.sprintcart.domain.common.event.DomainEventPublisher;
import com.sprintcart.port.out.catalog.CatalogRepository;
import com.sprintcart.port.out.catalog.PagedResult;
import com.sprintcart.port.out.catalog.ProductSearchCriteria;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.*;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Collections;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * Unit tests for {@link CatalogService}.
 *
 * <p>Because SprintCart Pro follows a strict Hexagonal Architecture, we never hit the database
 * or the web layer here. All outbound dependencies are mocked so that business rules can be
 * verified in isolation and at light-speed.</p>
 */
@ExtendWith(MockitoExtension.class)
class CatalogServiceTest {

    @Mock
    private CatalogRepository catalogRepository;

    @Mock
    private ProductValidator productValidator;

    @Mock
    private DomainEventPublisher eventPublisher;

    @InjectMocks
    private CatalogService catalogService;

    @Captor
    ArgumentCaptor<Product> productCaptor;

    @Captor
    ArgumentCaptor<StockLevelChangedEvent> eventCaptor;

    // ---------------------------------------------------------------------
    // Positive Path Scenarios
    // ---------------------------------------------------------------------

    @Nested
    @DisplayName("When adding a new product")
    class AddProduct {

        @Test
        @DisplayName("it should persist the product and return the generated ID")
        void shouldAddProductToCatalog_whenProductIsValid() {
            // Arrange
            Product productToPersist = sampleProduct(null);               // unsaved (no ID yet)
            Product savedProduct = sampleProduct(ProductId.newId());      // returned by repository

            doNothing().when(productValidator).validate(productToPersist);
            when(catalogRepository.save(productToPersist)).thenReturn(savedProduct);

            // Act
            ProductId newProductId = catalogService.addProduct(productToPersist);

            // Assert
            assertThat(newProductId).isEqualTo(savedProduct.getId());
            verify(productValidator).validate(productToPersist);
            verify(catalogRepository).save(productCaptor.capture());

            Product captured = productCaptor.getValue();
            assertThat(captured.getCreatedAt()).isNotNull();
            assertThat(captured.getUpdatedAt()).isEqualTo(captured.getCreatedAt());
        }
    }

    @Nested
    @DisplayName("When searching products")
    class SearchCatalog {

        @Test
        @DisplayName("it should return a paginated result set")
        void shouldReturnPaginatedProducts_whenCatalogQueried() {
            // Arrange
            ProductSearchCriteria criteria = new ProductSearchCriteria(
                    "mug", null, 0, 20, "price", true);

            PagedResult<Product> expectedResult =
                    new PagedResult<>(Collections.singletonList(sampleProduct(ProductId.newId())), 1, 0, 20);

            when(catalogRepository.search(criteria)).thenReturn(expectedResult);

            // Act
            PagedResult<Product> result = catalogService.search(criteria);

            // Assert
            assertThat(result)
                    .isNotNull()
                    .hasFieldOrPropertyWithValue("totalElements", 1)
                    .hasFieldOrPropertyWithValue("pageSize", 20);
            verify(catalogRepository).search(criteria);
            verifyNoMoreInteractions(catalogRepository);
        }
    }

    // ---------------------------------------------------------------------
    // Negative / Edge-Case Scenarios
    // ---------------------------------------------------------------------

    @Nested
    @DisplayName("When validation fails")
    class ValidationFailures {

        @Test
        @DisplayName("it should throw a ProductValidationException and never hit the repository")
        void shouldThrowValidationException_whenProductInvalid() {
            // Arrange
            Product invalidProduct = sampleProduct(null);
            doThrow(new ProductValidationException("Name is required"))
                    .when(productValidator).validate(invalidProduct);

            // Act / Assert
            assertThatThrownBy(() -> catalogService.addProduct(invalidProduct))
                    .isInstanceOf(ProductValidationException.class)
                    .hasMessageContaining("Name is required");

            verify(productValidator).validate(invalidProduct);
            verifyNoInteractions(catalogRepository);
        }
    }

    // ---------------------------------------------------------------------
    // Domain Event Scenarios
    // ---------------------------------------------------------------------

    @Nested
    @DisplayName("When stock level is updated")
    class StockUpdates {

        @Test
        @DisplayName("it should persist the change and publish a StockLevelChangedEvent")
        void shouldUpdateStockAndPublishEvent_whenStockChanges() {
            // Arrange
            ProductId existingId = ProductId.newId();
            Product existing = sampleProduct(existingId).withStock(5);

            when(catalogRepository.findById(existingId)).thenReturn(Optional.of(existing));
            when(catalogRepository.save(any(Product.class))).thenAnswer(i -> i.getArgument(0));

            // Act
            catalogService.updateStock(existingId, 12);

            // Assert
            verify(catalogRepository).findById(existingId);
            verify(catalogRepository).save(productCaptor.capture());
            verify(eventPublisher).publish(eventCaptor.capture());

            Product saved = productCaptor.getValue();
            assertThat(saved.getStock()).isEqualTo(12);

            StockLevelChangedEvent evt = eventCaptor.getValue();
            assertThat(evt.getProductId()).isEqualTo(existingId);
            assertThat(evt.getNewLevel()).isEqualTo(12);
        }

        @Test
        @DisplayName("it should throw when product is not found")
        void shouldThrowWhenUpdatingStockForUnknownProduct() {
            // Arrange
            ProductId unknown = ProductId.newId();
            when(catalogRepository.findById(unknown)).thenReturn(Optional.empty());

            // Act / Assert
            assertThatThrownBy(() -> catalogService.updateStock(unknown, 7))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessageContaining("not found");

            verify(catalogRepository).findById(unknown);
            verifyNoMoreInteractions(catalogRepository);
            verifyNoInteractions(eventPublisher);
        }
    }

    // ---------------------------------------------------------------------
    // Helper factory methods
    // ---------------------------------------------------------------------

    private Product sampleProduct(ProductId id) {
        return Product.builder()
                .id(id)
                .name("SprintCart Pro Coffee Mug")
                .description("Never code without caffeine again.")
                .price(new BigDecimal("12.99"))
                .currency("USD")
                .stock(10)
                .sku("SC-MUG-" + UUID.randomUUID())
                .weightGrams(350)
                .createdAt(Instant.now())
                .updatedAt(Instant.now())
                .build();
    }
}
```