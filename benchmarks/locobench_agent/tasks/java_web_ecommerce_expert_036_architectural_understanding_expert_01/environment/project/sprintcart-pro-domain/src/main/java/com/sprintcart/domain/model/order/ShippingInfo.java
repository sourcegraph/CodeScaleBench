package com.sprintcart.domain.model.order;

import java.io.Serializable;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.Currency;
import java.util.Objects;
import java.util.regex.Pattern;

/**
 * Value object representing the shipping information associated with an Order.
 * <p>
 * The class is immutable and side-effect-free. Any state transition produces a
 * brand-new instance, which helps keep the domain model thread-safe and
 * intention-revealing.
 */
public final class ShippingInfo implements Serializable {

    private static final long serialVersionUID = 1L;

    private final Recipient recipient;
    private final Address address;
    private final ShippingMethod method;
    private final Money cost;
    private final String trackingNumber;
    private final DeliveryStatus status;
    private final LocalDate estimatedDeliveryDate;
    private final LocalDateTime createdAt;
    private final LocalDateTime updatedAt;

    private ShippingInfo(Builder builder) {
        this.recipient = builder.recipient;
        this.address = builder.address;
        this.method = builder.method;
        this.cost = builder.cost;
        this.trackingNumber = builder.trackingNumber;
        this.status = builder.status;
        this.estimatedDeliveryDate = builder.estimatedDeliveryDate;
        this.createdAt = builder.createdAt != null ? builder.createdAt : LocalDateTime.now();
        this.updatedAt = builder.updatedAt != null ? builder.updatedAt : this.createdAt;

        validateState();
    }

    private void validateState() {
        Objects.requireNonNull(recipient, "Recipient must not be null");
        Objects.requireNonNull(address, "Address must not be null");
        Objects.requireNonNull(method, "Shipping method must not be null");
        Objects.requireNonNull(cost, "Shipping cost must not be null");
        Objects.requireNonNull(status, "Delivery status must not be null");

        if (cost.getAmount().compareTo(BigDecimal.ZERO) < 0) {
            throw new IllegalArgumentException("Shipping cost cannot be negative");
        }

        // Once an order is shipped, tracking number must be present.
        if (status.ordinal() >= DeliveryStatus.SHIPPED.ordinal()
                && (trackingNumber == null || trackingNumber.isBlank())) {
            throw new IllegalStateException("Tracking number is required once parcel has shipped");
        }
    }

    /* ---------- Domain-driven state transitions ---------- */

    /**
     * Adds or replaces the parcel tracking number. The delivery status will be
     * upgraded to SHIPPED if it is still earlier in the lifecycle.
     */
    public ShippingInfo withTracking(String newTrackingNumber) {
        if (newTrackingNumber == null || newTrackingNumber.isBlank()) {
            throw new IllegalArgumentException("Tracking number must not be blank");
        }

        return new Builder(this)
                .trackingNumber(newTrackingNumber)
                .status(status.ordinal() < DeliveryStatus.SHIPPED.ordinal()
                        ? DeliveryStatus.SHIPPED
                        : status)
                .updatedAt(LocalDateTime.now())
                .build();
    }

    /**
     * Advances (never regresses) the delivery status.
     *
     * @param nextStatus the new status
     * @return a new instance with the updated status
     */
    public ShippingInfo advanceStatus(DeliveryStatus nextStatus) {
        Objects.requireNonNull(nextStatus, "nextStatus cannot be null");
        if (nextStatus.ordinal() < status.ordinal()) {
            throw new IllegalArgumentException("Cannot regress delivery status");
        }

        return new Builder(this)
                .status(nextStatus)
                .updatedAt(LocalDateTime.now())
                .build();
    }

    /* ---------- Getters ---------- */

    public Recipient getRecipient()                 { return recipient; }
    public Address getAddress()                     { return address; }
    public ShippingMethod getMethod()               { return method; }
    public Money getCost()                          { return cost; }
    public String getTrackingNumber()               { return trackingNumber; }
    public DeliveryStatus getStatus()               { return status; }
    public LocalDate getEstimatedDeliveryDate()     { return estimatedDeliveryDate; }
    public LocalDateTime getCreatedAt()             { return createdAt; }
    public LocalDateTime getUpdatedAt()             { return updatedAt; }

