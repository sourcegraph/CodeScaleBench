package com.sprintcart.domain.ports.out.persistence;

import com.sprintcart.domain.model.automation.AutomationEventType;
import com.sprintcart.domain.model.automation.AutomationRule;
import com.sprintcart.domain.model.automation.AutomationRuleId;
import com.sprintcart.domain.model.automation.RuleStatus;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * Outbound persistence port for {@link AutomationRule} aggregates.
 * <p>
 * This interface belongs to the domain layer and must not depend on any infrastructure‐specific
 * classes (JPA, JDBC, Mongo, etc.).  Implementations live in the infrastructure layer and are
 * injected into use-case services through dependency inversion.
 */
public interface AutomationRuleRepositoryPort {

    /**
     * Persists a new or existing {@link AutomationRule}.
     *
     * @param rule the rule instance to save.
     * @return the managed rule, potentially carrying generated identifiers or version metadata.
     * @throws AutomationRulePersistenceException if the operation cannot be completed.
     */
    AutomationRule save(AutomationRule rule);

    /**
     * Looks up a rule by its identity.
     *
     * @param id the business identifier.
     * @return the rule wrapped in an {@link Optional}, or empty if not found.
     */
    Optional<AutomationRule> findById(AutomationRuleId id);

    /**
     * Deletes a rule by its identifier.
     *
     * @param id rule identifier.
     * @throws AutomationRulePersistenceException if the rule cannot be removed.
     */
    void deleteById(AutomationRuleId id);

    /**
     * Retrieves all rules that match the given lifecycle status.
     *
     * @param status rule status (e.g., ACTIVE, DISABLED, DRAFT).
     * @return list that may be empty but never {@code null}.
     */
    List<AutomationRule> findAllByStatus(RuleStatus status);

    /**
     * Finds rules that are triggered by the specified domain event.
     *
     * @param eventType the event type (e.g., STOCK_LOW, ORDER_PLACED).
     * @return ordered list of matching rules.
     */
    List<AutomationRule> findRulesTriggeredBy(AutomationEventType eventType);

    /**
     * Returns rules that will expire at or before the supplied threshold.
     *
     * @param threshold inclusive upper bound timestamp.
     * @return list of rules that need to be deactivated by a scheduler.
     */
    List<AutomationRule> findRulesExpiringBefore(Instant threshold);

    /**
     * Executes a flexible, paginated search.
     *
     * @param criteria the criteria instance.
     * @param page     paging information.
     * @return a paged result object.
     */
    PagedResult<AutomationRule> search(AutomationRuleSearchCriteria criteria, PageRequest page);

    /* -----------------------------------------------------------------------
     * Helper types – defined here so that the domain does not depend on any
     * particular pagination or criteria query library.
     * -------------------------------------------------------------------- */

    /**
     * Immutable pagination request.
     *
     * @param page zero-based page index.
     * @param size requested page size (1 – 1 000).
     */
    record PageRequest(int page, int size) {

        public PageRequest {
            if (page < 0) {
                throw new IllegalArgumentException("page must be ≥ 0");
            }
            if (size <= 0 || size > 1_000) {
                throw new IllegalArgumentException("size must be between 1 and 1 000");
            }
        }

        public int offset() {
            return page * size;
        }
    }

    /**
     * Generic paged result.
     *
     * @param content       current page content.
     * @param totalElements total number of elements across all pages.
     * @param page          current page index.
     * @param size          page size.
     */
    record PagedResult<T>(List<T> content, long totalElements, int page, int size) {

        public long totalPages() {
            return (totalElements + size - 1) / size;
        }

        public boolean isLast() {
            return page >= totalPages() - 1;
        }
    }

    /**
     * Criteria object used to construct complex queries without coupling to a
     * specific persistence technology.
     */
    final class AutomationRuleSearchCriteria {

        private AutomationEventType eventType;
        private RuleStatus status;
        private String createdBy;
        private Instant createdAfter;
        private Instant createdBefore;

        private AutomationRuleSearchCriteria() {
        }

        public Optional<AutomationEventType> eventType() {
            return Optional.ofNullable(eventType);
        }

        public Optional<RuleStatus> status() {
            return Optional.ofNullable(status);
        }

        public Optional<String> createdBy() {
            return Optional.ofNullable(createdBy);
        }

        public Optional<Instant> createdAfter() {
            return Optional.ofNullable(createdAfter);
        }

        public Optional<Instant> createdBefore() {
            return Optional.ofNullable(createdBefore);
        }

        /* ------------------------------------------------------------ */
        /* Builder                                                       */
        /* ------------------------------------------------------------ */

        public static Builder builder() {
            return new Builder();
        }

        public static final class Builder {

            private final AutomationRuleSearchCriteria instance = new AutomationRuleSearchCriteria();

            public Builder withEventType(AutomationEventType eventType) {
                instance.eventType = eventType;
                return this;
            }

            public Builder withStatus(RuleStatus status) {
                instance.status = status;
                return this;
            }

            public Builder withCreatedBy(String createdBy) {
                instance.createdBy = createdBy;
                return this;
            }

            public Builder createdAfter(Instant createdAfter) {
                instance.createdAfter = createdAfter;
                return this;
            }

            public Builder createdBefore(Instant createdBefore) {
                instance.createdBefore = createdBefore;
                return this;
            }

            public AutomationRuleSearchCriteria build() {
                return instance;
            }
        }
    }

    /**
     * Runtime exception to signal persistence-layer problems without exposing
     * underlying infrastructure details to the domain.
     */
    class AutomationRulePersistenceException extends RuntimeException {
        public AutomationRulePersistenceException(String message) {
            super(message);
        }

        public AutomationRulePersistenceException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}