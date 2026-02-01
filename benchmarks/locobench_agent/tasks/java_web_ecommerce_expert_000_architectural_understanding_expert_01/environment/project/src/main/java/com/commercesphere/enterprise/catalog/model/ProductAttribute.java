package com.commercesphere.enterprise.catalog.model;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.persistence.Basic;
import jakarta.persistence.Column;
import jakarta.persistence.Convert;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import jakarta.persistence.Temporal;
import jakarta.persistence.TemporalType;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.hibernate.Hibernate;

import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.Objects;
import java.util.Optional;

/**
 * Domain model that represents a single, typed attribute assigned to a
 * {@link Product}. To keep the data layer loosely coupled from the business
 * layer, all values are stored as raw Strings in the database and converted
 * on–the–fly into the proper Java types.
 *
 * The class performs basic self-validation at lifecycle hooks to guarantee
 * that persisted data always complies with the declared {@link ValueType}.
 */
@Entity
@Table(
        name = "product_attributes",
        indexes = @Index(name = "idx_attr_product_code", columnList = "product_id,code", unique = true)
)
public class ProductAttribute implements Serializable {

    @Serial
    private static final long serialVersionUID = 3238517035943343192L;

    // --------------------------------------------------------------------- //
    // JPA Columns
    // --------------------------------------------------------------------- //

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * Owning side of the many-to-one relation. We purposefully keep the
     * association lazy because attributes can be fetched in bulk for batch
     * validation without loading their parent {@link Product}s.
     */
    @ManyToOne(optional = false)
    @JoinColumn(name = "product_id", nullable = false, updatable = false)
    @JsonIgnore
    private Product product;

    @NotBlank
    @Column(nullable = false, length = 120)
    private String code;

    @NotBlank
    @Column(nullable = false, length = 255)
    private String label;

    @NotNull
    @Column(name = "value_type", nullable = false, length = 16)
    private ValueType valueType;

    /**
     * The raw, unparsed value stored in the database. Consumers are
     * encouraged to use the type-safe getters such as
     * {@link #asInteger()} or {@link #asDate()}.
     */
    @Basic(optional = false)
    @Column(name = "raw_value", nullable = false, columnDefinition = "TEXT")
    private String rawValue;

    // --------------------------------------------------------------------- //
    // Lifecycle hooks
    // --------------------------------------------------------------------- //

    @PrePersist
    @PreUpdate
    private void validateBeforeSave() {
        validateRawValue();
    }

    // --------------------------------------------------------------------- //
    // Factory / Builder
    // --------------------------------------------------------------------- //

    protected ProductAttribute() {
        // JPA
    }

    private ProductAttribute(Builder builder) {
        this.product = builder.product;
        this.code = builder.code;
        this.label = builder.label;
        this.valueType = builder.valueType;
        this.rawValue = builder.rawValue;
    }

    public static Builder builder() {
        return new Builder();
    }

    // --------------------------------------------------------------------- //
    // Business logic
    // --------------------------------------------------------------------- //

    /**
     * Verifies that {@link #rawValue} complies with {@link #valueType}.
     * Throws an {@link IllegalArgumentException} if a mismatch is detected.
     */
    public void validateRawValue() {
        if (valueType == null) {
            throw new IllegalStateException("valueType must not be null");
        }
        if (rawValue == null) {
            throw new IllegalStateException("rawValue must not be null");
        }

        try {
            switch (valueType) {
                case STRING -> {/* always valid */}
                case INTEGER -> Integer.parseInt(rawValue);
                case DECIMAL -> new BigDecimal(rawValue);
                case BOOLEAN -> {
                    if (!"true".equalsIgnoreCase(rawValue) && !"false".equalsIgnoreCase(rawValue)) {
                        throw new IllegalArgumentException("Invalid boolean: " + rawValue);
                    }
                }
                case DATE -> LocalDate.parse(rawValue); // ISO-8601
                default -> throw new IllegalStateException("Unhandled valueType " + valueType);
            }
        } catch (NumberFormatException | DateTimeParseException ex) {
            throw new IllegalArgumentException(
                    "ProductAttribute " + code + ": rawValue does not match valueType " + valueType, ex
            );
        }
    }

