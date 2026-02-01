```java
package com.commercesphere.enterprise.user.model;

import javax.persistence.CascadeType;
import javax.persistence.Column;
import javax.persistence.ElementCollection;
import javax.persistence.Entity;
import javax.persistence.EntityListeners;
import javax.persistence.FetchType;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.persistence.JoinColumn;
import javax.persistence.JoinTable;
import javax.persistence.ManyToMany;
import javax.persistence.SequenceGenerator;
import javax.persistence.Table;
import javax.persistence.UniqueConstraint;
import javax.validation.constraints.Email;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.Size;
import java.io.Serial;
import java.io.Serializable;
import java.time.Instant;
import java.util.Collections;
import java.util.HashSet;
import java.util.Objects;
import java.util.Set;

import org.springframework.data.annotation.CreatedDate;
import org.springframework.data.annotation.LastModifiedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

/**
 * Persisted representation of a platform user.
 * <p>
 * The User record drives authentication and access-control.  Passwords are
 * salted and hashed via BCrypt and never returned in serialization views.
 * <p>
 * Note: Because the CommerceSphere suite runs in a single JVM, we can afford
 * direct calls to the domain without additional network hops—hence methods like
 * {@link #matchesPassword(CharSequence)} exist on the aggregate itself.
 */
@Entity
@Table(
        name = "cs_user",
        uniqueConstraints = {
                @UniqueConstraint(name = "uc_user_username", columnNames = "username"),
                @UniqueConstraint(name = "uc_user_email", columnNames = "email")
        }
)
@EntityListeners(AuditingEntityListener.class)
public class User implements Serializable {

    @Serial
    private static final long serialVersionUID = 3715513852789456021L;

    private static final BCryptPasswordEncoder PASSWORD_ENCODER = new BCryptPasswordEncoder(12);

    /* ---------- Primary Key & Versioning ---------- */

    @Id
    @GeneratedValue(strategy = GenerationType.SEQUENCE, generator = "user_seq_gen")
    @SequenceGenerator(name = "user_seq_gen", sequenceName = "seq_cs_user", allocationSize = 50)
    @Column(name = "id", nullable = false, updatable = false)
    private Long id;

    @CreatedDate
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @LastModifiedDate
    @Column(name = "updated_at")
    private Instant updatedAt;

    /* ---------- Identity & Credentials ---------- */

    @NotBlank
    @Size(max = 60)
    @Column(name = "username", nullable = false, length = 60, updatable = false)
    private String username;

    @NotBlank
    @Email
    @Size(max = 254)
    @Column(name = "email", nullable = false, length = 254)
    private String email;

    /**
     * BCrypt hashed password.  Never expose this field on any outbound DTO.
     */
    @Column(name = "password_hash", nullable = false, length = 60)
    private String passwordHash;

    @Column(name = "password_changed_at", nullable = false)
    private Instant passwordChangedAt;

    /* ---------- Profile Details ---------- */

    @NotBlank
    @Size(max = 50)
    @Column(name = "first_name", nullable = false, length = 50)
    private String firstName;

    @NotBlank
    @Size(max = 50)
    @Column(name = "last_name", nullable = false, length = 50)
    private String lastName;

    /* ---------- Account State ---------- */

    @Column(name = "enabled", nullable = false)
    private boolean enabled = true;

    @Column(name = "locked", nullable = false)
    private boolean locked = false;

    @Column(name = "last_login_at")
    private Instant lastLoginAt;

    /* ---------- Role Mapping ---------- */

    @ManyToMany(fetch = FetchType.LAZY, cascade = {CascadeType.MERGE})
    @JoinTable(
            name = "cs_user_role",
            joinColumns = @JoinColumn(name = "user_id", referencedColumnName = "id", nullable = false),
            inverseJoinColumns = @JoinColumn(name = "role_id", referencedColumnName = "id", nullable = false)
    )
    private Set<Role> roles = new HashSet<>();

    /* ---------- Constructors ---------- */

    protected User() {
        /* Required by JPA */
    }

    private User(Builder builder) {
        this.username = normalize(builder.username);
        this.email = normalize(builder.email);
        this.firstName = builder.firstName;
        this.lastName = builder.lastName;
        this.enabled = builder.enabled;
        this.locked = builder.locked;
        setPassword(builder.rawPassword);
        setRoles(builder.roles);
    }

    /* ---------- Static Factory ---------- */

    public static Builder builder(String username, String email) {
        return new Builder(username, email);
    }

    /* ---------- Public Business Methods ---------- */

    /**
     * Hashes and sets the password.  Raw password char array is wiped after use.
     *
     * @param rawPassword plaintext password
     * @throws IllegalArgumentException if rawPassword is null or too short
     */
    public void setPassword(char[] rawPassword) {
        if (rawPassword == null || rawPassword.length < 8) {
            throw new IllegalArgumentException("Password must be at least 8 characters long.");
        }
        this.passwordHash = PASSWORD_ENCODER.encode(new String(rawPassword));
        this.passwordChangedAt = Instant.now();
        // wipe secret from memory
        for (int i = 0; i < rawPassword.length; i++) {
            rawPassword[i] = 0;
        }
    }

    /**
     * Performs constant-time password comparison.
     */
    public boolean matchesPassword(CharSequence rawPassword) {
        return PASSWORD_ENCODER.matches(rawPassword, this.passwordHash);
    }

    public void enable() {
        this.enabled = true;
        this.locked = false;
    }

    public void disable() {
        this.enabled = false;
    }

    public void lock() {
        this.locked = true;
    }

    public void unlock() {
        this.locked = false;
    }

    public void touchLoginTimestamp() {
        this.lastLoginAt = Instant.now();
    }

    /* ---------- Role Helpers ---------- */

    public boolean addRole(Role role) {
        Objects.requireNonNull(role, "Role cannot be null");
        return this.roles.add(role);
    }

    public boolean removeRole(Role role) {
        Objects.requireNonNull(role, "Role cannot be null");
        return this.roles.remove(role);
    }

    public boolean hasRole(String roleCode) {
        return roles.stream().anyMatch(r -> r.getCode().equalsIgnoreCase(roleCode));
    }

    /* ---------- Getters ---------- */

    public Long getId() {
        return id;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public String getUsername() {
        return username;
    }

    public String getEmail() {
        return email;
    }

    /**
     * This getter purposefully omits returning passwordHash to calling code.
     * To verify authentication, call {@link #matchesPassword(CharSequence)}.
     */
    private String getPasswordHash() {
        return passwordHash;
    }

    public Instant getPasswordChangedAt() {
        return passwordChangedAt;
    }

    public String getFirstName() {
        return firstName;
    }

    public String getLastName() {
        return lastName;
    }

    public boolean isEnabled() {
        return enabled;
    }

    public boolean isLocked() {
        return locked;
    }

    public Instant getLastLoginAt() {
        return lastLoginAt;
    }

    public Set<Role> getRoles() {
        return Collections.unmodifiableSet(roles);
    }

    /* ---------- Mutating Helpers ---------- */

    private void setRoles(Set<Role> roles) {
        if (roles != null) {
            this.roles = new HashSet<>(roles);
        }
    }

    /* ---------- Utility ---------- */

    private static String normalize(String s) {
        return s == null ? null : s.trim().toLowerCase();
    }

    /* ---------- Equality & Hashing ---------- */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof User user)) return false;
        return Objects.equals(id, user.id) &&
               Objects.equals(username, user.username);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, username);
    }

    /* ---------- Builder ---------- */

    public static final class Builder {
        private final String username;
        private final String email;
        private char[] rawPassword = "ChangeMeNow!".toCharArray();
        private String firstName = "N/A";
        private String lastName = "N/A";
        private boolean enabled = true;
        private boolean locked;
        private Set<Role> roles = new HashSet<>();

        private Builder(String username, String email) {
            this.username = Objects.requireNonNull(username, "username cannot be null");
            this.email = Objects.requireNonNull(email, "email cannot be null");
        }

        public Builder password(char[] rawPassword) {
            this.rawPassword = Objects.requireNonNull(rawPassword, "password cannot be null");
            return this;
        }

        public Builder firstName(String firstName) {
            this.firstName = Objects.requireNonNull(firstName, "firstName cannot be null");
            return this;
        }

        public Builder lastName(String lastName) {
            this.lastName = Objects.requireNonNull(lastName, "lastName cannot be null");
            return this;
        }

        public Builder enabled(boolean enabled) {
            this.enabled = enabled;
            return this;
        }

        public Builder locked(boolean locked) {
            this.locked = locked;
            return this;
        }

        public Builder roles(Set<Role> roles) {
            this.roles = Objects.requireNonNull(roles, "roles cannot be null");
            return this;
        }

        public User build() {
            return new User(this);
        }
    }

}
```