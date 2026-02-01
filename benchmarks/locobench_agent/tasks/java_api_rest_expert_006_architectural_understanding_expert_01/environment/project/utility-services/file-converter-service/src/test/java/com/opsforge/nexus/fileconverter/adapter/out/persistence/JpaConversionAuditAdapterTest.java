package com.opsforge.nexus.fileconverter.adapter.out.persistence;

import com.opsforge.nexus.fileconverter.domain.ConversionAudit;
import com.opsforge.nexus.fileconverter.domain.ConversionStatus;
import org.assertj.core.api.Assertions;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Optional;
import java.util.UUID;

/**
 * Integration-style tests for {@link JpaConversionAuditAdapter}.
 * <p>
 *  – Spins up a disposable PostgreSQL instance via {@link Testcontainers}. <br/>
 *  – Verifies create, update, and paginated find operations. <br/>
 *  – Uses AssertJ for fluent assertions.
 */
@DataJpaTest(showSql = false)
@Import({JpaConversionAuditAdapter.class})
@Testcontainers
class JpaConversionAuditAdapterTest {

    @Container
    private static final PostgreSQLContainer<?> POSTGRES =
            new PostgreSQLContainer<>("postgres:15-alpine")
                    .withDatabaseName("utility_nexus")
                    .withUsername("sa")
                    .withPassword("sa");

    /**
     * Propagates dynamic container connection info into Spring’s Environment.
     */
    @DynamicPropertySource
    static void overrideDataSourceProps(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("spring.jpa.hibernate.ddl-auto", () -> "create-drop");
    }

    @Autowired
    private JpaConversionAuditAdapter adapter;

    @Autowired
    private JpaConversionAuditRepository repository;

    private UUID correlationId;

    @BeforeEach
    void setUp() {
        correlationId = UUID.randomUUID();
    }

    @Test
    @DisplayName("Should persist an initial audit entry and retrieve it by correlation id")
    void shouldPersistInitialAudit_andRetrieveByCorrelationId() {
        // Arrange
        ConversionAudit expected = ConversionAudit.builder()
                .correlationId(correlationId)
                .originalFilename("blueprint.dwg")
                .targetFormat("pdf")
                .status(ConversionStatus.IN_PROGRESS)
                .createdAt(Instant.now().truncatedTo(ChronoUnit.MILLIS))
                .build();

        // Act
        adapter.save(expected);

        Optional<ConversionAudit> loaded =
                adapter.findByCorrelationId(correlationId);

        // Assert
        Assertions.assertThat(loaded)
                  .isPresent()
                  .get()
                  .usingRecursiveComparison()
                  .ignoringFields("id") // primary key is generated after save
                  .isEqualTo(expected);
    }

    @Test
    @DisplayName("Should update an audit entry from IN_PROGRESS → COMPLETED")
    void shouldUpdateAuditStatusToCompleted() {
        // Arrange
        ConversionAudit audit = repository.save(
                ConversionAudit.builder()
                        .correlationId(correlationId)
                        .originalFilename("sensor-data.csv")
                        .targetFormat("parquet")
                        .status(ConversionStatus.IN_PROGRESS)
                        .createdAt(Instant.now().minusSeconds(10))
                        .build()
        );

        Instant finishedAt = Instant.now().truncatedTo(ChronoUnit.MILLIS);

        // Act
        audit.markAsCompleted(finishedAt);
        adapter.save(audit);

        // Assert
        ConversionAudit reloaded =
                repository.findById(audit.getId()).orElseThrow();

        Assertions.assertThat(reloaded.getStatus())
                  .isEqualTo(ConversionStatus.COMPLETED);
        Assertions.assertThat(reloaded.getCompletedAt())
                  .isEqualTo(finishedAt);
    }

    @Test
    @DisplayName("Should paginate results ordered by creation date desc")
    void shouldPaginateAuditsByCreatedAtDesc() {
        // Arrange
        for (int i = 0; i < 15; i++) {
            adapter.save(ConversionAudit.builder()
                    .correlationId(UUID.randomUUID())
                    .originalFilename("bulk-" + i + ".txt")
                    .targetFormat("gz")
                    .status(ConversionStatus.COMPLETED)
                    .createdAt(Instant.now().minusSeconds(i))
                    .completedAt(Instant.now().minusSeconds(i - 1))
                    .build());
        }

        PageRequest pageRequest = PageRequest.of(0, 10, Sort.Direction.DESC, "createdAt");

        // Act
        Page<ConversionAudit> firstPage = repository.findAll(pageRequest);

        // Assert
        Assertions.assertThat(firstPage)
                  .hasSize(10)
                  .extracting(ConversionAudit::getCreatedAt)
                  .isSortedAccordingTo(Sort.Direction.DESC.isAscending()
                          ? Instant::compareTo
                          : (a, b) -> b.compareTo(a));
    }
}