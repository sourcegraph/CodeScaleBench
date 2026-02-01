package com.sprintcart.domain.model.productivity;

import java.io.Serializable;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.Collections;
import java.util.Deque;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * Represents a key performance indicator (KPI) that measures how efficiently
 * an operator or a workflow step performs within SprintCart Pro.
 *
 * Being a domain entity, this class is free from persistence- or framework–
 * specific annotations.  Infrastructure layers (e.g. JPA, MongoDB) provide
 * mappings externally via {@code *EntityMapper} components.
 *
 * Thread safety: not inherently thread-safe.  Aggregate instances should be
 * scoped to a single application service boundary.
 */
public final class ProductivityMetric implements Serializable {

    private static final long serialVersionUID = 3616294717454473589L;

    /**
     * Maximum number of historical observations retained in-memory.
     * Older values are still persisted by the repository but are pruned
     * from the aggregate to keep memory footprint predictable.
     */
    private static final int DEFAULT_BUFFER_CAPACITY = 250;

    // --------------------------------------------------------------------- //
    // Fields
    // --------------------------------------------------------------------- //

    private final MetricId id;
    private final String code;
    private final String displayName;
    private final String description;
    private final Unit unit;

    /**
     * Desired target value.  May be {@code null} when the metric does not
     * prescribe a goal (e.g., merely informational).
     */
    private final BigDecimal target;

    /**
     * Circular buffer of most recent observations (bounded).
     */
    private final Deque<Observation> observations;

    /**
     * Domain timestamps (captured in UTC).
     */
    private final Instant createdAt;
    private Instant lastModifiedAt;

    // --------------------------------------------------------------------- //
    // Constructors / Factory methods
    // --------------------------------------------------------------------- //

    private ProductivityMetric(Builder builder) {
        this.id           = builder.id;
        this.code         = builder.code;
        this.displayName  = builder.displayName;
        this.description  = builder.description;
        this.unit         = builder.unit;
        this.target       = builder.target;
        this.createdAt    = builder.createdAt;
        this.lastModifiedAt = builder.createdAt;
        this.observations = new ArrayDeque<>(DEFAULT_BUFFER_CAPACITY);
    }

    public static Builder builder() {
        return new Builder();
    }

    // --------------------------------------------------------------------- //
    // Business behaviour
    // --------------------------------------------------------------------- //

    /**
     * Records a new observation and returns the calculated status against the
     * current target (if any).
     *
     * @param value       measured value; must be non-null and non-negative
     * @param occurredAt  timestamp of the observation (UTC)
     *
     * @return {@link StatusReport} snapshot at this point in time
     *
     * @throws DomainException if validation fails
     */
    public synchronized StatusReport record(BigDecimal value, Instant occurredAt)
            throws DomainException {

        Objects.requireNonNull(value, "value must not be null");
        Objects.requireNonNull(occurredAt, "occurredAt must not be null");
        if (value.signum() < 0) {
            throw new DomainException("Metric value cannot be negative: " + value);
        }

        // Trim buffer when needed (simple ring behaviour)
        if (observations.size() >= DEFAULT_BUFFER_CAPACITY) {
            observations.removeFirst();
        }
        observations.addLast(new Observation(value, occurredAt));
        lastModifiedAt = Clock.systemUTC().instant();

        return evaluateCurrentStatus();
    }

    /**
     * Returns an immutable snapshot of the most recent observations.
     */
    public Deque<Observation> recentObservations() {
        return Collections.unmodifiableDeque(observations);
    }

    /**
     * Calculates a rolling average over the provided window.  Observations
     * outside of the time window are ignored.
     *
     * @param window rolling time range (e.g. the last 1 hour)
     * @param now    current reference time (UTC); usually {@code Clock.systemUTC().instant()}
     *
     * @return average value (scale 2) or {@code Optional.empty()} when there
     *         are no observations within the given window
     */
    public Optional<BigDecimal> rollingAverage(Duration window, Instant now) {
        Objects.requireNonNull(window, "window must not be null");
        Objects.requireNonNull(now, "now must not be null");

        if (window.isNegative() || window.isZero()) {
            throw new IllegalArgumentException("Window must be positive");
        }

        Instant threshold = now.minus(window);

        BigDecimal sum   = BigDecimal.ZERO;
        int        count = 0;
        for (Observation obs : observations) {
            if (!obs.occurredAt.isBefore(threshold)) {
                sum = sum.add(obs.value);
                count++;
            }
        }

        if (count == 0) {
            return Optional.empty();
        }
        return Optional.of(sum.divide(BigDecimal.valueOf(count), 2, RoundingMode.HALF_UP));
    }

    /**
     * Indicates whether the most recent value meets or exceeds the configured
     * target (when a target is set).
     */
    public boolean isOnTarget() {
        if (target == null) {
            return true; // implicitly on-target
        }
        return latestValue()
                .map(v -> v.compareTo(target) >= 0)
                .orElse(false);
    }

    // --------------------------------------------------------------------- //
    // Getters (no setters to maintain integrity)
    // --------------------------------------------------------------------- //

