package com.sprintcart.domain.model.user;

import java.io.Serial;
import java.io.Serializable;
import java.util.Collections;
import java.util.EnumSet;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/**
 * Domain representation of a security Role within SprintCart Pro.
 * <p>
 * A Role is immutable and uniquely identified by a UUID.  Core (a.k.a. system) roles
 * are provided through the {@link SystemRole} enumeration. Merchants may also create
 * ad–hoc roles at runtime via {@link #createCustom(String, String, Set)}.  Business
 * logic should never rely on a role’s name or description directly—use {@link #id()}
 * or {@link #hasPermission(Permission)} whenever possible.
 *
 * Hexagonal architecture note:
 * This class lives in the domain layer and therefore contains <b>no framework-specific
 * annotations</b>. Persistence mappings or JSON bindings must be declared in outbound/
 * inbound adapters respectively.
 */
public final class Role implements Serializable {

    @Serial
    private static final long serialVersionUID = 8906245369700929340L;

    private final UUID id;
    private final String name;
    private final String description;
    private final Set<Permission> permissions;
    private final boolean systemRole;

    private Role(
            UUID id,
            String name,
            String description,
            Set<Permission> permissions,
            boolean systemRole
    ) {
        this.id = Objects.requireNonNull(id, "id must not be null");
        this.name = Objects.requireNonNull(name, "name must not be null");
        this.description = Objects.requireNonNull(description, "description must not be null");
        this.permissions = Set.copyOf(Objects.requireNonNull(permissions, "permissions must not be null"));
        this.systemRole = systemRole;
    }

    /**
     * Factory method for merchant-defined roles.
     */
    public static Role createCustom(String name, String description, Set<Permission> permissions) {
        validateName(name);
        validateDescription(description);
        validatePermissions(permissions);
        return new Role(UUID.randomUUID(), name.trim(), description.trim(), permissions, false);
    }

    /**
     * Returns a system role, which is pre-defined and therefore shares the same UUID
     * across all SprintCart Pro installations.
     */
    public static Role system(SystemRole systemRole) {
        Objects.requireNonNull(systemRole, "systemRole must not be null");
        return systemRole.toDomain();
    }

    public UUID id() {
        return id;
    }

    public String name() {
        return name;
    }

    public String description() {
        return description;
    }

    public boolean isSystemRole() {
        return systemRole;
    }

    /**
     * Returns an immutable view of permissions.
     */
    public Set<Permission> permissions() {
        return permissions;
    }

    /**
     * Checks if this role grants the specified permission.
     */
    public boolean hasPermission(Permission permission) {
        return permissions.contains(permission);
    }

    /* -----------------------------------------------------------------------
     * Validation helpers
     * --------------------------------------------------------------------- */

    private static void validateName(String name) {
        if (name == null || name.trim().isEmpty()) {
            throw new IllegalArgumentException("Role name must not be blank");
        }
    }

    private static void validateDescription(String description) {
        if (description == null || description.trim().isEmpty()) {
            throw new IllegalArgumentException("Role description must not be blank");
        }
    }

    private static void validatePermissions(Set<Permission> permissions) {
        if (permissions == null || permissions.isEmpty()) {
            throw new IllegalArgumentException("Role must have at least one permission");
        }
    }

    /* -----------------------------------------------------------------------
     * Equality / hashing are based solely on the UUID.
     * --------------------------------------------------------------------- */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Role role)) return false;
        return id.equals(role.id);
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    @Override
    public String toString() {
        return "Role[id=%s, name=%s, system=%s]".formatted(id, name, systemRole);
    }

    /* -----------------------------------------------------------------------
     * Nested domain types
     * --------------------------------------------------------------------- */

    /**
     * Fine-grained permissions understood by SpringCart Pro’s authorization layer.
     * <p>
     * These map 1-to-1 onto application use-cases rather than underlying resources,
     * which allows the system to guide user behaviour via productivity nudges.
     */
    public enum Permission {
        // Catalog
        PRODUCT_READ,
        PRODUCT_WRITE,
        PRODUCT_BULK_EDIT,

        // Orders / Fulfilment
        ORDER_READ,
        ORDER_UPDATE_STATUS,
        ORDER_REFUND,

        // Automation Studio
        AUTOMATION_READ,
        AUTOMATION_WRITE,

        // Analytics
        ANALYTICS_VIEW,

        // User / Role Management
        USER_READ,
        USER_WRITE
    }

    /**
     * Built-in roles shipped with the platform.  These are stored in source-control
     * so that their UUIDs remain stable across environments (useful when seeding
     * databases or running migrations).
     */
    public enum SystemRole {

        /**
         * Full read/write access to every feature in SprintCart Pro.
         */
        SUPER_ADMIN(
                UUID.fromString("00000000-0000-0000-0000-000000000001"),
                "Super Admin",
                "Unrestricted access to all resources and administrative tools.",
                EnumSet.allOf(Permission.class)
        ),

        /**
         * Merchant owner with financial permissions but no server / tenant settings.
         */
        MERCHANT_OWNER(
                UUID.fromString("00000000-0000-0000-0000-000000000002"),
                "Merchant Owner",
                "Manages catalog, orders, automation rules and staff accounts.",
                EnumSet.of(
                        Permission.PRODUCT_READ, Permission.PRODUCT_WRITE, Permission.PRODUCT_BULK_EDIT,
                        Permission.ORDER_READ, Permission.ORDER_UPDATE_STATUS, Permission.ORDER_REFUND,
                        Permission.AUTOMATION_READ, Permission.AUTOMATION_WRITE,
                        Permission.ANALYTICS_VIEW,
                        Permission.USER_READ, Permission.USER_WRITE
                )
        ),

        /**
         * Day-to-day operator: manage catalog & orders but cannot edit staff.
         */
        MERCHANT_STAFF(
                UUID.fromString("00000000-0000-0000-0000-000000000003"),
                "Merchant Staff",
                "Handles catalog upkeep and order fulfilment.",
                EnumSet.of(
                        Permission.PRODUCT_READ, Permission.PRODUCT_WRITE, Permission.PRODUCT_BULK_EDIT,
                        Permission.ORDER_READ, Permission.ORDER_UPDATE_STATUS,
                        Permission.ANALYTICS_VIEW
                )
        ),

        /**
         * Restricted to dashboards and metrics—useful for agencies and investors.
         */
        ANALYST(
                UUID.fromString("00000000-0000-0000-0000-000000000004"),
                "Analyst",
                "Read-only access to analytics and reporting.",
                EnumSet.of(Permission.ANALYTICS_VIEW)
        );

        private final UUID uuid;
        private final String displayName;
        private final String description;
        private final Set<Permission> defaultPermissions;

        SystemRole(UUID uuid, String displayName, String description, Set<Permission> defaultPermissions) {
            this.uuid = uuid;
            this.displayName = displayName;
            this.description = description;
            this.defaultPermissions = Collections.unmodifiableSet(defaultPermissions);
        }

        /**
         * Converts the enumeration value into an immutable {@link Role} aggregate.
         */
        Role toDomain() {
            return new Role(uuid, displayName, description, defaultPermissions, true);
        }

        public UUID uuid() {
            return uuid;
        }

        public String displayName() {
            return displayName;
        }

        public String description() {
            return description;
        }

        public Set<Permission> defaultPermissions() {
            return defaultPermissions;
        }
    }
}