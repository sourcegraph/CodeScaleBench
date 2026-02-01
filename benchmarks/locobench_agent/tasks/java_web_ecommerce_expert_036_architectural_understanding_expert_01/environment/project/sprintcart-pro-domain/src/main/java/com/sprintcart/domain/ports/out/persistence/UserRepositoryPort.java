package com.sprintcart.domain.ports.out.persistence;

import java.time.Instant;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.Optional;

import com.sprintcart.domain.model.user.User;
import com.sprintcart.domain.model.user.UserId;
import com.sprintcart.domain.shared.DomainEvent;
import com.sprintcart.domain.shared.exception.EntityNotFoundException;

/**
 * Outbound port that encapsulates all persistence concerns for the {@link User} aggregate.
 * <p>
 * Implementations reside in the infrastructure layer (JPA, Mongo, external REST, etc.),
 * while the domain layer depends exclusively on this contract.
 */
public interface UserRepositoryPort {

    /* =======================================================================
     * Basic lookup operations
     * ==================================================================== */

    /**
     * Finds a user by its technical identifier.
     *
     * @param id aggregate identifier
     * @return an {@link Optional} containing the user or empty if not found
     */
    Optional<User> findById(UserId id);

    /**
     * Variant of {@link #findById(UserId)} that fails fast when the user
     * does not exist.
     *
     * @throws EntityNotFoundException when no matching user is available
     */
    default User requireById(UserId id) {
        return findById(id)
                .orElseThrow(() -> new EntityNotFoundException(User.class, id));
    }

    /**
     * Finds a user by its e-mail.
     */
    Optional<User> findByEmail(String email);

    /**
     * Finds a user by its username.
     */
    Optional<User> findByUsername(String username);

    /**
     * Retrieves the user alongside the full authority model (roles + permissions).
     * Useful for authentication flows that need the entire security context
     * in a single trip to the persistence layer.
     */
    Optional<User> fetchWithAuthorities(UserId id);

    /* =======================================================================
     * Mutating operations
     * ==================================================================== */

    /**
     * Saves (inserts or updates) an aggregate. Implementations <b>must</b> enforce
     * optimistic locking to guarantee isolation in concurrent scenarios.
     */
    User save(User aggregateRoot);

    /**
     * Atomically saves a collection of users in the same transaction.
     */
    List<User> saveAll(List<User> users);

    /**
     * Deletes a user by identifier.
     */
    void delete(UserId id);

    /**
     * Deletes a user by instance. The default implementation delegates to
     * {@link #delete(UserId)} but can be overridden for performance gains.
     */
    default void delete(User user) {
        Objects.requireNonNull(user, "user must not be null");
        delete(user.getId());
    }

    /* =======================================================================
     * Existence checks – used to enforce unique constraints at the domain layer
     * ==================================================================== */

    boolean existsByEmail(String email);

    boolean existsByUsername(String username);

    /* =======================================================================
     * Advanced querying
     * ==================================================================== */

    /**
     * Returns users matching the supplied {@link Criteria} ordered/paginated by
     * the {@link PageRequest}.
     */
    List<User> search(Criteria criteria, PageRequest pageRequest);

    /**
     * Counts users that satisfy the given {@link Criteria}.
     */
    long count(Criteria criteria);

    /* =======================================================================
     * Domain event handling
     * ==================================================================== */

    /**
     * Publishes domain events raised by a mutated aggregate.
     * <p>
     * The default implementation is a no-op, allowing adapters to opt-in only
     * when an integration boundary (e.g., Kafka, RabbitMQ) is present.
     *
     * @param aggregateId id of the aggregate that sourced the events
     * @param events      immutable list of events recorded during the transaction
     */
    default void publishEvents(UserId aggregateId, List<DomainEvent> events) {
        // no-op
    }

    /* =======================================================================
     * Helper value objects (kept lightweight to avoid third-party dependencies)
     * ==================================================================== */

    /**
     * Immutable page request abstraction with offset-based paging semantics.
     */
    final class PageRequest {

        private final int page;
        private final int size;
        private final Sort sort;

        private PageRequest(int page, int size, Sort sort) {
            if (page < 0) {
                throw new IllegalArgumentException("page must be >= 0");
            }
            if (size <= 0) {
                throw new IllegalArgumentException("size must be > 0");
            }
            this.page = page;
            this.size = size;
            this.sort = sort == null ? Sort.unsorted() : sort;
        }

        public static PageRequest of(int page, int size) {
            return new PageRequest(page, size, Sort.unsorted());
        }

        public static PageRequest of(int page, int size, Sort sort) {
            return new PageRequest(page, size, sort);
        }

        public int getPage() {
            return page;
        }

        public int getSize() {
            return size;
        }

        public Sort getSort() {
            return sort;
        }
    }

    /**
     * Sorting abstraction inspired by Spring's Sort but without dependencies.
     */
    final class Sort {

        public enum Direction {ASC, DESC}

        private final List<Order> orders;

        private Sort(List<Order> orders) {
            this.orders = Collections.unmodifiableList(orders);
        }

        public static Sort by(Order... orders) {
            return new Sort(List.of(orders));
        }

        public static Sort by(String property) {
            return new Sort(List.of(new Order(Direction.ASC, property)));
        }

        public static Sort unsorted() {
            return new Sort(List.of());
        }

        public List<Order> getOrders() {
            return orders;
        }

        public boolean isSorted() {
            return !orders.isEmpty();
        }

        public record Order(Direction direction, String property) {
            public Order {
                if (property == null || property.isBlank()) {
                    throw new IllegalArgumentException("property must not be blank");
                }
            }
        }
    }

    /**
     * Search criteria value object implemented via the builder pattern to
     * accommodate future parameters without breaking existing code.
     */
    final class Criteria {

        private final String emailContains;
        private final String usernameContains;
        private final Boolean enabled;
        private final Instant createdAfter;
        private final Instant createdBefore;

        private Criteria(Builder builder) {
            this.emailContains    = builder.emailContains;
            this.usernameContains = builder.usernameContains;
            this.enabled          = builder.enabled;
            this.createdAfter     = builder.createdAfter;
            this.createdBefore    = builder.createdBefore;
        }

        public Optional<String> emailContains()     { return Optional.ofNullable(emailContains); }
        public Optional<String> usernameContains()  { return Optional.ofNullable(usernameContains); }
        public Optional<Boolean> enabled()          { return Optional.ofNullable(enabled); }
        public Optional<Instant> createdAfter()     { return Optional.ofNullable(createdAfter); }
        public Optional<Instant> createdBefore()    { return Optional.ofNullable(createdBefore); }

        /* ------------------------------------------------------------------ */
        /* Builder                                                            */
        /* ------------------------------------------------------------------ */
        public static Builder builder() {
            return new Builder();
        }

        public static final class Builder {

            private String emailContains;
            private String usernameContains;
            private Boolean enabled;
            private Instant createdAfter;
            private Instant createdBefore;

            private Builder() {}

            public Builder emailContains(String emailContains) {
                this.emailContains = emailContains;
                return this;
            }

            public Builder usernameContains(String usernameContains) {
                this.usernameContains = usernameContains;
                return this;
            }

            public Builder enabled(Boolean enabled) {
                this.enabled = enabled;
                return this;
            }

            public Builder createdAfter(Instant createdAfter) {
                this.createdAfter = createdAfter;
                return this;
            }

            public Builder createdBefore(Instant createdBefore) {
                this.createdBefore = createdBefore;
                return this;
            }

            public Criteria build() {
                return new Criteria(this);
            }
        }
    }
}