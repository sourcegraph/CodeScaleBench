package com.commercesphere.enterprise.user.dto;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import javax.validation.constraints.Email;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;
import java.io.Serial;
import java.io.Serializable;
import java.time.Instant;
import java.util.Collections;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/**
 * Immutable Data Transfer Object representing a system user.
 *
 * <p>Although DTOs are traditionally simple POJOs, this class performs
 * several additional validation and safety checks to guarantee that
 * downstream services never receive illegal state. The class is also
 * deliberately immutable so that it can be safely cached and shared
 * across threads without additional synchronization.</p>
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public final class UserDto implements Serializable {

    @Serial
    private static final long serialVersionUID = 976413762541254051L;

    // ---------------------------------------------------------------------
    // Core Domain Fields
    // ---------------------------------------------------------------------

    @NotNull
    private final UUID id;

    @NotBlank
    private final String username;

    @NotBlank
    @Email
    private final String email;

    @NotNull
    private final Set<String> roles;

    @NotNull
    private final AccountStatus status;

    private final Instant createdAt;

    private final Instant lastLoginAt;

    @JsonProperty("passwordInitialized")
    private final boolean passwordInitialized;

    // ---------------------------------------------------------------------
    // Constructors
    // ---------------------------------------------------------------------

    /**
     * Jackson/Builder aware constructor. Should not be called directly. Use
     * {@link Builder} instead for compile-time safety.
     */
    @JsonCreator
    private UserDto(
            @JsonProperty("id") UUID id,
            @JsonProperty("username") String username,
            @JsonProperty("email") String email,
            @JsonProperty("roles") Set<String> roles,
            @JsonProperty("status") AccountStatus status,
            @JsonProperty("createdAt") Instant createdAt,
            @JsonProperty("lastLoginAt") Instant lastLoginAt,
            @JsonProperty("passwordInitialized") boolean passwordInitialized) {

        // Defensive Copy & Validation
        this.id = Objects.requireNonNull(id, "id must not be null");
        this.username = sanitizeUsername(username);
        this.email = Objects.requireNonNull(email, "email must not be null");
        this.roles = Collections.unmodifiableSet(
                Objects.requireNonNull(roles, "roles must not be null"));
        this.status = Objects.requireNonNull(status, "status must not be null");
        this.createdAt = createdAt;
        this.lastLoginAt = lastLoginAt;
        this.passwordInitialized = passwordInitialized;
    }

    // ---------------------------------------------------------------------
    // Static Factory
    // ---------------------------------------------------------------------

    public static Builder builder() {
        return new Builder();
    }

    // ---------------------------------------------------------------------
    // Getters
    // ---------------------------------------------------------------------

    public UUID getId() {
        return id;
    }

    public String getUsername() {
        return username;
    }

    public String getEmail() {
        return email;
    }

    public Set<String> getRoles() {
        return roles;
    }

    public AccountStatus getStatus() {
        return status;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getLastLoginAt() {
        return lastLoginAt;
    }

    public boolean isPasswordInitialized() {
        return passwordInitialized;
    }

    // ---------------------------------------------------------------------
    // Helper / Convenience
    // ---------------------------------------------------------------------

    /**
     * Lazy helper method for tiered authorization checks performed
     * throughout the administrative module.
     */
    public boolean hasRole(String role) {
        return roles != null && roles.contains(role);
    }

    @JsonIgnore
    public boolean isActive() {
        return AccountStatus.ACTIVE.equals(status);
    }

    // ---------------------------------------------------------------------
    // Object Overrides
    // ---------------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof UserDto that)) return false;
        return Objects.equals(id, that.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    @Override
    public String toString() {
        return "UserDto{" +
               "id=" + id +
               ", username='" + username + '\'' +
               ", email='" + email + '\'' +
               ", roles=" + roles +
               ", status=" + status +
               ", createdAt=" + createdAt +
               ", lastLoginAt=" + lastLoginAt +
               ", passwordInitialized=" + passwordInitialized +
               '}';
    }

    // ---------------------------------------------------------------------
    // Builder
    // ---------------------------------------------------------------------

    public static final class Builder {

        private UUID id;
        private String username;
        private String email;
        private Set<String> roles = Collections.emptySet();
        private AccountStatus status = AccountStatus.PENDING_ACTIVATION;
        private Instant createdAt = Instant.now();
        private Instant lastLoginAt;
        private boolean passwordInitialized;

        private Builder() {
            // Package-private constructor to prevent undesired instantiation.
        }

        public Builder id(UUID id) {
            this.id = id;
            return this;
        }

        public Builder username(String username) {
            this.username = sanitizeUsername(username);
            return this;
        }

        public Builder email(String email) {
            this.email = email;
            return this;
        }

        public Builder roles(Set<String> roles) {
            if (roles != null) {
                this.roles = Set.copyOf(roles);
            }
            return this;
        }

        public Builder status(AccountStatus status) {
            this.status = status;
            return this;
        }

        public Builder createdAt(Instant createdAt) {
            this.createdAt = createdAt;
            return this;
        }

        public Builder lastLoginAt(Instant lastLoginAt) {
            this.lastLoginAt = lastLoginAt;
            return this;
        }

        public Builder passwordInitialized(boolean passwordInitialized) {
            this.passwordInitialized = passwordInitialized;
            return this;
        }

        /**
         * Performs final validation before constructing the immutable DTO.
         */
        public UserDto build() {
            Objects.requireNonNull(id, "user id must not be null");
            Objects.requireNonNull(username, "username must not be null");
            Objects.requireNonNull(email, "email must not be null");

            return new UserDto(
                    id,
                    username,
                    email,
                    roles,
                    status,
                    createdAt,
                    lastLoginAt,
                    passwordInitialized
            );
        }
    }

    // ---------------------------------------------------------------------
    // Internal Utility
    // ---------------------------------------------------------------------

    /**
     * Domain-specific username sanitization that trims whitespace and
     * converts to lower-case. Throws {@link IllegalArgumentException} if
     * the username is blank after trimming.
     */
    private static String sanitizeUsername(String raw) {
        if (raw == null) {
            throw new IllegalArgumentException("username cannot be null");
        }
        String sanitized = raw.trim().toLowerCase();
        if (sanitized.isEmpty()) {
            throw new IllegalArgumentException("username cannot be blank");
        }
        return sanitized;
    }

    // ---------------------------------------------------------------------
    // Nested Types
    // ---------------------------------------------------------------------

    public enum AccountStatus {
        ACTIVE,
        LOCKED,
        DISABLED,
        PENDING_ACTIVATION;

        /**
         * Provides compatibility for textual enum representation in JSON
         * payloads to remain forward-compatible with potential renames.
         */
        @JsonCreator
        public static AccountStatus fromString(String value) {
            for (AccountStatus status : values()) {
                if (status.name().equalsIgnoreCase(value)) {
                    return status;
                }
            }
            throw new IllegalArgumentException("Unknown account status: " + value);
        }
    }
}