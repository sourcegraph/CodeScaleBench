package com.opsforge.nexus.anonymizer.domain.model;

import java.io.Serial;
import java.io.Serializable;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

/**
 * Domain-level representation of an anonymization configuration.
 * <p>
 * The configuration is an immutable value object that maps source field names
 * to {@link FieldConfig}s describing how each field must be anonymized.
 * <p>
 * This class purposefully avoids references to infrastructure-specific concepts
 * (e.g., database column names, JSON libraries, Spring annotations) in order to
 * preserve the portability guarantees that Hexagonal Architecture provides.
 */
public final class AnonymizationConfig implements Serializable {

    @Serial
    private static final long serialVersionUID = -2282380032142983358L;

    /**
     * Maps fully-qualified field identifiers (e.g., "user.email") to their
     * anonymization strategy details.
     */
    private final Map<String, FieldConfig> fieldConfigs;

    private AnonymizationConfig(Map<String, FieldConfig> fieldConfigs) {
        // defend deep immutability
        this.fieldConfigs = Collections.unmodifiableMap(new LinkedHashMap<>(fieldConfigs));
    }

    /**
     * Retrieves the {@link FieldConfig} for the supplied field name if present.
     *
     * @param fieldName The canonical field identifier.
     * @return an {@link Optional} containing the configuration when defined.
     */
    public Optional<FieldConfig> configFor(String fieldName) {
        return Optional.ofNullable(fieldConfigs.get(fieldName));
    }

    /**
     * @return an unmodifiable view of all field configurations.
     */
    public Map<String, FieldConfig> all() {
        return fieldConfigs;
    }

    /**
     * Indicates whether this configuration is empty (i.e., no fields are
     * configured for anonymization).
     */
    public boolean isEmpty() {
        return fieldConfigs.isEmpty();
    }

    @Override
    public String toString() {
        return "AnonymizationConfig{" +
               "fieldConfigs=" + fieldConfigs +
               '}';
    }

    @Override
    public int hashCode() {
        return Objects.hash(fieldConfigs);
    }

    @Override
    public boolean equals(Object obj) {
        if (!(obj instanceof AnonymizationConfig other)) {
            return false;
        }
        return Objects.equals(this.fieldConfigs, other.fieldConfigs);
    }

    /* -------------------------------------------------- *
     *  Builder
     * -------------------------------------------------- */

    /**
     * Returns a new {@link Builder} instance.
     */
    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {

        private final Map<String, FieldConfig> fieldConfigs = new LinkedHashMap<>();

        private Builder() {
        }

        /**
         * Adds a {@link FieldConfig} for a particular field.
         *
         * @param fieldName   unique field identifier (e.g., "card.number").
         * @param fieldConfig configuration details.
         * @return the builder.
         * @throws IllegalArgumentException if the field name is blank or already defined.
         * @throws NullPointerException     if {@code fieldConfig} is {@code null}.
         */
        public Builder field(String fieldName, FieldConfig fieldConfig) {
            Objects.requireNonNull(fieldConfig, "fieldConfig must not be null");

            if (fieldName == null || fieldName.trim().isEmpty()) {
                throw new IllegalArgumentException("fieldName must not be blank");
            }
            if (fieldConfigs.containsKey(fieldName)) {
                throw new IllegalArgumentException("Duplicate fieldName: " + fieldName);
            }
            fieldConfigs.put(fieldName, fieldConfig);
            return this;
        }

        /**
         * Builds an immutable {@link AnonymizationConfig} after performing basic validation.
         *
         * @return {@link AnonymizationConfig}.
         * @throws IllegalStateException if the configuration would be empty.
         */
        public AnonymizationConfig build() {
            if (fieldConfigs.isEmpty()) {
                throw new IllegalStateException("AnonymizationConfig must configure at least one field");
            }
            return new AnonymizationConfig(fieldConfigs);
        }
    }

    /* -------------------------------------------------- *
     *  Field Configuration
     * -------------------------------------------------- */

    /**
     * Encapsulates anonymization behavior for a single field.
     */
    public static final class FieldConfig implements Serializable {

        @Serial
        private static final long serialVersionUID = 134782125942L;

        private final Strategy strategy;
        private final String maskingCharacter;
        private final int visiblePrefix;
        private final int visibleSuffix;
        private final Map<String, String> parameters;

        private FieldConfig(Strategy strategy,
                            String maskingCharacter,
                            int visiblePrefix,
                            int visibleSuffix,
                            Map<String, String> parameters) {

            this.strategy = Objects.requireNonNull(strategy, "strategy must not be null");
            this.maskingCharacter = maskingCharacter; // may be null for non-MASK strategies
            this.visiblePrefix = visiblePrefix;
            this.visibleSuffix = visibleSuffix;
            this.parameters = parameters == null || parameters.isEmpty()
                              ? Collections.emptyMap()
                              : Collections.unmodifiableMap(new LinkedHashMap<>(parameters));

            validateInternalState();
        }

