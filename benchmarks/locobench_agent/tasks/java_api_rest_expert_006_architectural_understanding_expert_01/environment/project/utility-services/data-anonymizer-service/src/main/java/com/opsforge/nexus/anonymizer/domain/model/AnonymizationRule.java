package com.opsforge.nexus.anonymizer.domain.model;

import java.io.Serial;
import java.io.Serializable;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.Collections;
import java.util.EnumSet;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/**
 * Immutable value object that represents a single, executable anonymization rule.
 * Rules live purely in the domain layer and are deliberately agnostic of transport,
 * persistence, and infrastructure frameworks.
 *
 * Example JSON representation (for a REST adapter) might look like:
 *
 * <pre>
 * {
 *     "id": "08de5042-0c3d-4a1a-a5ef-e1d3f235e128",
 *     "fieldPath": "user.email",
 *     "strategy": "HASH_SHA256",
 *     "params": { }
 * }
 * </pre>
 */
public final class AnonymizationRule implements Serializable {

    @Serial
    private static final long serialVersionUID = 3275908787600189960L;

    /**
     * Common parameter keys used across strategies.
     */
    public static final class ParamKey {
        public static final String MASK_CHAR   = "maskChar";
        public static final String MASK_LENGTH = "maskLength";
        public static final String CONSTANT    = "constant";
        private ParamKey() { }
    }

    /**
     * Algorithm/technique used to anonymize the target field.
     */
    public enum Strategy {

        /**
         * Replace the value with a repeated mask character. 
         * Required params:
         * - {@code maskChar} (String, single character)
         * - {@code maskLength} (Integer)
         */
        MASK(Set.of(ParamKey.MASK_CHAR, ParamKey.MASK_LENGTH)) {
            @Override
            protected Object applyInternal(Object original, Map<String, Object> params) {
                char maskChar = String.valueOf(params.get(ParamKey.MASK_CHAR)).charAt(0);
                int length    = Integer.parseInt(params.get(ParamKey.MASK_LENGTH).toString());
                return String.valueOf(maskChar).repeat(length);
            }
        },

        /**
         * Replace the value with a constant provided at rule-definition time.
         * Required params:
         * - {@code constant} (String)
         */
        CONSTANT_REPLACEMENT(Set.of(ParamKey.CONSTANT)) {
            @Override
            protected Object applyInternal(Object original, Map<String, Object> params) {
                return params.get(ParamKey.CONSTANT);
            }
        },

        /**
         * Cryptographically hash the value with SHA-256 and return the
         * lowercase hexadecimal string.
         * No params required.
         */
        HASH_SHA256(Collections.emptySet()) {
            @Override
            protected Object applyInternal(Object original, Map<String, Object> params) {
                try {
                    MessageDigest digest = MessageDigest.getInstance("SHA-256");
                    byte[] hashedBytes   = digest.digest(
                            Objects.toString(original, "").getBytes(java.nio.charset.StandardCharsets.UTF_8)
                    );
                    StringBuilder sb = new StringBuilder(hashedBytes.length * 2);
                    for (byte b : hashedBytes) {
                        sb.append(String.format("%02x", b));
                    }
                    return sb.toString();
                } catch (NoSuchAlgorithmException e) {
                    // SHA-256 is guaranteed to exist, but we wrap in a runtime exception for completeness.
                    throw new IllegalStateException("SHA-256 not available in JVM", e);
                }
            }
        },

        /**
         * Remove the value entirely (null).
         */
        REMOVE(Collections.emptySet()) {
            @Override
            protected Object applyInternal(Object original, Map<String, Object> params) {
                return null;
            }
        },

        /**
         * Replace the value with a type-appropriate random counterpart.
         * • Strings => random UUID
         * • Numbers => current epoch millis
         * • Booleans => false
         * • Others  => {@code null}
         */
        RANDOMIZE(Collections.emptySet()) {
            @Override
            protected Object applyInternal(Object original, Map<String, Object> params) {

                if (original instanceof String) {
                    return UUID.randomUUID().toString();
                }
                if (original instanceof Number) {
                    return Instant.now().toEpochMilli();
                }
                if (original instanceof Boolean) {
                    return Boolean.FALSE;
                }
                // Default fallback
                return null;
            }
        };

        private final Set<String> requiredParams;

        Strategy(Set<String> requiredParams) {
            this.requiredParams = EnumSet.copyOf(requiredParams);
        }

        /**
         * Execute the anonymization for the given input.
         *
         * Domain invariants:
         *  • A required parameter must exist and be non-null
         *  • Strategies should never mutate the original input object
         *
         * @param original original field value
         * @param params   rule-level parameters
         * @return anonymized value
         * @throws IllegalArgumentException when validation fails
         */
        public final Object apply(Object original, Map<String, Object> params) {
            validate(params);
            return applyInternal(original, params == null ? Collections.emptyMap() : params);
        }

        protected abstract Object applyInternal(Object original, Map<String, Object> params);

        private void validate(Map<String, Object> params) {
            for (String key : requiredParams) {
                if (params == null || !params.containsKey(key) || params.get(key) == null) {
                    throw new IllegalArgumentException(
                            "Missing required param '%s' for strategy %s".formatted(key, name()));
                }
            }
        }
    }

    private final UUID id;
    private final String fieldPath;
    private final Strategy strategy;
    private final Map<String, Object> params;

    private AnonymizationRule(Builder builder) {
        this.id        = builder.id   == null ? UUID.randomUUID() : builder.id;
        this.fieldPath = Objects.requireNonNull(builder.fieldPath, "fieldPath must not be null");
        this.strategy  = Objects.requireNonNull(builder.strategy,  "strategy must not be null");
        this.params    = Collections.unmodifiableMap(
                builder.params == null ? Collections.emptyMap() : builder.params
        );
    }

    public UUID getId() {
        return id;
    }

    /**
     * The target field expressed in dot-notation (e.g., {@code user.address.street}).
     * Interpretation of the path is deferred to application-level components.
     */
    public String getFieldPath() {
        return fieldPath;
    }

    public Strategy getStrategy() {
        return strategy;
    }

    public Map<String, Object> getParams() {
        return params;
    }

    /**
     * Convenience method used by application services to apply the rule
     * without having to expose {@link Strategy} internals.
     *
     * @param currentValue the current, non-anonymized value of the field
     * @return anonymized value
     */
    public Object anonymize(Object currentValue) {
        return strategy.apply(currentValue, params);
    }

    // --------------------------------------------------------------------- //
    // Equality & representation
    // --------------------------------------------------------------------- //

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof AnonymizationRule that)) return false;
        return id.equals(that.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    @Override
    public String toString() {
        return "AnonymizationRule{" +
                "id=" + id +
                ", fieldPath='" + fieldPath + '\'' +
                ", strategy=" + strategy +
                ", params=" + params +
                '}';
    }

    // --------------------------------------------------------------------- //
    // Builder
    // --------------------------------------------------------------------- //

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {

        private UUID id;
        private String fieldPath;
        private Strategy strategy;
        private Map<String, Object> params;

        private Builder() { }

        public Builder id(UUID id) {
            this.id = id;
            return this;
        }

        public Builder fieldPath(String fieldPath) {
            this.fieldPath = fieldPath;
            return this;
        }

        public Builder strategy(Strategy strategy) {
            this.strategy = strategy;
            return this;
        }

        public Builder params(Map<String, Object> params) {
            this.params = params;
            return this;
        }

        public AnonymizationRule build() {
            return new AnonymizationRule(this);
        }
    }
}