    public MetricId id()         { return id; }
    public String   code()       { return code; }
    public String   displayName(){ return displayName; }
    public String   description(){ return description; }
    public Unit     unit()       { return unit; }
    public BigDecimal target()   { return target; }
    public Instant  createdAt()  { return createdAt; }
    public Instant  lastModifiedAt() { return lastModifiedAt; }

    // --------------------------------------------------------------------- //
    // Internal helpers
    // --------------------------------------------------------------------- //

    private StatusReport evaluateCurrentStatus() {
        Performance performance = Performance.NO_TARGET;

        if (target != null) {
            Optional<BigDecimal> latest = latestValue();
            if (latest.isPresent()) {
                int cmp = latest.get().compareTo(target);
                if (cmp >= 0) {
                    performance = Performance.ON_TRACK;
                } else if (cmp >= -1) { // within 1 unit below target
                    performance = Performance.AT_RISK;
                } else {
                    performance = Performance.OFF_TRACK;
                }
            }
        }

        return new StatusReport(this.id, performance, lastModifiedAt);
    }

    private Optional<BigDecimal> latestValue() {
        Observation obs = observations.peekLast();
        return obs == null ? Optional.empty() : Optional.of(obs.value);
    }

    // --------------------------------------------------------------------- //
    // Nested types
    // --------------------------------------------------------------------- //

    /**
     * Aggregate identifier value object.
     */
    public record MetricId(UUID value) implements Serializable {

        public MetricId {
            Objects.requireNonNull(value, "MetricId value must not be null");
        }

        public static MetricId random() {
            return new MetricId(UUID.randomUUID());
        }
    }

    /**
     * Immutable observation tuple.
     */
    public record Observation(BigDecimal value, Instant occurredAt) implements Serializable {
        public Observation {
            Objects.requireNonNull(value, "value must not be null");
            Objects.requireNonNull(occurredAt, "occurredAt must not be null");
        }
    }

    /**
     * Unit of measurement for a metric.
     */
    public enum Unit {
        ITEMS,
        SECONDS,
        PERCENTAGE,
        CURRENCY,
        OPERATIONS
    }

    /**
     * High-level performance bucket relative to the target.
     */
    public enum Performance {
        ON_TRACK,
        AT_RISK,
        OFF_TRACK,
        NO_TARGET
    }

    /**
     * Lightweight DTO returned when the application service records an
     * observation.
     *
     * Note: This object is *not* exposed externally; adapters map it to
     * REST/GraphQL payloads as needed.
     */
    public record StatusReport(
            MetricId metricId,
            Performance performance,
            Instant generatedAt
    ) implements Serializable { }

    /**
     * Domain-layer exception for guard clauses and invariants.
     */
    public static class DomainException extends RuntimeException {
        private static final long serialVersionUID = -65774494630225596L;

        public DomainException(String message) {
            super(message);
        }
    }

    // --------------------------------------------------------------------- //
    // Builder
    // --------------------------------------------------------------------- //

    public static final class Builder {

        private MetricId   id          = MetricId.random();
        private String     code;
        private String     displayName;
        private String     description;
        private Unit       unit        = Unit.OPERATIONS;
        private BigDecimal target;
        private Instant    createdAt   = Clock.systemUTC().instant();

        private Builder() {}

        public Builder id(MetricId id) {
            this.id = Objects.requireNonNull(id);
            return this;
        }

        /**
         * Logical slug used to uniquely reference the metric (e.g.,
         * {@code ITEMS_PICKED_PER_HOUR}).  Must be upper-snake-case.
         */
        public Builder code(String code) {
            this.code = Objects.requireNonNull(code).trim();
            return this;
        }

        public Builder displayName(String displayName) {
            this.displayName = Objects.requireNonNull(displayName).trim();
            return this;
        }

        public Builder description(String description) {
            this.description = Objects.requireNonNull(description).trim();
            return this;
        }

        public Builder unit(Unit unit) {
            this.unit = Objects.requireNonNull(unit);
            return this;
        }

        public Builder target(BigDecimal target) {
            if (target != null && target.signum() < 0) {
                throw new IllegalArgumentException("Target cannot be negative");
            }
            this.target = target;
            return this;
        }

        public Builder createdAt(Instant createdAt) {
            this.createdAt = Objects.requireNonNull(createdAt);
            return this;
        }

        public ProductivityMetric build() {

            // Minimal invariants
            if (code == null || code.isBlank()) {
                throw new IllegalStateException("code is required");
            }
            if (displayName == null || displayName.isBlank()) {
                throw new IllegalStateException("displayName is required");
            }

            return new ProductivityMetric(this);
        }
    }

    // --------------------------------------------------------------------- //
    // Equality / HashCode / ToString
    // --------------------------------------------------------------------- //

    @Override
    public boolean equals(Object obj) {
        if (this == obj) return true;
        if (!(obj instanceof ProductivityMetric other)) return false;
        return id.equals(other.id);
    }

    @Override
    public int hashCode() {
        // Aggregate identity equality based on id only
        return Objects.hash(id);
    }

    @Override
    public String toString() {
        return "ProductivityMetric[" + "id=" + id + ", code=" + code + ']';
    }
}