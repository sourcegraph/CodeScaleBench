package com.sprintcart.domain.model.user;

import java.io.Serial;
import java.io.Serializable;
import java.time.Clock;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.function.UnaryOperator;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;

import com.sprintcart.domain.common.event.DomainEvent;
import com.sprintcart.domain.common.event.DomainEventRecorder;
import com.sprintcart.domain.common.vo.CustomerId;
import com.sprintcart.domain.common.vo.EmailAddress;
import com.sprintcart.domain.common.vo.PhoneNumber;
import com.sprintcart.domain.model.common.Address;

/**
 * CustomerProfile is the aggregate root that captures all user–specific data
 * used throughout the checkout, fulfillment, and engagement pipelines.
 *
 * Domain invariants:
 *  • Each profile is uniquely identified by {@link CustomerId}.
 *  • Email must be unique in the system (enforced at a higher layer).
 *  • Loyalty points can never be negative.
 *
 * This class is intentionally persistence-agnostic; mapping annotations live in
 * an infrastructure adapter so that the core domain stays free of framework
 * concerns.
 */
public final class CustomerProfile implements DomainEventRecorder, Serializable {

    @Serial
    private static final long serialVersionUID = 34298742987342L;

    public enum LoyaltyTier {
        NEWBIE,
        BRONZE,
        SILVER,
        GOLD,
        PLATINUM;

        public static LoyaltyTier fromPoints(final int points) {
            if (points >= 10_000) return PLATINUM;
            if (points >= 5_000) return GOLD;
            if (points >= 2_000) return SILVER;
            if (points >= 1_000) return BRONZE;
            return NEWBIE;
        }
    }

    // -----------------------------------------------------------------------
    // Core Identifiers
    // -----------------------------------------------------------------------

    @NotNull
    private final CustomerId id;

    // -----------------------------------------------------------------------
    // Personal details
    // -----------------------------------------------------------------------

    @NotBlank
    private String firstName;

    @NotBlank
    private String lastName;

    @NotNull
    private EmailAddress email;

    private PhoneNumber phoneNumber;

    // -----------------------------------------------------------------------
    // Addresses (shipping / billing)
    // -----------------------------------------------------------------------

    @NotEmpty
    private final List<Address> addresses = new ArrayList<>();

    /**
     * Index into {@link #addresses} designating the default shipping address.
     * A value of {@code -1} indicates "unset".
     */
    private int defaultShippingIndex = -1;

    /**
     * Index into {@link #addresses} designating the default billing address.
     * A value of {@code -1} indicates "unset".
     */
    private int defaultBillingIndex = -1;

    // -----------------------------------------------------------------------
    // Preferences and Meta
    // -----------------------------------------------------------------------

    private final Map<String, String> traits = new LinkedHashMap<>();

    @Min(0)
    private int loyaltyPoints;

    private LoyaltyTier loyaltyTier;

    @NotNull
    private ZonedDateTime createdAt;

    @NotNull
    private ZonedDateTime updatedAt;

    /**
     * Version used for optimistic concurrency in an eventual persistence layer.
     */
    private long version;

    // -----------------------------------------------------------------------
    // Domain Event Buffer
    // -----------------------------------------------------------------------

    private transient List<DomainEvent> domainEvents = new ArrayList<>();

    // -----------------------------------------------------------------------
    // Constructors / Factories
    // -----------------------------------------------------------------------

    private CustomerProfile(
            final CustomerId id,
            final String firstName,
            final String lastName,
            final EmailAddress email,
            final PhoneNumber phoneNumber,
            final Clock clock
    ) {
        this.id = Objects.requireNonNull(id, "id");
        this.firstName = requireNonBlank(firstName, "firstName");
        this.lastName = requireNonBlank(lastName, "lastName");
        this.email = Objects.requireNonNull(email, "email");
        this.phoneNumber = phoneNumber;

        this.createdAt  = ZonedDateTime.now(clock);
        this.updatedAt  = this.createdAt;
        this.loyaltyTier = LoyaltyTier.NEWBIE;
    }

    public static CustomerProfile create(
            final CustomerId id,
            final String firstName,
            final String lastName,
            final EmailAddress email,
            final PhoneNumber phoneNumber,
            final Clock clock
    ) {
        final CustomerProfile profile = new CustomerProfile(
                id,
                firstName,
                lastName,
                email,
                phoneNumber,
                clock
        );

        profile.recordEvent(new CustomerRegisteredEvent(id, profile.createdAt));
        return profile;
    }

