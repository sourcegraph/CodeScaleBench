package com.commercesphere.enterprise.user.dto;

import java.io.Serial;
import java.io.Serializable;
import java.util.Arrays;
import java.util.Objects;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * Data-transfer object used by the authentication module to capture user-supplied
 * credentials from HTTP requests (JSON/XML/Form-URL-Encoded).
 *
 * <p>Security notice: the backing {@code password} is stored as a {@code char[]}
 * instead of an immutable {@link String} to allow explicit memory wiping after
 * authentication completes.  The {@link #clearSensitiveData()} method <em>must</em>
 * be invoked by callers once the DTO leaves the security boundary (e.g., controller
 * layer) to minimise the window in which the plaintext password resides in memory.</p>
 *
 * <p>The class is immutable except for the explicit wipe operation.</p>
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public final class LoginRequest implements Serializable {

    @Serial
    private static final long serialVersionUID = 5485725047454732473L;

    private static final int USERNAME_MIN = 3;
    private static final int USERNAME_MAX = 150;
    private static final int PASSWORD_MIN = 8;
    private static final int PASSWORD_MAX = 128;

    /**
     * Username or email address uniquely identifying the user.  The BE authentication
     * service is responsible for resolving the principal.
     */
    @NotBlank(message = "Username / email must be provided.")
    @Size(min = USERNAME_MIN, max = USERNAME_MAX,
          message = "Username / email length must be between {min} and {max} characters.")
    private final String principal;

    /**
     * Clear-text password as UTF-16 code units.  Sender MUST use HTTPS transport.
     */
    @NotBlank(message = "Password cannot be empty.")
    @Size(min = PASSWORD_MIN, max = PASSWORD_MAX,
          message = "Password length must be between {min} and {max} characters.")
    private final char[] password;

    /**
     * Optional device identifier used for MFA trust or risk analysis.
     */
    private final String deviceId;

    /**
     * Flag indicating if the authentication session should be persisted beyond the
     * current browser session (e.g., via long-lived refresh token or secure cookie).
     */
    private final boolean rememberMe;

    private LoginRequest(Builder builder) {
        this.principal   = builder.principal;
        this.password    = builder.password;
        this.deviceId    = builder.deviceId;
        this.rememberMe  = builder.rememberMe;
    }

    // -------------------------------------------------------------------------
    // Factory / builder helpers
    // -------------------------------------------------------------------------

    public static Builder builder() {
        return new Builder();
    }

    // -------------------------------------------------------------------------
    // Getters (note: password is intentionally not exposed via getter)
    // -------------------------------------------------------------------------

    /**
     * Returns the user’s principal (username or email).
     */
    public String getPrincipal() {
        return principal;
    }

    /**
     * Returns copy of password to prevent external mutation.
     */
    @JsonProperty("password")
    public char[] getPassword() {
        return password != null ? password.clone() : null;
    }

    /**
     * Optional device identifier, may be {@code null}.
     */
    public String getDeviceId() {
        return deviceId;
    }

    public boolean isRememberMe() {
        return rememberMe;
    }

    // -------------------------------------------------------------------------
    // Security
    // -------------------------------------------------------------------------

    /**
     * Overwrite the password array with zeros to reduce memory exposure.
     * Client code should call this <b>exactly once</b> after authentication
     * completes.
     */
    public void clearSensitiveData() {
        if (password != null) {
            Arrays.fill(password, '\0');
        }
    }

    /**
     * Password is intentionally excluded from {@code toString()} to avoid leaking
     * secrets into log files.
     */
    @Override
    public String toString() {
        return "LoginRequest{" +
               "principal='" + principal + '\'' +
               ", deviceId='" + deviceId + '\'' +
               ", rememberMe=" + rememberMe +
               '}';
    }

    /**
     * Equality is determined by principal only (not password) to allow look-ups
     * in cache structures keyed by user identity.
     */
    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof LoginRequest that)) return false;
        return Objects.equals(principal, that.principal);
    }

    @Override
    public int hashCode() {
        return Objects.hash(principal);
    }

    // -------------------------------------------------------------------------
    // Builder
    // -------------------------------------------------------------------------

    public static final class Builder {
        private String principal;
        private char[] password;
        private String deviceId;
        private boolean rememberMe;

        private Builder() {}

        public Builder withPrincipal(String principal) {
            this.principal = principal;
            return this;
        }

        public Builder withPassword(char[] password) {
            // Clone to maintain immutability of passed-in reference
            this.password = password != null ? password.clone() : null;
            return this;
        }

        public Builder withPassword(String password) {
            this.password = password != null ? password.toCharArray() : null;
            return this;
        }

        public Builder withDeviceId(String deviceId) {
            this.deviceId = deviceId;
            return this;
        }

        public Builder rememberMe(boolean rememberMe) {
            this.rememberMe = rememberMe;
            return this;
        }

        /**
         * Builds the immutable {@link LoginRequest} instance, validating required
         * fields for non-nullity. Bean-validation (JSR-380) annotations will handle
         * further constraints downstream.
         *
         * @throws IllegalStateException if mandatory properties are missing
         */
        public LoginRequest build() {
            if (principal == null || principal.isBlank()) {
                throw new IllegalStateException("principal must be provided");
            }
            if (password == null || password.length == 0) {
                throw new IllegalStateException("password must be provided");
            }
            return new LoginRequest(this);
        }
    }

    // -------------------------------------------------------------------------
    // Jackson helper to ignore raw password during serialisation
    // -------------------------------------------------------------------------

    @JsonIgnore
    public String getObfuscatedPassword() {
        return password == null ? null : "********";
    }
}