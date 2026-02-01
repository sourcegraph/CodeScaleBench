package com.sprintcart.domain.model.catalog;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.*;
import java.util.function.Predicate;

/**
 * Attribute represents a configurable piece of data that can be attached to a {@code Product},
 * {@code Category}, or any other catalog entity. An Attribute is immutable once created and must
 * be constructed via the {@link Builder}, which guarantees domain invariants such as unique code,
 * correct option definitions, and type/value compatibility.
 *
 * The design purposefully avoids any dependency on infrastructure‐level frameworks (JPA, Jackson, …)
 * so the domain model remains portable in a strict Hexagonal Architecture.
 */
public final class Attribute implements Serializable {

    @Serial
    private static final long serialVersionUID = 5723720175421695383L;

    /**
     * Unique, opaque identifier for this attribute.
     * Using a dedicated value object prevents accidental mix-ups with other UUIDs in the system.
     */
    public record AttributeId(UUID value) implements Serializable {
        @Serial private static final long serialVersionUID = 1L;

        public AttributeId {
            Objects.requireNonNull(value, "AttributeId value must not be null");
        }

        public static AttributeId random() {
            return new AttributeId(UUID.randomUUID());
        }
    }

    /**
     * Supported attribute data types.
     */
    public enum Type {
        TEXT(String.class, value -> ((String) value).length() <= 500),
        NUMBER(BigDecimal.class, value -> true), // range is validated separately
        BOOLEAN(Boolean.class, value -> true),
        DATE(LocalDate.class, value -> true),
        ENUM(String.class, value -> true),
        MULTI_ENUM(Collection.class, value -> true);

        private final Class<?> javaType;
        private final Predicate<Object> intrinsicValidator;

        Type(Class<?> javaType, Predicate<Object> intrinsicValidator) {
            this.javaType = javaType;
            this.intrinsicValidator = intrinsicValidator;
        }

        boolean supports(Object value) {
            return value != null && javaType.isAssignableFrom(value.getClass()) && intrinsicValidator.test(value);
        }

        public Class<?> javaType() {
            return javaType;
        }
    }

    /**
     * Option is only relevant for {@link Type#ENUM} or {@link Type#MULTI_ENUM}.
     */
    public record Option(String code, Map<Locale, String> labels) implements Serializable {
        @Serial private static final long serialVersionUID = -4040076890688736837L;

        public Option {
            Objects.requireNonNull(code, "Option code must not be null");
            Objects.requireNonNull(labels, "Option labels must not be null");
            if (code.isBlank()) {
                throw new IllegalArgumentException("Option code cannot be blank");
            }
        }

        public String label(Locale locale) {
            return labels.getOrDefault(locale, labels.getOrDefault(Locale.ENGLISH, code));
        }
    }

    private final AttributeId id;
    private final String code;
    private final Map<Locale, String> displayNames;
    private final Type type;
    private final boolean required;
    private final boolean variantAxis;
    private final BigDecimal min;                 // only for NUMBER
    private final BigDecimal max;                 // only for NUMBER
    private final Set<Option> options;            // only for ENUM/MULTI_ENUM

    private Attribute(Builder builder) {
        this.id = builder.id;
        this.code = builder.code;
        this.displayNames = Collections.unmodifiableMap(new HashMap<>(builder.displayNames));
        this.type = builder.type;
        this.required = builder.required;
        this.variantAxis = builder.variantAxis;
        this.min = builder.min;
        this.max = builder.max;
        this.options = builder.options == null ? Collections.emptySet()
                : Collections.unmodifiableSet(new LinkedHashSet<>(builder.options));
    }

    /** ----------------------------------------------------------------------------
     *  Public factory access
     *  ---------------------------------------------------------------------------*/

    public static Builder builder(String code, Type type) {
        return new Builder(code, type);
    }

    /** ----------------------------------------------------------------------------
     *  Domain behaviour
     *  ---------------------------------------------------------------------------*/

    /**
     * Validates a value against this attribute's definition.
     *
     * @param value the value to be validated (may be {@code Collection} for MULTI_ENUM)
     * @throws ValidationException if validation fails
     */
    public void validateValue(Object value) {
        if (value == null) {
            if (required) {
                throw new ValidationException("Value is required for attribute " + code);
            }
            return; // nothing to validate
        }

        switch (type) {
            case TEXT, BOOLEAN, DATE -> validateSingle(value);
            case NUMBER -> validateNumber(value);
            case ENUM -> validateEnum(value);
            case MULTI_ENUM -> validateMultiEnum(value);
            default -> throw new IllegalStateException("Unhandled type " + type);
        }
    }

    private void validateSingle(Object value) {
        if (!type.supports(value)) {
            throw typeMismatch(value);
        }
    }

    private void validateNumber(Object value) {
        if (!(value instanceof BigDecimal number)) {
            throw typeMismatch(value);
        }
        if (min != null && number.compareTo(min) < 0) {
            throw new ValidationException("Number below minimum (" + min + "): " + number);
        }
        if (max != null && number.compareTo(max) > 0) {
            throw new ValidationException("Number above maximum (" + max + "): " + number);
        }
    }

    private void validateEnum(Object value) {
        if (!(value instanceof String s)) {
            throw typeMismatch(value);
        }
        ensureOptionExists(s);
    }