    // -----------------------------------------------------------------------
    // Domain Operations
    // -----------------------------------------------------------------------

    public void changeEmail(final EmailAddress newEmail) {
        Objects.requireNonNull(newEmail, "newEmail");
        if (this.email.equals(newEmail)) {
            return; // NO-OP
        }

        final EmailAddress old = this.email;
        this.email = newEmail;
        touch();
        recordEvent(new CustomerEmailChangedEvent(id, old, newEmail, updatedAt));
    }

    public void changePhoneNumber(final PhoneNumber newPhoneNumber) {
        this.phoneNumber = newPhoneNumber;
        touch();
        recordEvent(new CustomerPhoneChangedEvent(id, newPhoneNumber, updatedAt));
    }

    public void changeName(final String newFirstName, final String newLastName) {
        boolean changed = false;

        if (!this.firstName.equals(requireNonBlank(newFirstName, "newFirstName"))) {
            this.firstName = newFirstName;
            changed = true;
        }

        if (!this.lastName.equals(requireNonBlank(newLastName, "newLastName"))) {
            this.lastName = newLastName;
            changed = true;
        }

        if (changed) {
            touch();
            recordEvent(new CustomerNameChangedEvent(id, firstName, lastName, updatedAt));
        }
    }

    // -----------------------------------------------------------------------
    // Address Management
    // -----------------------------------------------------------------------

    public void addAddress(final Address address, final boolean setAsDefaultShipping, final boolean setAsDefaultBilling) {
        Objects.requireNonNull(address, "address");
        addresses.add(address);

        if (setAsDefaultShipping) {
            defaultShippingIndex = addresses.size() - 1;
        }
        if (setAsDefaultBilling) {
            defaultBillingIndex = addresses.size() - 1;
        }

        touch();
        recordEvent(new CustomerAddressAddedEvent(id, address, updatedAt));
    }

    public void updateAddress(final int index, final UnaryOperator<Address> mutator) {
        if (index < 0 || index >= addresses.size()) {
            throw new IndexOutOfBoundsException("Address index out of bounds: " + index);
        }

        final Address oldAddress = addresses.get(index);
        final Address newAddress = mutator.apply(oldAddress);

        if (!oldAddress.equals(newAddress)) {
            addresses.set(index, newAddress);
            touch();
            recordEvent(new CustomerAddressUpdatedEvent(id, oldAddress, newAddress, updatedAt));
        }
    }

    public void removeAddress(final int index) {
        if (index < 0 || index >= addresses.size()) {
            throw new IndexOutOfBoundsException("Address index out of bounds: " + index);
        }

        final Address removed = addresses.remove(index);

        // Adjust default indices if needed
        if (defaultShippingIndex == index) defaultShippingIndex = -1;
        if (defaultBillingIndex == index)  defaultBillingIndex  = -1;

        if (defaultShippingIndex > index) defaultShippingIndex--;
        if (defaultBillingIndex  > index) defaultBillingIndex--;

        touch();
        recordEvent(new CustomerAddressRemovedEvent(id, removed, updatedAt));
    }

    public Optional<Address> getDefaultShippingAddress() {
        return defaultShippingIndex >= 0 ? Optional.of(addresses.get(defaultShippingIndex)) : Optional.empty();
    }

    public Optional<Address> getDefaultBillingAddress() {
        return defaultBillingIndex >= 0 ? Optional.of(addresses.get(defaultBillingIndex)) : Optional.empty();
    }

    public List<Address> getAddresses() {
        return Collections.unmodifiableList(addresses);
    }

    // -----------------------------------------------------------------------
    // Loyalty & Traits
    // -----------------------------------------------------------------------

    public void addLoyaltyPoints(final int points) {
        if (points <= 0) {
            throw new IllegalArgumentException("points must be positive");
        }

        this.loyaltyPoints += points;
        final LoyaltyTier oldTier = loyaltyTier;
        this.loyaltyTier = LoyaltyTier.fromPoints(loyaltyPoints);

        touch();
        recordEvent(new LoyaltyPointsAddedEvent(id, points, loyaltyPoints, updatedAt));

        if (!oldTier.equals(loyaltyTier)) {
            recordEvent(new LoyaltyTierUpgradedEvent(id, oldTier, loyaltyTier, updatedAt));
        }
    }

