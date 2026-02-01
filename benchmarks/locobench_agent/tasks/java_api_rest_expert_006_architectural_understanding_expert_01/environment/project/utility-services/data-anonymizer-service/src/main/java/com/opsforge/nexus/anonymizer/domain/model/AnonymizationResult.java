package com.opsforge.nexus.anonymizer.domain.model;

import java.io.Serial;
import java.io.Serializable;
import java.time.Instant;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

/**
 * Immutable value-object that captures the outcome of anonymizing a single datum.
 * <p>
 * This class intentionally lives in the <em>domain</em> package so that core business
 * logic cannot depend on any specific transport technology.  For example, an
 * {@code AnonymizationResult} can be produced by an HTTP controller, a GraphQL resolver,
 * or a batch job without modification.
 * <p>
 * The object supports two distinct states—{@code SUCCESS} and {@code FAILURE}.
 * Use the static factory methods {@link #success(String, Object, Object, List, Map)}
 * and {@link #failure(String, Object, String, Map)} to create instances.
 */
public final class AnonymizationResult implements Serializable {

    @Serial
    private static final long serialVersionUID = 1L;

    /**
     * Identifies the specific field / JSON path / column name whose value was processed.
     */
    private final String target;

    /**
     * The value before anonymization was attempted.
     * <p>
     * Stored as {@code Object} so that callers are free to use
     * primitives, collections, or complex types.
     */
    private final Object originalValue;

    /**
     * The value after anonymization completed.  This will be {@code null} when
     * {@link #status} is {@link Status#FAILURE}.
     */
    private final Object anonymizedValue;

    /**
     * Outcome of the anonymization attempt.
     */
    private final Status status;

    /**
     * Ordered list of strategy identifiers that were applied
     * (e.g., "masking", "tokenization", "blurring").
     * <p>
     * For failures, this list is empty.
     */
    private final List<String> appliedStrategies;

    /**
     * Human-readable reason in case of failure; <em>empty</em> for successes.
     */
    private final String errorMessage;

    /**
     * Implementation-agnostic metadata such as rule versions, processor IDs, execution
     * environment, etc.
     */
    private final Map<String, String> metadata;

    /**
     * Time at which the anonymization took place.
     */
    private final Instant timestamp;

    // --------------------------------------------------------------------- //
    //  Constructors                                                         //
    // --------------------------------------------------------------------- //

    private AnonymizationResult(Builder builder) {
        this.target = builder.target;
        this.originalValue = builder.originalValue;
        this.anonymizedValue = builder.anonymizedValue;
        this.status = builder.status;
        this.appliedStrategies = builder.appliedStrategies == null
                                 ? List.of()
                                 : List.copyOf(builder.appliedStrategies);
        this.errorMessage = builder.errorMessage;
        this.metadata = builder.metadata == null
                        ? Map.of()
                        : Map.copyOf(builder.metadata);
        this.timestamp = builder.timestamp == null ? Instant.now() : builder.timestamp;
    }

    // --------------------------------------------------------------------- //
    //  Static factory methods                                               //
    // --------------------------------------------------------------------- //

    /**
     * Creates a successful {@code AnonymizationResult}.
     */
    public static AnonymizationResult success(
            String target,
            Object originalValue,
            Object anonymizedValue,
            List<String> appliedStrategies,
            Map<String, String> metadata
    ) {
        Objects.requireNonNull(anonymizedValue, "anonymizedValue must not be null");
        return new Builder(Status.SUCCESS)
                .target(target)
                .originalValue(originalValue)
                .anonymizedValue(anonymizedValue)
                .appliedStrategies(
                        appliedStrategies == null ? List.of() : List.copyOf(appliedStrategies))
                .metadata(metadata == null ? Map.of() : Map.copyOf(metadata))
                .build();
    }

    /**
     * Creates a failed {@code AnonymizationResult}.
     */
    public static AnonymizationResult failure(
            String target,
            Object originalValue,
            String errorMessage,
            Map<String, String> metadata
    ) {
        Objects.requireNonNull(errorMessage, "errorMessage must not be null");
        return new Builder(Status.FAILURE)
                .target(target)
                .originalValue(originalValue)
                .errorMessage(errorMessage)
                .metadata(metadata == null ? Map.of() : Map.copyOf(metadata))
                .build();
    }