    private void validateMultiEnum(Object value) {
        if (!(value instanceof Collection<?> coll)) {
            throw typeMismatch(value);
        }
        for (Object v : coll) {
            if (!(v instanceof String s)) {
                throw typeMismatch(v);
            }
            ensureOptionExists(s);
        }
    }

    private void ensureOptionExists(String optionCode) {
        boolean exists = options.stream().anyMatch(o -> o.code().equals(optionCode));
        if (!exists) {
            throw new ValidationException("Unsupported option '" + optionCode + "' for attribute " + code);
        }
    }

    private ValidationException typeMismatch(Object value) {
        return new ValidationException("Type mismatch for attribute " + code +
                ". Expected " + type.javaType().getSimpleName() + ", got " + value.getClass().getSimpleName());
    }

    /** ----------------------------------------------------------------------------
     *  Value objects
     *  ---------------------------------------------------------------------------*/

    /**
     * Wrapper exception to signal validation issues at domain level.
     */
    public static class ValidationException extends RuntimeException {
        @Serial private static final long serialVersionUID = 4186496331124842635L;

        public ValidationException(String message) {
            super(message);
        }
    }

    /** ----------------------------------------------------------------------------
     *  Builder
     *  ---------------------------------------------------------------------------*/

    public static final class Builder {
        private final AttributeId id = AttributeId.random();
        private final String code;
        private final Type type;

        private Map<Locale, String> displayNames = new HashMap<>();
        private boolean required;
        private boolean variantAxis;
        private BigDecimal min;
        private BigDecimal max;
        private Set<Option> options;

        private Builder(String code, Type type) {
            this.code = Objects.requireNonNull(code, "Attribute code must not be null").trim().toLowerCase(Locale.ROOT);
            if (this.code.isBlank()) {
                throw new IllegalArgumentException("Attribute code must not be blank");
            }
            this.type = Objects.requireNonNull(type, "Attribute type must not be null");
        }

        /* ------------------------------------------------------------------- */
        /*     Fluent setters                                                  */
        /* ------------------------------------------------------------------- */

        public Builder displayName(Locale locale, String name) {
            Objects.requireNonNull(locale, "Locale must not be null");
            Objects.requireNonNull(name, "Name must not be null");
            if (name.isBlank()) {
                throw new IllegalArgumentException("Display name cannot be blank");
            }
            displayNames.put(locale, name.trim());
            return this;
        }

        public Builder required(boolean required) {
            this.required = required;
            return this;
        }

        public Builder variantAxis(boolean variantAxis) {
            this.variantAxis = variantAxis;
            return this;
        }

        public Builder numericRange(BigDecimal min, BigDecimal max) {
            ensureType(Type.NUMBER);
            if (min != null && max != null && min.compareTo(max) > 0) {
                throw new IllegalArgumentException("Min cannot be greater than max");
            }
            this.min = min;
            this.max = max;
            return this;
        }

        public Builder options(Collection<Option> options) {
            ensureType(Type.ENUM, Type.MULTI_ENUM);
            if (options == null || options.isEmpty()) {
                throw new IllegalArgumentException("Options must not be empty");
            }
            // enforce unique codes
            Set<String> codes = new HashSet<>();
            for (Option option : options) {
                if (!codes.add(option.code())) {
                    throw new IllegalArgumentException("Duplicate option code: " + option.code());
                }
            }
            this.options = new LinkedHashSet<>(options);
            return this;
        }

        private void ensureType(Type... expected) {
            List<Type> list = Arrays.asList(expected);
            if (!list.contains(type)) {
                throw new IllegalStateException("Cannot call this method for attribute type " + type);
            }
        }

        public Attribute build() {
            // basic display name fallback
            displayNames.putIfAbsent(Locale.ENGLISH, code);

            // additional invariant checks
            if ((type == Type.ENUM || type == Type.MULTI_ENUM) && (options == null || options.isEmpty())) {
                throw new IllegalStateException("ENUM/MULTI_ENUM attributes must define options");
            }
            if (type == Type.NUMBER && (min == null || max == null)) {
                throw new IllegalStateException("NUMBER attributes must define a numeric range");
            }
            return new Attribute(this);
        }
    }

    /** ----------------------------------------------------------------------------
     *  Getters (immutability, no setters!)
     *  ---------------------------------------------------------------------------*/

    public AttributeId id() {
        return id;
    }

    public String code() {
        return code;
    }

    public String displayName(Locale locale) {
        return displayNames.getOrDefault(locale, displayNames.get(Locale.ENGLISH));
    }

    public Type type() {
        return type;
    }

    public boolean required() {
        return required;
    }

    public boolean variantAxis() {
        return variantAxis;
    }

    public Optional<BigDecimal> min() {
        return Optional.ofNullable(min);
    }

    public Optional<BigDecimal> max() {
        return Optional.ofNullable(max);
    }

    public Set<Option> options() {
        return options;
    }

    /** ----------------------------------------------------------------------------
     *  Equality
     *  ---------------------------------------------------------------------------*/

    @Override
    public boolean equals(Object o) {
        return this == o || (o instanceof Attribute a && Objects.equals(id, a.id));
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    @Override
    public String toString() {
        return "Attribute{" +
                "id=" + id +
                ", code='" + code + '\'' +
                ", type=" + type +
                ", required=" + required +
                ", variantAxis=" + variantAxis +
                '}';
    }
}