    public void setTrait(final String key, final String value) {
        Objects.requireNonNull(key, "key");
        Objects.requireNonNull(value, "value");
        traits.put(key, value);
        touch();
    }

    public Optional<String> getTrait(final String key) {
        return Optional.ofNullable(traits.get(key));
    }

    public Map<String, String> getTraits() {
        return Collections.unmodifiableMap(traits);
    }

    // -----------------------------------------------------------------------
    // Getters
    // -----------------------------------------------------------------------

    public CustomerId getId() {
        return id;
    }

    public String getFirstName() {
        return firstName;
    }

    public String getLastName() {
        return lastName;
    }

    public EmailAddress getEmail() {
        return email;
    }

    public PhoneNumber getPhoneNumber() {
        return phoneNumber;
    }

    public int getLoyaltyPoints() {
        return loyaltyPoints;
    }

    public LoyaltyTier getLoyaltyTier() {
        return loyaltyTier;
    }

    public ZonedDateTime getCreatedAt() {
        return createdAt;
    }

    public ZonedDateTime getUpdatedAt() {
        return updatedAt;
    }

    public long getVersion() {
        return version;
    }

    // -----------------------------------------------------------------------
    // Domain Event Recorder
    // -----------------------------------------------------------------------

    @Override
    public List<DomainEvent> pullEvents() {
        final List<DomainEvent> snapshot = domainEvents;
        domainEvents = new ArrayList<>();
        return snapshot;
    }

    private void recordEvent(final DomainEvent event) {
        domainEvents.add(event);
    }

    // -----------------------------------------------------------------------
    // Internal Helpers
    // -----------------------------------------------------------------------

    private void touch() {
        this.updatedAt = ZonedDateTime.now();
        this.version++;
    }

    private static String requireNonBlank(final String value, final String fieldName) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(fieldName + " must not be blank");
        }
        return value;
    }

    // -----------------------------------------------------------------------
    // Equality / HashCode
    // -----------------------------------------------------------------------

    @Override
    public boolean equals(final Object o) {
        if (this == o) return true;
        if (!(o instanceof CustomerProfile that)) return false;
        return id.equals(that.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    // -----------------------------------------------------------------------
    // String representation (for logging only)
    // -----------------------------------------------------------------------

    @Override
    public String toString() {
        return "CustomerProfile{" +
               "id=" + id +
               ", email=" + email +
               ", loyaltyTier=" + loyaltyTier +
               ", createdAt=" + createdAt +
               ", updatedAt=" + updatedAt +
               '}';
    }

    // -----------------------------------------------------------------------
    // Domain Events
    // -----------------------------------------------------------------------

    public record CustomerRegisteredEvent(
            CustomerId customerId,
            ZonedDateTime occurredAt
    ) implements DomainEvent {}

    public record CustomerEmailChangedEvent(
            CustomerId customerId,
            EmailAddress oldEmail,
            EmailAddress newEmail,
            ZonedDateTime occurredAt
    ) implements DomainEvent {}

    public record CustomerPhoneChangedEvent(
            CustomerId customerId,
            PhoneNumber newPhoneNumber,
            ZonedDateTime occurredAt
    ) implements DomainEvent {}

    public record CustomerNameChangedEvent(
            CustomerId customerId,
            String firstName,
            String lastName,
            ZonedDateTime occurredAt
    ) implements DomainEvent {}

    public record CustomerAddressAddedEvent(
            CustomerId customerId,
            Address address,
            ZonedDateTime occurredAt
    ) implements DomainEvent {}

    public record CustomerAddressUpdatedEvent(
            CustomerId customerId,
            Address oldAddress,
            Address newAddress,
            ZonedDateTime occurredAt
    ) implements DomainEvent {}

    public record CustomerAddressRemovedEvent(
            CustomerId customerId,
            Address address,
            ZonedDateTime occurredAt
    ) implements DomainEvent {}

    public record LoyaltyPointsAddedEvent(
            CustomerId customerId,
            int added,
            int totalPoints,
            ZonedDateTime occurredAt
    ) implements DomainEvent {}

    public record LoyaltyTierUpgradedEvent(
            CustomerId customerId,
            LoyaltyTier oldTier,
            LoyaltyTier newTier,
            ZonedDateTime occurredAt
    ) implements DomainEvent {}
}