    // --------------------------------------------------------------------- //
    //  Business helpers                                                     //
    // --------------------------------------------------------------------- //

    /**
     * Semantic sugar for {@code getStatus() == Status.SUCCESS}.
     */
    public boolean isSuccess() {
        return status == Status.SUCCESS;
    }

    /**
     * Returns {@code true} when {@link #originalValue} and {@link #anonymizedValue}
     * differ in {@code #success} results.
     */
    public boolean isModified() {
        if (!isSuccess()) {
            return false;
        }
        return !Objects.equals(originalValue, anonymizedValue);
    }

    // --------------------------------------------------------------------- //
    //  Getters                                                              //
    // --------------------------------------------------------------------- //

    public String getTarget() {
        return target;
    }

    public Object getOriginalValue() {
        return originalValue;
    }

    public Object getAnonymizedValue() {
        return anonymizedValue;
    }

    public Status getStatus() {
        return status;
    }

    public List<String> getAppliedStrategies() {
        return appliedStrategies;
    }

    public Optional<String> getErrorMessage() {
        return Optional.ofNullable(errorMessage);
    }

    public Map<String, String> getMetadata() {
        return metadata;
    }

    public Instant getTimestamp() {
        return timestamp;
    }

    // --------------------------------------------------------------------- //
    //  Object methods                                                       //
    // --------------------------------------------------------------------- //

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof AnonymizationResult that)) return false;
        return Objects.equals(target, that.target)
                && Objects.equals(originalValue, that.originalValue)
                && Objects.equals(anonymizedValue, that.anonymizedValue)
                && status == that.status
                && Objects.equals(appliedStrategies, that.appliedStrategies)
                && Objects.equals(errorMessage, that.errorMessage)
                && Objects.equals(metadata, that.metadata)
                && Objects.equals(timestamp, that.timestamp);
    }

    @Override
    public int hashCode() {
        return Objects.hash(target, originalValue, anonymizedValue, status,
                appliedStrategies, errorMessage, metadata, timestamp);
    }

    @Override
    public String toString() {
        return "AnonymizationResult{" +
                "target='" + target + '\'' +
                ", status=" + status +
                ", timestamp=" + timestamp +
                '}';
    }

    // --------------------------------------------------------------------- //
    //  Builder                                                              //
    // --------------------------------------------------------------------- //

    private static final class Builder {
        private final Status status;
        private String target;
        private Object originalValue;
        private Object anonymizedValue;
        private List<String> appliedStrategies = Collections.emptyList();
        private String errorMessage;
        private Map<String, String> metadata = Collections.emptyMap();
        private Instant timestamp;

        private Builder(Status status) {
            this.status = status;
        }

        private Builder target(String target) {
            this.target = target;
            return this;
        }

        private Builder originalValue(Object originalValue) {
            this.originalValue = originalValue;
            return this;
        }

        private Builder anonymizedValue(Object anonymizedValue) {
            this.anonymizedValue = anonymizedValue;
            return this;
        }

        private Builder appliedStrategies(List<String> appliedStrategies) {
            this.appliedStrategies = appliedStrategies;
            return this;
        }

        private Builder errorMessage(String errorMessage) {
            this.errorMessage = errorMessage;
            return this;
        }

        private Builder metadata(Map<String, String> metadata) {
            this.metadata = metadata;
            return this;
        }

        private Builder timestamp(Instant timestamp) {
            this.timestamp = timestamp;
            return this;
        }

        private AnonymizationResult build() {
            // Invariant enforcement
            if (status == Status.SUCCESS && anonymizedValue == null) {
                throw new IllegalStateException(
                        "Successful result must contain an anonymizedValue");
            }
            if (status == Status.FAILURE && (errorMessage == null || errorMessage.isBlank())) {
                throw new IllegalStateException(
                        "Failure result must contain a non-blank errorMessage");
            }
            return new AnonymizationResult(this);
        }
    }

    // --------------------------------------------------------------------- //
    //  Enums                                                                //
    // --------------------------------------------------------------------- //

    /**
     * Binary status to simplify API responses and conditional logic.  If future
     * requirements demand more granularity (e.g., RETRIED, PARTIAL_SUCCESS),
     * this enum can be extended safely.
     */
    public enum Status {
        SUCCESS,
        FAILURE
    }
}