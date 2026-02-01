package com.sprintcart.domain.model.productivity;

import java.io.Serializable;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/**
 * Aggregate root representing a user–defined automation rule.
 * <p>
 * A rule encapsulates the following:
 * <ul>
 *     <li>A set of {@link Condition}s that must all evaluate to {@code true} in order to fire.</li>
 *     <li>A set of side–effect–free {@link Action}s that will be executed in the order in which
 *     they were registered.</li>
 *     <li>Lifecycle controls (activate, pause, archive) so operators can manage rules
 *     without physically deleting them, allowing for reliable audits and replayability.</li>
 * </ul>
 *
 * <p><strong>Domain Invariants</strong></p>
 * <ul>
 *     <li>At least one {@link Condition} and one {@link Action} have to be provided.</li>
 *     <li>The rule must be in {@link Status#ACTIVE} to execute its actions.</li>
 * </ul>
 *
 * <p>Because the domain layer must remain technology–agnostic, no scheduler, database or external
 * messaging code is referenced here. The infrastructure layer is responsible for persisting the
 * aggregate and triggering {@link #tryExecute(Map)} at the right moment.</p>
 */
public final class AutomationRule implements Serializable {

    private static final long serialVersionUID = 42424242424L;

    // -------------------- Value Objects --------------------
    private final RuleId id;
    private String name;
    private String description;
    private Status status;
    private final List<Condition> conditions;
    private final List<Action> actions;
    private final Instant createdAt;
    private Instant updatedAt;

    // -------------------- Ctor -----------------------------

    private AutomationRule(Builder builder) {
        this.id          = builder.id;
        this.name        = builder.name;
        this.description = builder.description;
        this.status      = builder.status;
        this.conditions  = Collections.unmodifiableList(new ArrayList<>(builder.conditions));
        this.actions     = Collections.unmodifiableList(new ArrayList<>(builder.actions));
        this.createdAt   = builder.createdAt;
        this.updatedAt   = builder.updatedAt;

        validateInvariants();
    }

    // -------------------- Domain behaviour ----------------

    /**
     * Evaluates the rule, and if all {@link Condition}s succeed while the rule is ACTIVE,
     * executes all configured {@link Action}s in a defensive try/catch block so that
     * one misbehaving action does not prevent subsequent actions from running.
     *
     * @param facts Arbitrary run–time data points (e.g., order info, stock levels, KPIs).
     * @return A list of {@link ActionResult}s—one for each executed action, empty if the
     *         rule did not fire.
     */
    public List<ActionResult> tryExecute(final Map<String, Object> facts) {
        Objects.requireNonNull(facts, "facts map must not be null");

        if (status != Status.ACTIVE) {
            return Collections.emptyList();
        }

        for (Condition condition : conditions) {
            if (!condition.test(facts)) {
                return Collections.emptyList();
            }
        }

        List<ActionResult> results = new ArrayList<>(actions.size());
        for (Action action : actions) {
            try {
                results.add(action.execute(facts));
            } catch (Exception ex) {
                // encapsulate the exception so callers receive a complete picture of what happened
                results.add(ActionResult.failure(action, ex));
            }
        }
        return results;
    }

    // -------------------- Lifecycle operations ------------

    public void pause() {
        if (status == Status.ARCHIVED) {
            throw new IllegalStateException("Archived rule cannot be paused.");
        }
        if (status != Status.PAUSED) {
            this.status = Status.PAUSED;
            touch();
        }
    }

    public void activate() {
        if (status == Status.ARCHIVED) {
            throw new IllegalStateException("Archived rule cannot be activated.");
        }
        if (status != Status.ACTIVE) {
            this.status = Status.ACTIVE;
            touch();
        }
    }

    public void archive() {
        if (status != Status.ARCHIVED) {
            this.status = Status.ARCHIVED;
            touch();
        }
    }

    public void rename(String newName) {
        this.name = requireNonEmpty(newName, "newName");
        touch();
    }

    public void updateDescription(String newDescription) {
        this.description = requireNonEmpty(newDescription, "newDescription");
        touch();
    }

    // -------------------- Getters -------------------------

    public RuleId getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public String getDescription() {
        return description;
    }

    public Status getStatus() {
        return status;
    }

