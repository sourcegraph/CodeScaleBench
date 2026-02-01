package com.sprintcart.domain.model.productivity;

import java.io.Serial;
import java.io.Serializable;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDateTime;
import java.util.Collections;
import java.util.EnumMap;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * Trigger is a domain construct that represents the “WHEN” portion of an automation rule
 * (e.g., “when stock &lt; X”, “when order paid”, “every Monday 08:00”).
 *
 * Triggers are immutable value objects that can be attached to an Automation
 * aggregate.  They expose an evaluator that answers the question
 * “should I fire for the given context right now?” while keeping all side-effects
 * outside the domain model.
 *
 * Note: this class is free of any persistence annotations because the SprintCart
 * core follows a strict Hexagonal Architecture where the domain layer is pure Java.
 */
public final class Trigger implements Serializable {

    @Serial
    private static final long serialVersionUID = 3907654309189309284L;

    /**
     * Stable, unique identifier so that triggers can be referenced from outside
     * the aggregate (e.g., for audit logs).
     */
    private final UUID id;

    /**
     * Human-readable name displayed in the Automation Studio UI.
     */
    private final String name;

    /**
     * Optional description giving operators more context.
     */
    private final String description;

    /**
     * The type determines how the trigger will be evaluated at runtime.
     */
    private final Type type;

    /**
     * Type-specific configuration details.  Keys are normalized to lower-case.
     * Example for STOCK_LEVEL:
     *   "sku"         -> "CAP-X-RED-M"
     *   "threshold"   -> "5"
     * Example for SCHEDULED:
     *   "cron"        -> "0 0/30 * * * ?"
     */
    private final Map<String, String> parameters;

    /**
     * Whether the trigger is currently active.
     */
    private final boolean enabled;

    /**
     * Optimistic-locking value.  Not managed by domain logic but
     * provided so that adapters can map it to the persistence layer
     * (e.g., JPA @Version) without polluting the core model.
     */
    private final long version;

    private Trigger(Builder builder) {
        this.id          = builder.id;
        this.name        = builder.name;
        this.description = builder.description;
        this.type        = builder.type;
        this.parameters  = Collections.unmodifiableMap(builder.parameters);
        this.enabled     = builder.enabled;
        this.version     = builder.version;
        validate();
    }

    /* Validation logic follows the “fail fast” principle so that invalid triggers
       never enter the system. */
    private void validate() {
        if (Objects.isNull(id)) {
            throw new IllegalStateException("id must not be null");
        }
        if (Objects.isNull(name) || name.isBlank()) {
            throw new IllegalStateException("name must be provided");
        }
        if (Objects.isNull(type)) {
            throw new IllegalStateException("type must be specified");
        }
        switch (type) {
            case STOCK_LEVEL -> ensureParams("sku", "threshold");
            case ORDER_PLACED -> ensureParams("paymentStatus");
            case SCHEDULED -> ensureParams("cron");
        }
    }

    private void ensureParams(String... keys) {
        for (String key : keys) {
            if (!parameters.containsKey(key)) {
                throw new IllegalStateException(
                        "missing required parameter '%s' for trigger type %s".formatted(key, type));
            }
        }
    }

    /**
     * Evaluates whether this trigger should fire, based on the supplied context.
     *
     * This method performs pure calculations only.  No IO, no state mutations.
     *
     * @param ctx   event context information
     * @param clock clock to use for time-based evaluation (injected to keep things testable)
     * @return true if the trigger’s condition is satisfied and {@link #isEnabled()} is true
     */
    public boolean shouldFire(TriggerContext ctx, Clock clock) {
        if (!enabled) {
            return false;
        }

        return switch (type) {
            case STOCK_LEVEL  -> evalStockLevel(ctx);
            case ORDER_PLACED -> evalOrderPlaced(ctx);
            case SCHEDULED    -> evalScheduled(clock);
        };
    }

    private boolean evalStockLevel(TriggerContext ctx) {
        InventorySnapshot inventory = ctx.inventory()
                                          .orElseThrow(() -> new IllegalArgumentException(
                                                  "InventorySnapshot required for STOCK_LEVEL evaluation"));

        String sku       = parameters.get("sku");
        int threshold    = Integer.parseInt(parameters.get("threshold"));
        int currentStock = inventory.stockForSku(sku);

        return currentStock < threshold;
    }

    private boolean evalOrderPlaced(TriggerContext ctx) {
        OrderEvent event = ctx.orderEvent()
                              .orElseThrow(() -> new IllegalArgumentException(
                                      "OrderEvent required for ORDER_PLACED evaluation"));

        String expectedPaymentStatus = parameters.get("paymentStatus");
        return event.paymentStatus().equalsIgnoreCase(expectedPaymentStatus);
    }

    private boolean evalScheduled(Clock clock) {
        String cronExpression = parameters.get("cron");
        CronSchedule schedule = CronSchedule.parse(cronExpression);

        LocalDateTime now = LocalDateTime.ofInstant(Instant.now(clock), schedule.zoneId());
        return schedule.matches(now);
    }

    // -----------------------------------------------------------------------
    // Domain behaviour
    // -----------------------------------------------------------------------

    public Trigger disable() {
        return toBuilder().enabled(false).build();
    }

    public Trigger enable() {
        return toBuilder().enabled(true).build();
    }

    // -----------------------------------------------------------------------
    // Getters (no setters to preserve immutability)
    // -----------------------------------------------------------------------