    // --------------------------------------------------------------------- //
    // Typed getters
    // --------------------------------------------------------------------- //

    public Optional<String> asString() {
        return Optional.ofNullable(rawValue);
    }

    public Optional<Integer> asInteger() {
        try {
            return Optional.of(Integer.valueOf(rawValue));
        } catch (NumberFormatException e) {
            return Optional.empty();
        }
    }

    public Optional<BigDecimal> asDecimal() {
        try {
            return Optional.of(new BigDecimal(rawValue));
        } catch (NumberFormatException e) {
            return Optional.empty();
        }
    }

    public Optional<Boolean> asBoolean() {
        if ("true".equalsIgnoreCase(rawValue) || "false".equalsIgnoreCase(rawValue)) {
            return Optional.of(Boolean.parseBoolean(rawValue));
        }
        return Optional.empty();
    }

    public Optional<LocalDate> asDate() {
        try {
            return Optional.of(LocalDate.parse(rawValue));
        } catch (DateTimeParseException e) {
            return Optional.empty();
        }
    }

    // --------------------------------------------------------------------- //
    // Plain getters / setters
    // --------------------------------------------------------------------- //

    public Long getId() {
        return id;
    }

    public Product getProduct() {
        return product;
    }

    public String getCode() {
        return code;
    }

    public String getLabel() {
        return label;
    }

    public ValueType getValueType() {
        return valueType;
    }

    @JsonProperty("value")
    public String getRawValue() {
        return rawValue;
    }

    /**
     * Updates the attribute with a new value and immediately validates it
     * against {@link #valueType}.
     *
     * @param newValue raw input. Cannot be {@code null}.
     * @throws IllegalArgumentException if the value cannot be parsed
     *                                  according to the existing type.
     */
    public void updateValue(String newValue) {
        Objects.requireNonNull(newValue, "newValue must not be null");
        this.rawValue = newValue;
        validateRawValue();
    }

    // --------------------------------------------------------------------- //
    // equals / hashCode / toString
    // --------------------------------------------------------------------- //

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || Hibernate.getClass(this) != Hibernate.getClass(o)) return false;
        ProductAttribute that = (ProductAttribute) o;
        return id != null && Objects.equals(id, that.id);
    }

    @Override
    public int hashCode() {
        return getClass().hashCode();
    }

    @Override
    public String toString() {
        return "ProductAttribute[" +
                "id=" + id +
                ", code='" + code + '\'' +
                ", valueType=" + valueType +
                ", rawValue='" + rawValue + '\'' +
                ']';
    }

    // --------------------------------------------------------------------- //
    // Enum definition
    // --------------------------------------------------------------------- //

    /**
     * Defines the allowed data types for a {@link ProductAttribute}.
     */
    public enum ValueType {
        STRING,
        INTEGER,
        DECIMAL,
        BOOLEAN,
        DATE
    }

    // --------------------------------------------------------------------- //
    // Builder pattern
    // --------------------------------------------------------------------- //

    public static final class Builder {
        private Product product;
        private String code;
        private String label;
        private ValueType valueType;
        private String rawValue;

        private Builder() {
        }

        public Builder product(Product product) {
            this.product = product;
            return this;
        }

        public Builder code(String code) {
            this.code = code;
            return this;
        }

        public Builder label(String label) {
            this.label = label;
            return this;
        }

        public Builder valueType(ValueType valueType) {
            this.valueType = valueType;
            return this;
        }

        public Builder rawValue(String rawValue) {
            this.rawValue = rawValue;
            return this;
        }

        public ProductAttribute build() {
            Objects.requireNonNull(product, "product is required");
            Objects.requireNonNull(code, "code is required");
            Objects.requireNonNull(label, "label is required");
            Objects.requireNonNull(valueType, "valueType is required");
            Objects.requireNonNull(rawValue, "rawValue is required");

            ProductAttribute attribute = new ProductAttribute(this);
            attribute.validateRawValue();
            return attribute;
        }
    }
}