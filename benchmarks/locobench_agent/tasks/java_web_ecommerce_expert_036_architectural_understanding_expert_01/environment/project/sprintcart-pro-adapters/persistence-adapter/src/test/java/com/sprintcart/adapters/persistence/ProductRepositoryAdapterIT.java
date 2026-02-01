package com.sprintcart.adapters.persistence;

import com.sprintcart.domain.catalog.Money;
import com.sprintcart.domain.catalog.Product;
import com.sprintcart.domain.catalog.ProductId;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.junit.jupiter.SpringExtension;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.math.BigDecimal;
import java.time.Duration;
import java.util.Currency;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.*;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * Integration tests for {@link ProductRepositoryAdapter}.
 * <p>
 * The tests spin up a disposable PostgreSQL database via Testcontainers to
 * verify that the adapter correctly interacts with the real persistence layer
 * (JPA, transactions, optimistic locking, etc.).
 */
@ExtendWith(SpringExtension.class)
@SpringBootTest
@Testcontainers
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
class ProductRepositoryAdapterIT {

    /**
     * Spin-up a lightweight Postgres instance for the entire test class.
     */
    @Container
    static final PostgreSQLContainer<?> POSTGRES =
            new PostgreSQLContainer<>("postgres:15-alpine")
                    .withDatabaseName("sprintcart")
                    .withUsername("sc_admin")
                    .withPassword("secret");

    @DynamicPropertySource
    static void registerDynamicProps(final DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
    }

    @Autowired
    private ProductRepositoryAdapter productRepository;

    @BeforeEach
    void setUp() {
        productRepository.deleteAll(); // Make sure each test starts from a clean slate.
    }

    @Test
    @DisplayName("Should persist and load a product by its technical identifier")
    void shouldPersistAndLoadProduct() {
        // Arrange
        Product original = sampleProductBuilder().build();
        productRepository.save(original);

        // Act
        Optional<Product> reloaded = productRepository.findById(original.id());

        // Assert
        assertThat(reloaded).isPresent();
        assertThat(reloaded.get()).usingRecursiveComparison()
                                   .ignoringFields("version") // JPA version column is managed by the ORM.
                                   .isEqualTo(original);
    }

    @Test
    @DisplayName("Should be able to look-up a product by its merchant-defined SKU")
    void shouldFindProductBySku() {
        // Arrange
        Product hoodie = sampleProductBuilder().sku("SPR-HOOD-01").build();
        productRepository.save(hoodie);

        // Act
        Optional<Product> bySku = productRepository.findBySkuIgnoreCase("spr-hood-01");

        // Assert
        assertThat(bySku).isPresent();
        assertThat(bySku.get().sku()).isEqualTo("SPR-HOOD-01");
    }

    @Test
    @Timeout(value = 10)
    @DisplayName("Should enforce optimistic locking when concurrent updates collide")
    void shouldHandleOptimisticLocking() throws Exception {
        // Arrange
        Product product = productRepository.save(sampleProductBuilder().build());

        // Load the same aggregate twice, simulating two concurrent transactions.
        Product p1 = productRepository.findById(product.id()).orElseThrow();
        Product p2 = productRepository.findById(product.id()).orElseThrow();

        ExecutorService pool = Executors.newFixedThreadPool(2);
        Future<?> txn1 = pool.submit(() -> {
            Product updated = p1.reprice(Money.of(new BigDecimal("79.90"), Currency.getInstance("USD")));
            productRepository.save(updated);
        });

        Future<?> txn2 = pool.submit(() -> {
            Product updated = p2.adjustInventory(5);
            // Second save is expected to fail because the entity version has been bumped by txn1.
            assertThrows(OptimisticLockingFailureException.class, () -> productRepository.save(updated));
        });

        // Assert
        txn1.get(5, TimeUnit.SECONDS);
        txn2.get(5, TimeUnit.SECONDS);
        pool.shutdownNow();
    }

    // ------------------------------------------------------------------------
    // Helper methods
    // ------------------------------------------------------------------------

    private static Product.Builder sampleProductBuilder() {
        return Product.builder()
                      .id(ProductId.of(UUID.randomUUID()))
                      .name("Super-Soft Hoodie")
                      .sku("SPR-HOOD-01")
                      .description("A hoodie so soft you'll never want to take it off.")
                      .price(Money.of(new BigDecimal("89.90"), Currency.getInstance("USD")))
                      .inventory(12);
    }
}