    /* ---------- Equality ---------- */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof ShippingInfo that)) return false;
        return Objects.equals(recipient, that.recipient)
                && Objects.equals(address, that.address)
                && method == that.method
                && Objects.equals(cost, that.cost)
                && Objects.equals(trackingNumber, that.trackingNumber)
                && status == that.status
                && Objects.equals(estimatedDeliveryDate, that.estimatedDeliveryDate);
    }

    @Override
    public int hashCode() {
        return Objects.hash(recipient, address, method, cost,
                trackingNumber, status, estimatedDeliveryDate);
    }

    @Override
    public String toString() {
        return "ShippingInfo{" +
                "recipient=" + recipient +
                ", address=" + MaskUtil.maskAddress(address) +
                ", method=" + method +
                ", cost=" + cost +
                ", trackingNumber='" + MaskUtil.maskTracking(trackingNumber) + '\'' +
                ", status=" + status +
                ", estimatedDeliveryDate=" + estimatedDeliveryDate +
                '}';
    }

    /* ---------- Builder ---------- */

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private Recipient recipient;
        private Address address;
        private ShippingMethod method;
        private Money cost;
        private String trackingNumber;
        private DeliveryStatus status = DeliveryStatus.PENDING_FULFILLMENT;
        private LocalDate estimatedDeliveryDate;
        private LocalDateTime createdAt;
        private LocalDateTime updatedAt;

        public Builder() { }

        private Builder(ShippingInfo copy) {
            this.recipient = copy.recipient;
            this.address = copy.address;
            this.method = copy.method;
            this.cost = copy.cost;
            this.trackingNumber = copy.trackingNumber;
            this.status = copy.status;
            this.estimatedDeliveryDate = copy.estimatedDeliveryDate;
            this.createdAt = copy.createdAt;
            this.updatedAt = copy.updatedAt;
        }

        public Builder recipient(Recipient recipient)                 { this.recipient = recipient; return this; }
        public Builder address(Address address)                       { this.address = address; return this; }
        public Builder method(ShippingMethod method)                  { this.method = method; return this; }
        public Builder cost(Money cost)                               { this.cost = cost; return this; }
        public Builder trackingNumber(String trackingNumber)          { this.trackingNumber = trackingNumber; return this; }
        public Builder status(DeliveryStatus status)                  { this.status = status; return this; }
        public Builder estimatedDeliveryDate(LocalDate date)          { this.estimatedDeliveryDate = date; return this; }
        public Builder createdAt(LocalDateTime createdAt)             { this.createdAt = createdAt; return this; }
        public Builder updatedAt(LocalDateTime updatedAt)             { this.updatedAt = updatedAt; return this; }

        public ShippingInfo build() { return new ShippingInfo(this); }
    }

    /* ---------- Enums ---------- */

    public enum ShippingMethod {
        STANDARD,
        EXPEDITED,
        OVERNIGHT,
        SAME_DAY,
        INTERNATIONAL
    }

    public enum DeliveryStatus {
        PENDING_FULFILLMENT,
        AWAITING_SHIPMENT,
        SHIPPED,
        IN_TRANSIT,
        OUT_FOR_DELIVERY,
        DELIVERED,
        RETURNED,
        CANCELED
    }

    /* ---------- Value Objects ---------- */

    /**
     * Recipient PII encapsulation—immutable and validated.
     */
    public static final class Recipient implements Serializable {
        private static final long serialVersionUID = 1L;
        private static final Pattern PHONE_PATTERN =
                Pattern.compile("^\\+?[0-9 .\\-]{7,20}$");

        private final String firstName;
        private final String lastName;
        private final String phone;

        public Recipient(String firstName, String lastName, String phone) {
            this.firstName = Objects.requireNonNull(firstName, "firstName").trim();
            this.lastName = Objects.requireNonNull(lastName, "lastName").trim();
            this.phone = Objects.requireNonNull(phone, "phone").trim();

            if (this.firstName.isBlank() || this.lastName.isBlank()) {
                throw new IllegalArgumentException("Names must not be blank");
            }
            if (!PHONE_PATTERN.matcher(this.phone).matches()) {
                throw new IllegalArgumentException("Invalid phone number format");
            }
        }

        public String fullName() { return firstName + " " + lastName; }

        public String getFirstName() { return firstName; }
        public String getLastName()  { return lastName;  }
        public String getPhone()     { return phone;     }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof Recipient that)) return false;
            return firstName.equalsIgnoreCase(that.firstName)
                    && lastName.equalsIgnoreCase(that.lastName)
                    && phone.equals(that.phone);
        }

        @Override
        public int hashCode() {
            return Objects.hash(firstName.toLowerCase(),
                    lastName.toLowerCase(), phone);
        }

        @Override
        public String toString() {
            return "Recipient{" +
                    "firstName='" + firstName + '\'' +
                    ", lastName='" + lastName + '\'' +
                    ", phone='" + MaskUtil.maskPhone(phone) + '\'' +
                    '}';
        }
    }

    /**
     * Immutable postal address.
     */
    public static final class Address implements Serializable {
        private static final long serialVersionUID = 1L;

        private final String line1;
        private final String line2;
        private final String city;
        private final String stateOrProvince;
        private final String postalCode;
        private final String countryCode;

        public Address(String line1,
                       String line2,
                       String city,
                       String stateOrProvince,
                       String postalCode,
                       String countryCode) {

            this.line1 = Objects.requireNonNull(line1, "line1").trim();
            this.line2 = line2 != null ? line2.trim() : null;
            this.city = Objects.requireNonNull(city, "city").trim();
            this.stateOrProvince = Objects.requireNonNull(stateOrProvince, "stateOrProvince").trim();
            this.postalCode = Objects.requireNonNull(postalCode, "postalCode").trim();
            this.countryCode = Objects.requireNonNull(countryCode, "countryCode").trim().toUpperCase();

            validate();
        }

        private void validate() {
            if (line1.isBlank() || city.isBlank() || stateOrProvince.isBlank()
                    || postalCode.isBlank() || countryCode.isBlank()) {
                throw new IllegalArgumentException("Address fields must not be blank");
            }
            if (countryCode.length() != 2) {
                throw new IllegalArgumentException("Country code must be ISO-3166 alpha-2");
            }
        }

        public String getLine1()          { return line1; }
        public String getLine2()          { return line2; }
        public String getCity()           { return city; }
        public String getStateOrProvince(){ return stateOrProvince; }
        public String getPostalCode()     { return postalCode; }
        public String getCountryCode()    { return countryCode; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof Address that)) return false;
            return line1.equalsIgnoreCase(that.line1)
                    && Objects.equals(line2, that.line2)
                    && city.equalsIgnoreCase(that.city)
                    && stateOrProvince.equalsIgnoreCase(that.stateOrProvince)
                    && postalCode.equalsIgnoreCase(that.postalCode)
                    && countryCode.equalsIgnoreCase(that.countryCode);
        }

        @Override
        public int hashCode() {
            return Objects.hash(line1.toLowerCase(), line2, city.toLowerCase(),
                    stateOrProvince.toLowerCase(), postalCode.toLowerCase(),
                    countryCode.toLowerCase());
        }

        @Override
        public String toString() {
            return "Address{" +
                    "line1='" + line1 + '\'' +
                    ", line2='" + line2 + '\'' +
                    ", city='" + city + '\'' +
                    ", stateOrProvince='" + stateOrProvince + '\'' +
                    ", postalCode='" + postalCode + '\'' +
                    ", countryCode='" + countryCode + '\'' +
                    '}';
        }
    }

    /**
     * Minimal Money implementation (amount + currency) with basic arithmetic.
     */
    public static final class Money
            implements Comparable<Money>, Serializable {

        private static final long serialVersionUID = 1L;

        private final BigDecimal amount;
        private final Currency currency;

        public Money(BigDecimal amount, Currency currency) {
            Objects.requireNonNull(amount, "amount");
            this.amount = amount.setScale(2, RoundingMode.HALF_EVEN);
            this.currency = Objects.requireNonNull(currency, "currency");
        }

        public BigDecimal getAmount() { return amount; }
        public Currency getCurrency() { return currency; }

        public Money add(Money other) {
            assertSameCurrency(other);
            return new Money(amount.add(other.amount), currency);
        }

        public Money subtract(Money other) {
            assertSameCurrency(other);
            return new Money(amount.subtract(other.amount), currency);
        }

        public Money multiply(int factor) {
            return new Money(amount.multiply(BigDecimal.valueOf(factor)), currency);
        }

        private void assertSameCurrency(Money other) {
            if (!currency.equals(other.currency)) {
                throw new IllegalArgumentException("Currency mismatch");
            }
        }

        @Override
        public int compareTo(Money other) {
            assertSameCurrency(other);
            return amount.compareTo(other.amount);
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof Money that)) return false;
            return amount.compareTo(that.amount) == 0
                    && currency.equals(that.currency);
        }

        @Override
        public int hashCode() {
            return Objects.hash(amount, currency);
        }

        @Override
        public String toString() {
            return currency.getCurrencyCode() + " " + amount;
        }
    }

    /* ---------- Internal helpers ---------- */

    /**
     * Utility functions for masking PII when logging.
     */
    static final class MaskUtil {
        private MaskUtil() { }

        static String maskPhone(String phone) {
            if (phone == null || phone.length() < 4) {
                return "****";
            }
            return "*".repeat(Math.max(0, phone.length() - 4))
                    + phone.substring(phone.length() - 4);
        }

        static String maskTracking(String tracking) {
            if (tracking == null || tracking.length() < 6) {
                return "******";
            }
            return tracking.substring(0, 3)
                    + "****"
                    + tracking.substring(tracking.length() - 3);
        }

        static String maskAddress(Address address) {
            if (address == null) return "N/A";
            return address.getLine1() + ", ****, " + address.getCity();
        }
    }
}