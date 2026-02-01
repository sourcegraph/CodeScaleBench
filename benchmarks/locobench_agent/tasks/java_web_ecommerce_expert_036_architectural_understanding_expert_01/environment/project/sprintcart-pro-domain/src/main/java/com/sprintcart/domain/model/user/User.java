package com.sprintcart.domain.model.user;

import java.io.Serial;
import java.io.Serializable;
import java.time.Instant;
import java.util.Collections;
import java.util.EnumSet;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/**
 * Aggregate root representing a platform user (merchant operator, admin, etc.).
 *
 * <p>NOTE: This class purposefully avoids any persistence-specific annotations (e.g. JPA)
 * to keep the domain model free of infrastructure concerns in accordance with
 * Hexagonal Architecture.</p>
 */
public class User implements Serializable {

    @Serial
    private static final long serialVersionUID = -6546893916985479904L;

    /* ------------- Core State ------------- */

    private final UserId      id;
    private Email             email;
    private String            displayName;
    private PasswordHash      passwordHash;
    private EnumSet<Role>     roles;
    private boolean           locked;
    private Instant           createdAt;
    private Instant           updatedAt;
    private long              version;

    /* ------------- Constructors ------------- */

    private User(UserId id,
                 Email email,
                 String displayName,
                 PasswordHash passwordHash,
                 EnumSet<Role> roles,
                 boolean locked,
                 Instant createdAt,
                 Instant updatedAt,
                 long version) {

        this.id           = id;
        this.email        = email;
        this.displayName  = displayName;
        this.passwordHash = passwordHash;
        this.roles        = roles.clone();         // defensive copy
        this.locked       = locked;
        this.createdAt    = createdAt;
        this.updatedAt    = updatedAt;
        this.version      = version;
    }

    /* ------------- Factory Methods ------------- */

    /**
     * Creates a new user instance that will be persisted later via a repository.
     *
     * @throws IllegalArgumentException when any argument is invalid
     */
    public static User newUser(String email,
                               String displayName,
                               String rawPassword,
                               Set<Role> initialRoles) {

        Objects.requireNonNull(email, "email must not be null");
        Objects.requireNonNull(rawPassword, "password must not be null");
        Objects.requireNonNull(displayName, "displayName must not be null");

        EnumSet<Role> roles = (initialRoles == null || initialRoles.isEmpty())
                              ? EnumSet.of(Role.MERCHANT_OPERATOR)
                              : EnumSet.copyOf(initialRoles);

        Instant now = Instant.now();

        return new User(
                UserId.random(),
                new Email(email),
                displayName.trim(),
                PasswordHash.fromRaw(rawPassword),
                roles,
                false,
                now,
                now,
                0L
        );
    }

    /* ------------- Behaviour ------------- */

    /**
     * Change the user password.
     *
     * @param currentRawPassword current password in plain text
     * @param newRawPassword     new password in plain text
     */
    public void changePassword(String currentRawPassword, String newRawPassword) {
        requireNotLocked();
        if (!passwordHash.matches(currentRawPassword)) {
            throw new DomainException("Current password does not match");
        }
        passwordHash = PasswordHash.fromRaw(newRawPassword);
        touch();
    }

    /**
     * Update the user profile (e.g. email or display name).
     */
    public void updateProfile(String newEmail, String newDisplayName) {
        requireNotLocked();
        boolean changed = false;

        if (newEmail != null && !email.equals(new Email(newEmail))) {
            email = new Email(newEmail);
            changed = true;
        }
        if (newDisplayName != null && !displayName.equals(newDisplayName.trim())) {
            displayName = newDisplayName.trim();
            changed = true;
        }
        if (changed) {
            touch();
        }
    }

    /**
     * Lock the account (e.g. when too many failed logins or manual admin action).
     */
    public void lock() {
        if (!locked) {
            locked = true;
            touch();
        }
    }

    /**
     * Unlock the account.
     */
    public void unlock() {
        if (locked) {
            locked = false;
            touch();
        }
    }

    /**
     * Grants a role to the user.
     */
    public void grantRole(Role role) {
        requireNotLocked();
        if (roles.add(role)) {
            touch();
        }
    }

    /**
     * Revokes a role from the user.
     */
    public void revokeRole(Role role) {
        requireNotLocked();
        if (roles.remove(role)) {
            touch();
        }
    }

    private void requireNotLocked() {
        if (locked) {
            throw new DomainException("User is locked: " + id);
        }
    }

    private void touch() {
        updatedAt = Instant.now();
        version++;
    }