        private void validateInternalState() {
            if (strategy == Strategy.MASK) {
                if (maskingCharacter == null || maskingCharacter.isEmpty()) {
                    throw new IllegalArgumentException("Masking strategy requires a maskingCharacter");
                }
                if (visiblePrefix < 0 || visibleSuffix < 0) {
                    throw new IllegalArgumentException("visiblePrefix and visibleSuffix must be >= 0");
                }
            }
            if (strategy == Strategy.CUSTOM && parameters.isEmpty()) {
                throw new IllegalArgumentException("CUSTOM strategy requires a non-empty parameter map");
            }
        }

        public Strategy strategy() {
            return strategy;
        }

        public String maskingCharacter() {
            return maskingCharacter;
        }

        public int visiblePrefix() {
            return visiblePrefix;
        }

        public int visibleSuffix() {
            return visibleSuffix;
        }

        /**
         * Additional, implementation-specific parameters (used notably for the
         * {@link Strategy#CUSTOM} strategy but can accompany any strategy).
         */
        public Map<String, String> parameters() {
            return parameters;
        }

        @Override
        public String toString() {
            return "FieldConfig{" +
                   "strategy=" + strategy +
                   ", maskingCharacter='" + maskingCharacter + '\'' +
                   ", visiblePrefix=" + visiblePrefix +
                   ", visibleSuffix=" + visibleSuffix +
                   ", parameters=" + parameters +
                   '}';
        }

        @Override
        public int hashCode() {
            return Objects.hash(strategy, maskingCharacter, visiblePrefix, visibleSuffix, parameters);
        }

        @Override
        public boolean equals(Object obj) {
            if (!(obj instanceof FieldConfig other)) {
                return false;
            }
            return strategy == other.strategy
                   && Objects.equals(maskingCharacter, other.maskingCharacter)
                   && visiblePrefix == other.visiblePrefix
                   && visibleSuffix == other.visibleSuffix
                   && Objects.equals(parameters, other.parameters);
        }

        /* ------------------------------------------ *
         *  Builder
         * ------------------------------------------ */

        public static FieldConfigBuilder builder() {
            return new FieldConfigBuilder();
        }

        public static final class FieldConfigBuilder {
            private Strategy strategy;
            private String maskingCharacter;
            private int visiblePrefix;
            private int visibleSuffix;
            private Map<String, String> parameters;

            private FieldConfigBuilder() {
            }

            public FieldConfigBuilder strategy(Strategy strategy) {
                this.strategy = strategy;
                return this;
            }

            /**
             * Applicable for {@link Strategy#MASK} only.
             */
            public FieldConfigBuilder maskingCharacter(char maskingCharacter) {
                this.maskingCharacter = String.valueOf(maskingCharacter);
                return this;
            }

            /**
             * Applicable for {@link Strategy#MASK} only.
             */
            public FieldConfigBuilder visiblePrefix(int visiblePrefix) {
                this.visiblePrefix = visiblePrefix;
                return this;
            }

            /**
             * Applicable for {@link Strategy#MASK} only.
             */
            public FieldConfigBuilder visibleSuffix(int visibleSuffix) {
                this.visibleSuffix = visibleSuffix;
                return this;
            }

            /**
             * Implementation-specific parameters, mainly used by {@link Strategy#CUSTOM}.
             */
            public FieldConfigBuilder parameters(Map<String, String> parameters) {
                this.parameters = parameters;
                return this;
            }

            public FieldConfig build() {
                return new FieldConfig(strategy, maskingCharacter, visiblePrefix, visibleSuffix, parameters);
            }
        }
    }

    /**
     * Core anonymization strategies supported by the platform.
     *
     * Implementers are free to support additional strategies through the
     * {@link Strategy#CUSTOM} option, which relies on the
     * {@link FieldConfig#parameters()} map for domain-specific instructions.
     */
    public enum Strategy {

        /**
         * Replaces the field value with {@code null}.
         */
        NULLIFY,

        /**
         * Replaces the field value with a fixed-length random string comprised
         * of alphanumeric characters.
         */
        RANDOM,

        /**
         * Calculates a one-way SHA-256 hash of the field value. The hash is
         * rendered in hex format and truncated/padded to fit column constraints
         * in downstream systems.
         */
        HASH,

        /**
         * Masks the original value while preserving parts of the prefix/suffix.
         * For instance: "john.doe@example.com" → "j***************m".
         */
        MASK,

        /**
         * Delegates the anonymization to an external strategy identified through
         * {@link FieldConfig#parameters()} (e.g., "beanName=myCustomStrategy").
         */
        CUSTOM
    }
}