    public UUID getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public Optional<String> getDescription() {
        return Optional.ofNullable(description);
    }

    public Type getType() {
        return type;
    }

    public Map<String, String> getParameters() {
        return parameters;
    }

    public boolean isEnabled() {
        return enabled;
    }

    public long getVersion() {
        return version;
    }

    public Builder toBuilder() {
        return new Builder(this);
    }

    // -----------------------------------------------------------------------
    // Builders & Enums
    // -----------------------------------------------------------------------

    public static Builder builder(Type type) {
        return new Builder(type);
    }

    public static final class Builder {
        private final Type type;
        private UUID id = UUID.randomUUID();
        private String name;
        private String description;
        private final Map<String, String> parameters = new EnumMap<>(String.class);
        private boolean enabled = true;
        private long version = 0L;

        private Builder(Type type) {
            this.type = Objects.requireNonNull(type);
        }

        private Builder(Trigger prototype) {
            this.type        = prototype.type;
            this.id          = prototype.id;
            this.name        = prototype.name;
            this.description = prototype.description;
            this.parameters.putAll(prototype.parameters);
            this.enabled     = prototype.enabled;
            this.version     = prototype.version;
        }

        public Builder id(UUID id) {
            this.id = Objects.requireNonNull(id);
            return this;
        }

        public Builder name(String name) {
            this.name = Objects.requireNonNull(name).trim();
            return this;
        }

        public Builder description(String description) {
            this.description = (description == null || description.isBlank()) ? null : description.trim();
            return this;
        }

        public Builder parameter(String key, String value) {
            Objects.requireNonNull(key);
            Objects.requireNonNull(value);
            parameters.put(key.toLowerCase(), value.trim());
            return this;
        }

        public Builder enabled(boolean enabled) {
            this.enabled = enabled;
            return this;
        }

        public Builder version(long version) {
            if (version < 0) {
                throw new IllegalArgumentException("version must not be negative");
            }
            this.version = version;
            return this;
        }

        public Trigger build() {
            return new Trigger(this);
        }
    }

    /**
     * Enumeration of first-class trigger types the domain understands.
     * Additional types should be added via refactoring rather than creating
     * “custom” types on the fly—keeping the vocabulary small is deliberate
     * to avoid “stringly-typed” business rules.
     */
    public enum Type {
        /**
         * Fires when inventory level for a given SKU drops below a threshold.
         */
        STOCK_LEVEL,

        /**
         * Fires when an order is placed with the specified payment status
         * (e.g., “PAID”, “PENDING”).
         */
        ORDER_PLACED,

        /**
         * Fires on a recurring schedule defined by a cron expression.
         */
        SCHEDULED
    }

    // -----------------------------------------------------------------------
    // Context objects — simplified representations so that Trigger remains
    // independent of heavy domain aggregates not required for evaluation
    // -----------------------------------------------------------------------

    /**
     * Immutable bag of data supplied to {@link #shouldFire(TriggerContext, Clock)}.
     * Each trigger picks the subset it needs.
     */
    public record TriggerContext(Optional<InventorySnapshot> inventory,
                                 Optional<OrderEvent> orderEvent) {

        public static TriggerContext empty() {
            return new TriggerContext(Optional.empty(), Optional.empty());
        }

        public static TriggerContext ofInventory(InventorySnapshot snapshot) {
            return new TriggerContext(Optional.of(snapshot), Optional.empty());
        }

        public static TriggerContext ofOrderEvent(OrderEvent orderEvent) {
            return new TriggerContext(Optional.empty(), Optional.of(orderEvent));
        }
    }

    /**
     * Lightweight stock representation used for trigger evaluation.
     */
    public interface InventorySnapshot {
        int stockForSku(String sku);
    }

    /**
     * Lightweight order event representation used for trigger evaluation.
     */
    public interface OrderEvent {
        String paymentStatus();
    }

    // -----------------------------------------------------------------------
    // CronSchedule — minimal wrapper around cron-pattern matching. We purposefully
    // keep the implementation lightweight.  In production you might delegate to
    // a mature library (e.g., cron-utils) but we avoid external dependencies here.
    // -----------------------------------------------------------------------

    private static final class CronSchedule {
        private final String original;
        private final java.time.ZoneId zoneId;

        private CronSchedule(String original, java.time.ZoneId zoneId) {
            this.original = original;
            this.zoneId   = zoneId;
        }

        static CronSchedule parse(String expression) {
            // Very naive validation; replace with real parsing if needed.
            if (expression.chars().filter(ch -> ch == ' ').count() < 5) {
                throw new IllegalArgumentException("Invalid cron expression: " + expression);
            }
            return new CronSchedule(expression, java.time.ZoneId.systemDefault());
        }

        boolean matches(LocalDateTime dateTime) {
            // Placeholder logic.  A real implementation would evaluate the cron expression.
            // For deterministic behaviour in unit tests we simply return true once per minute.
            return dateTime.getSecond() == 0;
        }

        java.time.ZoneId zoneId() {
            return zoneId;
        }

        @Override
        public String toString() {
            return original;
        }
    }

    // -----------------------------------------------------------------------
    // Equals/HashCode/ToString (based on immutable fields)
    // -----------------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Trigger trigger)) return false;
        return id.equals(trigger.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    @Override
    public String toString() {
        return "Trigger[id=%s, name=%s, type=%s, enabled=%s]".formatted(id, name, type, enabled);
    }
}