    /* ------------- Read-only Getters ------------- */

    public UserId getId() {
        return id;
    }

    public Email getEmail() {
        return email;
    }

    public String getDisplayName() {
        return displayName;
    }

    public Set<Role> getRoles() {
        return Collections.unmodifiableSet(roles);
    }

    public boolean isLocked() {
        return locked;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public long getVersion() {
        return version;
    }

    /* ------------- Equality & HashCode ------------- */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof User other)) return false;
        return id.equals(other.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    /* ------------- Value Objects ------------- */

    /**
     * Technical identifier for {@link User} aggregate.
     */
    public record UserId(UUID value) implements Serializable {
        @Serial private static final long serialVersionUID = 6735226725472135722L;

        public UserId {
            Objects.requireNonNull(value, "UserId value must not be null");
        }

        public static UserId random() {
            return new UserId(UUID.randomUUID());
        }

        @Override
        public String toString() { return value.toString(); }
    }

    /**
     * Value object encapsulating email validation concerns.
     */
    public static final class Email implements Serializable {

        @Serial private static final long serialVersionUID = 6602434499815041701L;

        private static final String RFC_5322_SIMPLE =
                "^(?:[a-zA-Z0-9_'^&/+-])+(?:\\.(?:[a-zA-Z0-9_'^&/+-])+)*@"
              + "(?:[a-zA-Z0-9-]+\\.)+[a-zA-Z]{2,}$";

        private final String value;

        public Email(String raw) {
            Objects.requireNonNull(raw, "Email must not be null");
            String normalized = raw.trim().toLowerCase();
            if (!normalized.matches(RFC_5322_SIMPLE)) {
                throw new DomainException("Invalid email: " + raw);
            }
            this.value = normalized;
        }

        public String value() {
            return value;
        }

        @Override
        public String toString() { return value; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof Email other)) return false;
            return value.equals(other.value);
        }

        @Override
        public int hashCode() {
            return Objects.hash(value);
        }
    }

    /**
     * Encapsulates password hashing and matching logic.
     *
     * <p>The actual algorithm is delegated to {@link PasswordHasher} strategy.
     * Keeping the hash inside the domain model lets us enforce parity between
     * authentication and business invariants (e.g. password rotation policy).</p>
     */
    public static final class PasswordHash implements Serializable {

        @Serial private static final long serialVersionUID = 2279919373919828871L;

        private final String hashed;

        private PasswordHash(String hashed) {
            this.hashed = hashed;
        }

        public static PasswordHash fromRaw(String rawPassword) {
            Objects.requireNonNull(rawPassword, "password must not be null");
            if (rawPassword.length() < 8) {
                throw new DomainException("Password too short (min 8 chars)");
            }
            String hash = PasswordHasher.DEFAULT.hash(rawPassword);
            return new PasswordHash(hash);
        }

        public boolean matches(String rawAttempt) {
            return PasswordHasher.DEFAULT.verify(rawAttempt, hashed);
        }

        public String value() { return hashed; }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof PasswordHash other)) return false;
            return hashed.equals(other.hashed);
        }

        @Override
        public int hashCode() {
            return Objects.hash(hashed);
        }
    }

    /**
     * Strategy interface (simple placeholder) for hashing algorithms.
     * Infra layer is expected to supply a concrete implementation (e.g. BCrypt).
     */
    public interface PasswordHasher {

        PasswordHasher DEFAULT = new BcryptHasher();

        String hash(String raw);

        boolean verify(String raw, String hashed);

        /* Default implementation for demonstration purposes. */
        class BcryptHasher implements PasswordHasher {
            @Override
            public String hash(String raw) {
                // In production, delegate to a real BCrypt implementation.
                // Here, we just simulate with a basic reversible scheme
                // to avoid adding heavy dependencies to the domain layer.
                return "$bcrypt$" + new StringBuilder(raw).reverse();
            }

            @Override
            public boolean verify(String raw, String hashed) {
                return Objects.equals(hash(raw), hashed);
            }
        }
    }

    /* ------------- Domain Enum Types ------------- */

    public enum Role {
        ADMIN,
        MERCHANT_OPERATOR,
        FULFILLMENT_AGENT,
        FINANCE,
        CUSTOMER_SUPPORT
    }

    /* ------------- Domain Exception ------------- */

    public static class DomainException extends RuntimeException {
        @Serial private static final long serialVersionUID = -328748306588660254L;

        public DomainException(String message) {
            super(message);
        }
    }
}