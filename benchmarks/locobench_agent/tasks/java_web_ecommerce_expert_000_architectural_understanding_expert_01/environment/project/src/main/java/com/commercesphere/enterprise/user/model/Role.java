```java
package com.commercesphere.enterprise.user.model;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.persistence.CascadeType;
import jakarta.persistence.CollectionTable;
import jakarta.persistence.Column;
import jakarta.persistence.ElementCollection;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import jakarta.persistence.Version;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.io.Serial;
import java.io.Serializable;
import java.time.Instant;
import java.util.Collections;
import java.util.EnumSet;
import java.util.Objects;
import java.util.Set;

/**
 * Domain aggregate representing a role within the B2B account hierarchy.
 * <p>
 * This entity is mapped by JPA and can be used by both 
 * the internal authorization framework and the REST API layer.
 */
@Entity
@Table(
    name = "cs_roles",
    uniqueConstraints = {
        @UniqueConstraint(name = "uq_cs_roles_name", columnNames = {"name"})
    }
)
public class Role implements Serializable {

    @Serial
    private static final long serialVersionUID = 3750947086839112891L;

    // ------------------------------------------------------------------------
    // JPA columns
    // ------------------------------------------------------------------------

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * Human-readable role name (e.g., "ACCOUNT_ADMIN", "SALES_REP").
     */
    @Column(nullable = false, length = 50)
    private String name;

    /**
     * Optional free-text description provided by administrators. 
     */
    @Column(length = 255)
    private String description;

    /**
     * Role permissions are stored as an eager element collection. 
     * ElementCollection is chosen because Permission is an enum 
     * and does not need its own lifecycle.
     */
    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(
        name = "cs_role_permissions",
        joinColumns = @JoinColumn(name = "role_id", referencedColumnName = "id"),
        // cascade removed to prevent accidental delete of role from cleaning up permissions shared in memory.
        // This ensures deliberate delete only.
        foreignKey = @jakarta.persistence.ForeignKey(name = "fk_role_permissions_role")
    )
    @Column(name = "permission", nullable = false, length = 75)
    @Enumerated(EnumType.STRING)
    private Set<Permission> permissions = EnumSet.noneOf(Permission.class);

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private Instant updatedAt;

    @Version
    @JsonIgnore
    private Long version;

    // ------------------------------------------------------------------------
    // Constructors
    // ------------------------------------------------------------------------

    protected Role() {
        /* JPA spec requires non-private no-arg constructor */
    }

    public Role(String name, String description, Set<Permission> permissions) {
        setName(name);
        setDescription(description);
        if (permissions != null) {
            this.permissions = EnumSet.copyOf(permissions);
        }
    }

    // ------------------------------------------------------------------------
    // Domain behavior
    // ------------------------------------------------------------------------

    public void addPermission(Permission permission) {
        Objects.requireNonNull(permission, "permission");
        permissions.add(permission);
    }

    public void addPermissions(Set<Permission> permissions) {
        Objects.requireNonNull(permissions, "permissions");
        this.permissions.addAll(permissions);
    }

    public void removePermission(Permission permission) {
        Objects.requireNonNull(permission, "permission");
        permissions.remove(permission);
    }

    public boolean hasPermission(Permission permission) {
        Objects.requireNonNull(permission, "permission");
        return permissions.contains(permission);
    }

    // ------------------------------------------------------------------------
    // Accessors
    // ------------------------------------------------------------------------

    public Long getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("Role.name cannot be null/blank");
        }
        this.name = name.trim().toUpperCase(); // canonical form
    }

    public String getDescription() {
        return description;
    }

    public void setDescription(String description) {
        this.description = description != null ? description.trim() : null;
    }

    @JsonProperty("permissions")
    public Set<Permission> getPermissions() {
        return Collections.unmodifiableSet(permissions);
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    // ------------------------------------------------------------------------
    // Technical overrides
    // ------------------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        // For Hibernate proxy safe comparison
        if (o == null || !getClass().isAssignableFrom(o.getClass())) return false;
        Role role = (Role) o;
        // equality based on natural key (name)
        return Objects.equals(name, role.name);
    }

    @Override
    public int hashCode() {
        return Objects.hash(name);
    }

    @Override
    public String toString() {
        return "Role{" +
               "id=" + id +
               ", name='" + name + '\'' +
               ", permissions=" + permissions +
               '}';
    }

    // ------------------------------------------------------------------------
    // Nested types
    // ------------------------------------------------------------------------

    /**
     * Permission enumeration centralised here to remove dependency 
     * on Security module and keep the demo self-contained.
     */
    public enum Permission {
        // Catalog permissions
        PRODUCT_READ,
        PRODUCT_WRITE,
        PRICE_MANAGE,

        // Order permissions
        ORDER_READ,
        ORDER_CREATE,
        ORDER_APPROVE,

        // User permissions
        USER_READ,
        USER_WRITE,
        ROLE_MANAGE,

        // Administration / Others
        SYSTEM_SETTINGS,
        AUDIT_LOG_VIEW
    }
}
```