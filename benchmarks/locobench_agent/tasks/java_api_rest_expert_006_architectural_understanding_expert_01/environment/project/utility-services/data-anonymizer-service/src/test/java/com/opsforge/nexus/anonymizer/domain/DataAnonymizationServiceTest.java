package com.opsforge.nexus.anonymizer.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.opsforge.nexus.anonymizer.domain.model.Customer;
import com.opsforge.nexus.anonymizer.domain.strategy.AnonymizationStrategy;
import com.opsforge.nexus.anonymizer.domain.strategy.AnonymizationStrategyRegistry;
import com.opsforge.nexus.common.exception.DomainException;
import java.time.LocalDate;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/**
 * Unit‐tests for {@link DataAnonymizationService}.
 *
 * <p>These tests focus strictly on domain behavior without involving Spring, persistence, or web
 * layers. All collaborators are provided via Mockito and verified for correct interaction.</p>
 */
@ExtendWith(MockitoExtension.class)
class DataAnonymizationServiceTest {

    private static final String ANONYMIZED_NAME   = "REDACTED_NAME";
    private static final String ANONYMIZED_EMAIL  = "anon+123@opsforge.com";
    private static final String ANONYMIZED_PHONE  = "XXX-XXX-XXXX";

    @Mock
    private AnonymizationStrategyRegistry strategyRegistry;

    @Mock
    private AnonymizationStrategy          nameStrategy;
    @Mock
    private AnonymizationStrategy          emailStrategy;
    @Mock
    private AnonymizationStrategy          phoneStrategy;

    @InjectMocks
    private DataAnonymizationService anonymizationService;

    private Customer plainCustomer;

    @BeforeEach
    void setUp() {
        // Input object that mimics an inbound DTO.
        plainCustomer = new Customer(
                "John Doe",
                "john.doe@opsforge.com",
                "+1-212-555-0198",
                LocalDate.of(1988, 9, 9));

        // Strategy registry wiring
        when(strategyRegistry.getStrategyForField("name")).thenReturn(nameStrategy);
        when(strategyRegistry.getStrategyForField("email")).thenReturn(emailStrategy);
        when(strategyRegistry.getStrategyForField("phone")).thenReturn(phoneStrategy);

        // Expected anonymization results
        when(nameStrategy.anonymize("John Doe")).thenReturn(ANONYMIZED_NAME);
        when(emailStrategy.anonymize("john.doe@opsforge.com")).thenReturn(ANONYMIZED_EMAIL);
        when(phoneStrategy.anonymize("+1-212-555-0198")).thenReturn(ANONYMIZED_PHONE);
    }

    @Test
    @DisplayName("Should anonymize all sensitive fields while leaving non-sensitive fields intact")
    void shouldAnonymizeCustomerUsingRegisteredStrategies() {
        // when
        Customer anonymized = anonymizationService.anonymize(plainCustomer);

        // then
        assertThat(anonymized).isNotNull();
        assertThat(anonymized.getName()).isEqualTo(ANONYMIZED_NAME);
        assertThat(anonymized.getEmail()).isEqualTo(ANONYMIZED_EMAIL);
        assertThat(anonymized.getPhone()).isEqualTo(ANONYMIZED_PHONE);

        // Non-sensitive fields must remain unchanged
        assertThat(anonymized.getBirthDate()).isEqualTo(plainCustomer.getBirthDate());

        // Verify interaction with all three strategies
        verify(nameStrategy,  times(1)).anonymize("John Doe");
        verify(emailStrategy, times(1)).anonymize("john.doe@opsforge.com");
        verify(phoneStrategy, times(1)).anonymize("+1-212-555-0198");
    }

    @Test
    @DisplayName("Should skip anonymization for null or empty values to avoid NPEs")
    void shouldSilentlySkipNullValues() {
        // given
        Customer partial = new Customer(
                "John Doe",
                /* email */ null,
                /* phone */ "",
                LocalDate.of(1990, 1, 1));

        // when
        Customer anonymized = anonymizationService.anonymize(partial);

        // then
        // Name is still anonymized
        assertThat(anonymized.getName()).isEqualTo(ANONYMIZED_NAME);

        // Null/empty fields are passed through as-is (i.e. still null / empty)
        assertThat(anonymized.getEmail()).isNull();
        assertThat(anonymized.getPhone()).isEmpty();

        // Verify strategies were *not* invoked for null or empty fields
        verify(emailStrategy, never()).anonymize(any());
        verify(phoneStrategy, never()).anonymize(any());
    }

    @Test
    @DisplayName("Should be idempotent—running anonymization twice has no additional effect")
    void shouldBeIdempotent() {
        // first pass
        Customer firstPass  = anonymizationService.anonymize(plainCustomer);
        // second pass
        Customer secondPass = anonymizationService.anonymize(firstPass);

        assertThat(secondPass).isEqualTo(firstPass);

        // Strategies are invoked only once per original value
        verify(nameStrategy,  times(1)).anonymize("John Doe");
        verify(emailStrategy, times(1)).anonymize("john.doe@opsforge.com");
        verify(phoneStrategy, times(1)).anonymize("+1-212-555-0198");
    }

    @Nested
    @DisplayName("Failure scenarios")
    class FailureScenarios {

        @Test
        @DisplayName("Should throw DomainException when no strategy is registered for a field")
        void shouldThrowWhenStrategyMissing() {
            // given – an unregistered field
            Customer custom = new Customer(
                    "John Doe",
                    "john.doe@opsforge.com",
                    "+1-212-555-0198",
                    LocalDate.of(1990, 1, 1));

            when(strategyRegistry.getStrategyForField(eq("name"))).thenReturn(null);

            // when / then
            assertThatThrownBy(() -> anonymizationService.anonymize(custom))
                    .isInstanceOf(DomainException.class)
                    .hasMessageContaining("No anonymization strategy registered for field: name");
        }

        @Test
        @DisplayName("Should wrap underlying strategy exceptions into DomainException")
        void shouldWrapStrategyFailures() {
            when(nameStrategy.anonymize(any()))
                    .thenThrow(new IllegalStateException("Something went sideways"));

            assertThatThrownBy(() -> anonymizationService.anonymize(plainCustomer))
                    .isInstanceOf(DomainException.class)
                    .hasRootCauseInstanceOf(IllegalStateException.class)
                    .hasMessageContaining("Failed to anonymize field: name");
        }
    }
}