    public List<Condition> getConditions() {
        return conditions;
    }

    public List<Action> getActions() {
        return actions;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    // -------------------- Helpers -------------------------

    private void validateInvariants() {
        requireNonEmpty(name, "name");
        requireNonEmpty(description, "description");

        if (conditions.isEmpty()) {
            throw new IllegalStateException("At least one condition must be specified.");
        }
        if (actions.isEmpty()) {
            throw new IllegalStateException("At least one action must be specified.");
        }
    }

    private void touch() {
        this.updatedAt = Instant.now();
    }

    private static String requireNonEmpty(String value, String label) {
        if (value == null || value.trim().isEmpty()) {
            throw new IllegalArgumentException(label + " must not be empty");
        }
        return value;
    }

    // -------------------- Inner types ---------------------

    /**
     * Unique identifier for a rule—a thin, type–safe wrapper around {@link UUID}.
     */
    public record RuleId(UUID value) implements Serializable {

        public RuleId {
            Objects.requireNonNull(value, "value must not be null");
        }

        public static RuleId newId() {
            return new RuleId(UUID.randomUUID());
        }

        @Override
        public String toString() {
            return value.toString();
        }
    }

    /**
     * Current lifecycle stage of a rule.
     */
    public enum Status {
        ACTIVE,
        PAUSED,
        ARCHIVED
    }

    /**
     * Functional interface for a boolean predicate that decides whether the rule
     * should fire given a dynamic set of facts.
     */
    @FunctionalInterface
    public interface Condition extends Serializable {

        /**
         * Evaluates the predicate.
         *
         * @param facts Immutable map of real–time inputs.
         * @return {@code true} if the rule should continue firing.
         */
        boolean test(Map<String, Object> facts);
    }

    /**
     * An idempotent unit of work to be executed when all {@link Condition}s pass.
     * <p>
     * Implementations must be side–effect–free within the domain layer. Effects
     * such as sending emails or pushing messages are to be handled by
     * infrastructure classes that implement the port this action represents.
     */
    public interface Action extends Serializable {

        /**
         * Executes the action.
         *
         * @param facts Same facts that were used to evaluate the rule.
         * @return A domain–specific result allowing callers to analyse execution outcome.
         * @throws Exception Any runtime exception will be caught and wrapped by the caller.
         */
        ActionResult execute(Map<String, Object> facts) throws Exception;
    }

    /**
     * Value Object describing the outcome of one {@link Action} execution.
     * It ships with factory helpers for success/failure creation.
     */
    public record ActionResult(Action source, boolean success, String message, Throwable error)
            implements Serializable {

        public static ActionResult success(Action source, String message) {
            return new ActionResult(source, true, message, null);
        }

        public static ActionResult failure(Action source, Throwable error) {
            Objects.requireNonNull(error, "error must not be null");
            return new ActionResult(source, false, error.getMessage(), error);
        }
    }

    // -------------------- Builder -------------------------

    public static class Builder {

        private RuleId id             = RuleId.newId();
        private String name           = "";
        private String description    = "";
        private Status status         = Status.ACTIVE;
        private List<Condition> conditions = new ArrayList<>();
        private List<Action> actions      = new ArrayList<>();
        private Instant createdAt    = Instant.now();
        private Instant updatedAt    = createdAt;

        public Builder id(RuleId id) {
            this.id = Objects.requireNonNull(id, "id must not be null");
            return this;
        }

        public Builder name(String name) {
            this.name = requireNonEmpty(name, "name");
            return this;
        }

        public Builder description(String description) {
            this.description = requireNonEmpty(description, "description");
            return this;
        }

        public Builder status(Status status) {
            this.status = Objects.requireNonNull(status, "status must not be null");
            return this;
        }

        public Builder addCondition(Condition condition) {
            this.conditions.add(Objects.requireNonNull(condition, "condition must not be null"));
            return this;
        }

        public Builder addAction(Action action) {
            this.actions.add(Objects.requireNonNull(action, "action must not be null"));
            return this;
        }

        public AutomationRule build() {
            return new AutomationRule(this);
        }
    }

    // -------------------- equals/hashCode -----------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof AutomationRule that)) return false;
        return id.equals(that.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }
}